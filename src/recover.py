"""Offline recovery of LLM results from the call cache after a hard stop. Makes NO network calls.

    python -m src.recover --cache outputs/llm_full/cache --out outputs/llm_full/recovered_results.json

Replays run_interview with a client that refuses every call, so only cached (already paid)
responses are used. Classification per interview:
  completed   decision present, no grounding/validation errors
  failed      a cached call returned output that failed validation (after its retry)
  incomplete  some chunks cached but no decision (run stopped mid-interview)
  unprocessed nothing cached
"""
import argparse
import json
from pathlib import Path

from .llm_infer import run_interview

REFUSED = 'NoNetworkRefused'


class NoNetworkRefused(Exception):
    pass


class NoNetworkClient:
    def __init__(self):
        self.attempts = 0

    def complete(self, *a, **k):
        self.attempts += 1
        raise NoNetworkRefused('offline replay: call not in cache')


def classify(r):
    real = [e for e in r['grounding_errors'] if REFUSED not in e]
    pv = r['provenance']
    if r['decision'] is not None and not real and pv['chunks_covered'] == pv['chunks_total']:
        return 'completed'
    if r['decision'] is not None:
        return 'failed'  # decision rests on partial evidence (a chunk failed validation or its call failed live)
    if real:
        return 'failed'
    return 'incomplete' if pv['chunks_covered'] > 0 else 'unprocessed'


def main():
    from .run_v2 import load_segments
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', default='data/impactLab.zip')
    ap.add_argument('--cache', default='outputs/llm_full/cache')
    ap.add_argument('--rules', default='outputs/evidence.json')
    ap.add_argument('--model', default='claude-opus-5-5')
    ap.add_argument('--effort', default='medium')
    ap.add_argument('--max-chars', type=int, default=100_000)
    ap.add_argument('--out', default='outputs/llm_full/recovered_results.json')
    a = ap.parse_args()
    segs = load_segments(a.archive)
    rules = {r['interview_id']: r for r in json.loads(Path(a.rules).read_text(encoding='utf-8'))}
    client, results = NoNetworkClient(), []
    for i in sorted(segs):
        cues = {k: rules[i][k] for k in ('age_bracket', 'gender', 'cohort_hypothesis', 'recording_year_lower_bound',
                                         'present_anchor_years', 'out_of_domain_year_flag', 'evidence_counts')}
        r = run_interview(i, segs[i], client, Path(a.cache), a.model, a.effort, a.max_chars,
                          {'spent_usd': 0.0, 'budget_usd': 1e9}, cues)
        r['status'] = classify(r)
        results.append(r)
    counts = {s: [r['interview_id'] for r in results if r['status'] == s]
              for s in ('completed', 'failed', 'incomplete', 'unprocessed')}
    Path(a.out).write_text(json.dumps({'manifest': {'recovered_offline': True, 'network_calls': 0,
                                                    'counts': {k: len(v) for k, v in counts.items()},
                                                    'ids': {k: v for k, v in counts.items() if k != 'unprocessed'}},
                                       'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: (len(v), v if k != 'unprocessed' and len(v) < 15 else '...') for k, v in counts.items()}, indent=1))
    print('refused (would-be) calls:', client.attempts, '- none sent')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
