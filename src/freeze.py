"""Freeze final predictions after the hard stop: LLM where completed, rules fallback otherwise. No GT, no network.

    python -m src.freeze
"""
import csv
import datetime
import glob
import hashlib
import json
import platform
from pathlib import Path

from .merge_llm import merge, FIELDS

FROZEN_FIELDS = FIELDS + ['llm_status']


def build_frozen_rows(llm_results, rules_by_id, segments_by_id):
    status = {r['interview_id']: r.get('status', 'completed') for r in llm_results}
    usable = [r for r in llm_results if status[r['interview_id']] == 'completed']
    rows, evidence, errs = merge(usable, rules_by_id, segments_by_id)
    for row in rows:
        row['llm_status'] = status.get(row['interview_id'], 'unprocessed')
    for rec in evidence:
        rec['llm_status'] = status.get(rec['interview_id'], 'unprocessed')
    return rows, evidence, errs


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    from .run_v2 import load_segments
    from . import llm_infer
    rec = json.loads(Path('outputs/llm_full/recovered_results.json').read_text(encoding='utf-8'))
    rules = {r['interview_id']: r for r in json.loads(Path('outputs/evidence.json').read_text(encoding='utf-8'))}
    rows, evidence, errs = build_frozen_rows(rec['results'], rules, load_segments('data/impactLab.zip'))
    if errs:
        print('VALIDATION ERRORS', errs[:10])
        return 1
    with open('predictions_frozen.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FROZEN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    Path('evidence_frozen.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding='utf-8')
    files = ['predictions_frozen.csv', 'evidence_frozen.json', 'outputs/predictions.csv', 'outputs/evidence.json',
             'outputs/llm_full/recovered_results.json', 'outputs/llm_full/run.log', 'data/impactLab.zip'] + \
        sorted(glob.glob('src/*.py')) + sorted(glob.glob('src/prompts/*.txt')) + sorted(glob.glob('tests/*.py'))
    snap = {
        'frozen_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'ground_truth_accessed': False,
        'stop': 'hard stop by user (time budget expired); inference process SIGTERM 16:00:52; recovered offline from cache',
        'counts': rec['manifest']['counts'], 'status_ids': rec['manifest']['ids'],
        'llm': {'model': 'claude-opus-5-5', 'effort': 'medium', 'thinking': 'adaptive', 'temperature': 'not settable',
                'structured_outputs': 'output_config.format json_schema', 'prompts': {
                    'extract': llm_infer.EXTRACT_PROMPT, 'decide': llm_infer.DECIDE_PROMPT},
                'chunk_max_chars': 100_000, 'chunk_overlap_segments': 10, 'extract_max_tokens': llm_infer.EXTRACT_MAX_TOKENS,
                'decide_max_tokens': llm_infer.DECIDE_MAX_TOKENS, 'retries_per_call': 1},
        'rules_version': json.loads(Path('outputs/summary_v2.json').read_text())['rules_version'],
        'environment': {'python': platform.python_version(), 'platform': platform.platform()},
        'method': 'segments (Who/Sync split) -> rules_v2 cues -> per-chunk evidence extraction (verbatim, role-checked) '
                  '-> per-interview decision with competing hypotheses -> merge (LLM if completed else rules fallback)',
        'sha256': {f: _sha(f) for f in files},
    }
    Path('REPRODUCIBILITY_SNAPSHOT.json').write_text(json.dumps(snap, indent=2), encoding='utf-8')
    src = {s: sum(r['source'] == s for r in rows) for s in ('llm', 'rules_fallback')}
    print(json.dumps({'rows': len(rows), 'source': src, 'llm_status': {s: sum(r['llm_status'] == s for r in rows)
                      for s in ('completed', 'failed', 'incomplete', 'unprocessed')}}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
