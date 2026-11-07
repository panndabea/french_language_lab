"""Run deterministic v2 rules over all interviews. No ground truth, no network calls."""
import argparse
import csv
import datetime
import hashlib
import json
import re
import sqlite3
import zipfile
from pathlib import Path

from .segments import parse_segments
from .rules_v2 import predict, RULES_VERSION
from .validate import validate_outputs

CSV_FIELDS = ['interview_id', 'age_bracket', 'gender', 'interview_year', 'cohort_hypothesis',
              'recording_year_lower_bound', 'out_of_domain_year_flag', 'age_basis', 'status']


def load_segments(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(n for n in z.namelist() if re.fullmatch(r'impactLab/S\d+\.trs', n))
        return {Path(n).stem: parse_segments(z.read(n), Path(n).stem) for n in names}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_sqlite(path, segs):
    conn = sqlite3.connect(path)
    conn.executescript('''DROP TABLE IF EXISTS segments;
      CREATE TABLE segments (interview_id TEXT, seg_index INTEGER, turn_index INTEGER, speaker_id TEXT, role TEXT,
        overlap INTEGER, start_seconds TEXT, turn_start TEXT, turn_end TEXT, text TEXT, PRIMARY KEY(interview_id, seg_index));''')
    with conn:
        for i, ss in segs.items():
            conn.executemany('INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?)',
                             [(i, k, s['turn_index'], s['speaker_id'], s['role'], int(s['overlap']), s['start'],
                               s['turn_start'], s['turn_end'], s['text']) for k, s in enumerate(ss)])
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', default='data/impactLab.zip')
    ap.add_argument('--out', default='outputs')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    segs = load_segments(a.archive)
    write_sqlite(out / 'interviews.sqlite', segs)
    preds = [predict(i, ss) for i, ss in segs.items()]
    rows = []
    for p in preds:
        r = {k: p[k] for k in CSV_FIELDS}
        r['interview_year'] = r['interview_year'] or ''
        r['age_bracket'] = r['age_bracket'] or ''
        r['recording_year_lower_bound'] = r['recording_year_lower_bound'] or ''
        r['age_basis'] = r['age_basis'] or ''
        r['out_of_domain_year_flag'] = str(r['out_of_domain_year_flag'])
        rows.append(r)
    with (out / 'predictions.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    (out / 'evidence.json').write_text(json.dumps(preds, ensure_ascii=False, indent=1), encoding='utf-8')
    errs = validate_outputs(rows, preds, segs, expected_ids=set(segs))
    src_hash = hashlib.sha256(b''.join(Path(f).read_bytes() for f in sorted(Path('src').glob('*.py')))).hexdigest()
    summary = {
        'run_at': datetime.datetime.now().isoformat(timespec='seconds'), 'rules_version': RULES_VERSION,
        'archive_sha256': sha256_file(a.archive), 'src_sha256': src_hash, 'llm_calls': 0, 'ground_truth_accessed': False,
        'interviews': len(segs), 'segments': sum(map(len, segs.values())),
        'interviewee_segments_from_overlap_turns': sum(s['overlap'] and s['role'] == 'interviewee' for ss in segs.values() for s in ss),
        'age_bracket_answered': sum(bool(r['age_bracket']) for r in rows),
        'gender_answered': sum(r['gender'] != 'unknown' for r in rows),
        'interview_year_answered_strict': sum(bool(r['interview_year']) for r in rows),
        'cohort_hypothesis_counts': {k: sum(r['cohort_hypothesis'] == k for r in rows) for k in ('1970', '2005', 'unknown')},
        'gender_counts': {k: sum(r['gender'] == k for r in rows) for k in ('female', 'male', 'unknown')},
        'out_of_domain_year_flags': sorted(r['interview_id'] for r in rows if r['out_of_domain_year_flag'] == 'True'),
        'review_needed': sum(r['status'] == 'review_needed' for r in rows),
        'validation_errors': errs,
    }
    (out / 'summary_v2.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'validation_errors'}, ensure_ascii=False, indent=2))
    print('validation errors:', len(errs), errs[:5])
    return 1 if errs else 0


if __name__ == '__main__':
    raise SystemExit(main())
