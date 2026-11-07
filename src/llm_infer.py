"""Chunked Claude evidence-collection + decision pipeline. SAFE BY DEFAULT.

    python -m src.llm_infer                      # plan only: chunk counts + cost estimate, NO API calls
    python -m src.llm_infer --execute --approved-budget-usd 5 --ids S035,S002 ...   # real calls

Real calls require --execute, an explicit budget and an explicit ID list (approval
recorded in the run manifest). Every call is cached on disk keyed by
(model, effort, prompt hash, chunk text hash) so re-runs never repeat a call.
Spend is tracked from response usage; a call is refused if its worst-case cost
would exceed the remaining budget. Data-protection note: --execute sends
transcript text to the Anthropic API; confirm permission before using it.
"""
import argparse
import datetime
import hashlib
import json
import uuid
from pathlib import Path

from .llm_schema import CHUNK_SCHEMA, DECISION_SCHEMA, render_chunks, validate_chunk_output, validate_decision, normalize_decision

PROMPT_DIR = Path(__file__).parent / 'prompts'
EXTRACT_PROMPT = 'extract_v1.txt'
DECIDE_PROMPT = 'decide_v3.txt'  # v3: inference discipline (S002 pilot lesson); v2: sentinels
# USD per 1M tokens (input, output) - from claude-api reference cached 2026-10-06; re-check before a paid run.
PRICING = {'claude-opus-5-5': (4.00, 20.00), 'claude-sonnet-5-5': (2.00, 10.00), 'claude-haiku-5-5': (0.10, 0.50)}
CHARS_PER_TOKEN = 3.2          # conservative for French with tags; verify with count_tokens before a paid run
EXTRACT_MAX_TOKENS = 8000
DECIDE_MAX_TOKENS = 8000
EST_OUTPUT_TOKENS_PER_CALL = 1500   # incl. thinking; planning assumption, logged as such


class ApprovalRequired(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def _sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def load_prompt(name):
    return (PROMPT_DIR / name).read_text(encoding='utf-8')


def cost(model, input_tokens, output_tokens):
    pi, po = PRICING[model]
    return input_tokens / 1e6 * pi + output_tokens / 1e6 * po


def check_approval(execute, budget, ids):
    if not execute:
        return
    if budget is None or budget <= 0:
        raise ApprovalRequired('--approved-budget-usd is required for --execute')
    if not ids:
        raise ApprovalRequired('--ids is required for --execute (no implicit full-corpus runs)')


def plan(segments_by_id, max_chars=100_000, model='claude-opus-5-5', overlap_segs=10):
    sys_chars = len(load_prompt(EXTRACT_PROMPT))
    n_chunks, in_chars, per = 0, 0, {}
    for i, segs in segments_by_id.items():
        ch = render_chunks(segs, max_chars=max_chars, overlap_segs=overlap_segs)
        per[i] = len(ch)
        n_chunks += len(ch)
        in_chars += sum(len(c['text']) + sys_chars for c in ch)
    n = len(segments_by_id)
    decide_in_tokens = n * 6000  # aggregated observations + system prompt; assumption
    in_tok = in_chars / CHARS_PER_TOKEN + decide_in_tokens
    out_tok = (n_chunks + n) * EST_OUTPUT_TOKENS_PER_CALL
    est = {m: round(cost(m, in_tok, out_tok), 2) for m in PRICING}
    return {'interviews': n, 'chunks': n_chunks, 'calls': n_chunks + n, 'max_chars_per_chunk': max_chars,
            'estimated_input_tokens': int(in_tok), 'estimated_output_tokens': int(out_tok),
            'estimated_cost_usd': est, 'estimated_cost_usd_batch_api_50pct': {m: round(v / 2, 2) for m, v in est.items()},
            'chunks_per_interview_max': max(per.values()) if per else 0, 'assumptions': {
                'chars_per_token': CHARS_PER_TOKEN, 'output_tokens_per_call': EST_OUTPUT_TOKENS_PER_CALL,
                'decision_input_tokens_per_interview': 6000}, 'default_model': model}


class AnthropicClient:
    """Thin wrapper over the official SDK (imported lazily so tests/plan need no dependency)."""
    def __init__(self):
        import anthropic  # noqa: WPS433
        self._c = anthropic.Anthropic()

    def complete(self, system, user, schema, model, effort, max_tokens):
        with self._c.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            thinking={'type': 'adaptive'},
            output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}},
            messages=[{'role': 'user', 'content': user}],
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == 'refusal':
            raise RuntimeError(f'refusal: {getattr(msg, "stop_details", None)}')
        if msg.stop_reason == 'max_tokens':
            raise RuntimeError('max_tokens reached; output truncated')
        text = next(b.text for b in msg.content if b.type == 'text')
        return text, {'input_tokens': msg.usage.input_tokens, 'output_tokens': msg.usage.output_tokens}


def _call(client, cache_dir, key_parts, system, user, schema, model, effort, max_tokens, ledger, validator):
    """Cached call with budget guard and at most one corrective retry. Returns (obj, errors, retries)."""
    key = _sha(json.dumps(key_parts, sort_keys=True))
    path = cache_dir / f'{key}.json'
    if path.exists():
        rec = json.loads(path.read_text(encoding='utf-8'))
        return rec['output'], rec['errors'], rec['retries']
    retries, errors, obj, msg, usages, spent = 0, [], None, user, [], 0.0
    for attempt in range(2):
        worst = cost(model, (len(system) + len(msg)) / CHARS_PER_TOKEN, max_tokens)
        if ledger['spent_usd'] + worst > ledger['budget_usd']:
            raise BudgetExceeded(f'next call worst-case ${worst:.3f} would exceed budget '
                                 f'(spent ${ledger["spent_usd"]:.3f} of ${ledger["budget_usd"]:.2f})')
        try:
            text, usage = client.complete(system, msg, schema, model, effort, max_tokens)
        except BudgetExceeded:
            raise
        except Exception as e:  # API/HTTP errors: record, do not cache, so a fixed request can retry
            return None, [f'api_error: {type(e).__name__}: {e}'[:500]], retries
        c = cost(model, usage['input_tokens'], usage['output_tokens'])
        ledger['spent_usd'] += c
        spent += c
        usages.append(usage)
        ledger.setdefault('usage', []).append(usage)
        try:
            obj = json.loads(text)
            errors = validator(obj)
        except json.JSONDecodeError as e:
            obj, errors = None, [f'invalid JSON: {e}']
        if not errors:
            break
        if attempt == 0:
            retries = 1
            msg = user + '\n\nYour previous answer failed validation:\n- ' + '\n- '.join(errors[:20]) + \
                '\nReturn the full corrected JSON. Quotes must be exact substrings of the cited segment.'
    path.write_text(json.dumps({'key_parts': key_parts, 'output': obj, 'errors': errors, 'retries': retries,
                                'usage': usages, 'cost_usd': round(spent, 6)},
                               ensure_ascii=False), encoding='utf-8')
    return obj, errors, retries


def run_interview(interview_id, segments, client, cache_dir, model, effort, max_chars, ledger, rule_cues=None,
                  overlap_segs=10):
    cache_dir.mkdir(parents=True, exist_ok=True)
    sys_x, sys_d = load_prompt(EXTRACT_PROMPT), load_prompt(DECIDE_PROMPT)
    chunks = render_chunks(segments, max_chars=max_chars, overlap_segs=overlap_segs)
    observations, grounding_errors, retries, covered = [], [], 0, 0
    for k, ch in enumerate(chunks):
        cid = f'{interview_id}-c{k}'
        user = f'chunk_id={cid}\ninterview_id={interview_id} chunk {k + 1}/{len(chunks)} segments {ch["range"][0]}-{ch["range"][1] - 1}\n\n{ch["text"]}'
        obj, errs, r = _call(client, cache_dir, [model, effort, _sha(sys_x), _sha(user)], sys_x, user, CHUNK_SCHEMA,
                             model, effort, EXTRACT_MAX_TOKENS, ledger,
                             lambda o, rng=ch['range']: validate_chunk_output(o, segments, rng))
        retries += r
        if obj is not None and not errs:
            covered += 1
            observations += [dict(o, chunk_id=cid) for o in obj['observations']]
        else:
            grounding_errors += [f'{cid}: {e}' for e in errs]
    # de-duplicate observations seen twice in chunk overlaps
    seen, uniq = set(), []
    for o in observations:
        key = (o['field'], o['seg_index'], o['quote'], o['candidate_value'])
        if key not in seen:
            seen.add(key)
            uniq.append(o)
    payload = {'interview_id': interview_id, 'chunks_total': len(chunks), 'chunks_with_valid_output': covered,
               'observations': [{k: o[k] for k in ('field', 'candidate_value', 'seg_index', 'quote', 'speaker_role',
                                                    'stance', 'about_interviewee', 'note')} for o in uniq],
               'rule_based_cues': rule_cues or {}}
    user_d = json.dumps(payload, ensure_ascii=False)
    decision, derrs, r = _call(client, cache_dir, [model, effort, _sha(sys_d), _sha(user_d)], sys_d, user_d,
                               DECISION_SCHEMA, model, effort, DECIDE_MAX_TOKENS, ledger, validate_decision)
    retries += r
    grounding_errors += [f'decision: {e}' for e in derrs]
    decision = normalize_decision(decision) if decision is not None and not derrs else None
    return {'interview_id': interview_id, 'decision': decision, 'observations': uniq, 'grounding_errors': grounding_errors,
            'provenance': {'model': model, 'effort': effort, 'thinking': 'adaptive',
                           'temperature': 'not settable (sampling params removed on current models)',
                           'prompt_files': [EXTRACT_PROMPT, DECIDE_PROMPT],
                           'prompt_sha256': {EXTRACT_PROMPT: _sha(sys_x), DECIDE_PROMPT: _sha(sys_d)},
                           'chunks_total': len(chunks), 'chunks_covered': covered, 'max_chars': max_chars,
                           'overlap_segs': overlap_segs, 'retries': retries}}


def main():
    from .run_v2 import load_segments
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', default='data/impactLab.zip')
    ap.add_argument('--out', default='outputs/llm')
    ap.add_argument('--model', default='claude-opus-5-5', choices=sorted(PRICING))
    ap.add_argument('--effort', default='medium', choices=['low', 'medium', 'high', 'xhigh', 'max'])
    ap.add_argument('--max-chars', type=int, default=100_000)
    ap.add_argument('--execute', action='store_true', help='make paid API calls (requires approval flags)')
    ap.add_argument('--approved-budget-usd', type=float)
    ap.add_argument('--approved-by', default='')
    ap.add_argument('--ids', help='comma-separated interview ids')
    a = ap.parse_args()
    ids = [x.strip() for x in a.ids.split(',')] if a.ids else None
    check_approval(a.execute, a.approved_budget_usd, ids)
    segs = load_segments(a.archive)
    sel = {i: segs[i] for i in (ids or segs)}
    p = plan(sel, max_chars=a.max_chars, model=a.model)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'plan.json').write_text(json.dumps(p, indent=2), encoding='utf-8')
    print(json.dumps(p, indent=2))
    if not a.execute:
        print('Plan only. No API calls made.')
        return 0
    rules = {r['interview_id']: r for r in json.loads(Path('outputs/evidence.json').read_text(encoding='utf-8'))}
    run_id = datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    ledger = {'spent_usd': 0.0, 'budget_usd': a.approved_budget_usd}
    client = AnthropicClient()
    results, stop_reason = [], None
    try:
        for i in sel:
            cues = {k: rules[i][k] for k in ('age_bracket', 'gender', 'cohort_hypothesis', 'recording_year_lower_bound',
                                             'present_anchor_years', 'out_of_domain_year_flag', 'evidence_counts')}
            results.append(run_interview(i, sel[i], client, out / 'cache', a.model, a.effort, a.max_chars, ledger, cues))
            print(f'{i}: done, spent ${ledger["spent_usd"]:.3f}')
    except BudgetExceeded as e:
        stop_reason = f'budget: {e}'
        print('STOPPED:', e)
    except Exception as e:  # never lose the ledger
        stop_reason = f'error: {type(e).__name__}: {e}'
        print('STOPPED:', stop_reason)
    manifest = {'stop_reason': stop_reason, 'usage_calls': len(ledger.get('usage', [])),'run_id': run_id, 'approved_budget_usd': a.approved_budget_usd, 'approved_by': a.approved_by,
                'spent_usd': round(ledger['spent_usd'], 4), 'ids': ids, 'completed': [r['interview_id'] for r in results],
                'model': a.model, 'effort': a.effort, 'plan': p}
    (out / f'run_{run_id}.json').write_text(json.dumps({'manifest': manifest, 'results': results}, ensure_ascii=False,
                                                       indent=1), encoding='utf-8')
    print(json.dumps(manifest, indent=1)[:2000])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
