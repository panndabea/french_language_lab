"""Merge LLM decisions with frozen rule predictions into one row per interview. No ground truth.

    python -m src.merge_llm --runs outputs/llm_full/run_*.json --out outputs/predictions_llm.csv

Source per row: 'llm' when a schema-valid, grounding-clean decision exists, else 'rules_fallback'.
Strict interview_year is blank whenever out_of_domain_year_flag is set (same policy as rules_v2).
"""
import argparse
import csv
import glob
import json
from pathlib import Path

from .validate import validate_outputs

FIELDS = ['interview_id', 'age_bracket', 'gender', 'interview_year', 'cohort_hypothesis', 'recording_year_estimate',
          'out_of_domain_year_flag', 'age_confidence', 'gender_confidence', 'source', 'disagrees_with_rules']


def _row_from_llm(i, d):
    ood = bool(d['out_of_domain_year_flag'])
    cohort = d['cohort']
    return {'interview_id': i, 'age_bracket': d['age_bracket'] or '', 'gender': d['gender'],
            'interview_year': cohort if cohort != 'unknown' and not ood else '', 'cohort_hypothesis': cohort,
            'recording_year_estimate': d['recording_year_estimate'] or '', 'out_of_domain_year_flag': str(ood),
            'age_confidence': d['age_confidence'], 'gender_confidence': d['gender_confidence'], 'source': 'llm'}


def _row_from_rules(i, r):
    return {'interview_id': i, 'age_bracket': r['age_bracket'] or '', 'gender': r['gender'],
            'interview_year': r['interview_year'] or '', 'cohort_hypothesis': r['cohort_hypothesis'],
            'recording_year_estimate': '', 'out_of_domain_year_flag': str(bool(r['out_of_domain_year_flag'])),
            'age_confidence': '', 'gender_confidence': '', 'source': 'rules_fallback'}


def merge(llm_results, rules_by_id, segments_by_id):
    latest = {}
    for r in llm_results:  # later runs override earlier ones
        if r.get('decision') and not r.get('grounding_errors'):
            latest[r['interview_id']] = r
    rows, evidence = [], []
    for i in sorted(segments_by_id):
        rule = rules_by_id[i]
        if i in latest:
            lr = latest[i]
            row = _row_from_llm(i, lr['decision'])
            rr = _row_from_rules(i, rule)
            row['disagrees_with_rules'] = ';'.join(
                k for k in ('age_bracket', 'gender', 'interview_year', 'cohort_hypothesis')
                if rr[k] not in ('', 'unknown') and row[k] not in ('', 'unknown') and rr[k] != row[k])
            segs = segments_by_id[i]
            obs = [dict(o, speaker_id=segs[o['seg_index']]['speaker_id'], start=segs[o['seg_index']]['start'],
                        role=segs[o['seg_index']]['role']) for o in lr['observations']]
            evidence.append({'interview_id': i, 'source': 'llm', 'decision': lr['decision'],
                             'provenance': lr['provenance'], 'evidence': {'llm_observations': obs}})
        else:
            row = _row_from_rules(i, rule)
            row['disagrees_with_rules'] = ''
            evidence.append({'interview_id': i, 'source': 'rules_fallback', 'evidence': rule.get('evidence', {})})
        rows.append(row)
    # LLM observation quotes are substrings of a segment, not whole segments: check substring + speaker + time.
    errs = validate_outputs(rows, [], segments_by_id, expected_ids=set(segments_by_id))
    for rec in evidence:
        if rec['source'] != 'llm':
            continue
        idx = {(s['speaker_id'], s['start']): s['text'] for s in segments_by_id[rec['interview_id']]}
        for o in rec['evidence']['llm_observations']:
            if o['quote'] not in idx.get((o['speaker_id'], o['start']), ''):
                errs.append(f'{rec["interview_id"]}: LLM quote not verbatim at {o["start"]}')
    return rows, evidence, errs


def main():
    from .run_v2 import load_segments
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', nargs='+', required=True)
    ap.add_argument('--archive', default='data/impactLab.zip')
    ap.add_argument('--rules', default='outputs/evidence.json')
    ap.add_argument('--out', default='outputs/predictions_llm.csv')
    a = ap.parse_args()
    files = sorted(f for pat in a.runs for f in glob.glob(pat))
    results = [r for f in files for r in json.loads(Path(f).read_text(encoding='utf-8'))['results']]
    rules = {r['interview_id']: r for r in json.loads(Path(a.rules).read_text(encoding='utf-8'))}
    rows, evidence, errs = merge(results, rules, load_segments(a.archive))
    out = Path(a.out)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    out.with_name(out.stem.replace('predictions', 'evidence') + '.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding='utf-8')
    src = {s: sum(r['source'] == s for r in rows) for s in ('llm', 'rules_fallback')}
    print(json.dumps({'run_files': files, 'rows': len(rows), 'source': src,
                      'disagreements': sum(bool(r['disagrees_with_rules']) for r in rows), 'validation_errors': errs[:10]}, indent=1))
    return 1 if errs else 0


if __name__ == '__main__':
    raise SystemExit(main())
