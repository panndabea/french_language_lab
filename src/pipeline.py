"""Ground-truth-blind TRS import and deliberately conservative rule baseline."""
import argparse
import csv
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

AGE = re.compile(r"\b(?:j['’]\s*ai|je\s+suis\s+âg[ée]\s+de)\s+(\d{1,3})\s+ans\b", re.I)
BORN = re.compile(r"\bje\s+suis\s+n(?:é|ée)\s+en\s+(1[89]\d{2}|20\d{2})\b", re.I)
OUT_OF_RANGE = re.compile(r"\b(?:on\s+est\s+en|nous\s+sommes\s+en)\s+(?:deux\s+mille\s+dix|2010|deux\s+mille\s+onze|2011|20[1-9]\d)\b", re.I)
AGE_BRACKETS = [(i, i+9) for i in range(0,90,10)]

def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()

def parse_trs(content, interview_id):
    root = ET.fromstring(content)
    speakers = {s.attrib['id']: s.attrib.get('name', '') for s in root.findall('.//Speaker')}
    turns = []
    for t in root.findall('.//Turn'):
        # A turn can have multiple speakers: do NOT assign text to one speaker in these cases.
        ids = t.attrib.get('speaker', '').split()
        txt = clean(' '.join(t.itertext()))
        if not txt:
            continue
        turns.append({'interview_id': interview_id, 'speaker_ids': ids,
                      'role': speakers.get(ids[0], 'unknown') if len(ids) == 1 else 'overlap',
                      'start': t.attrib.get('startTime', ''), 'end': t.attrib.get('endTime', ''),
                      'text': txt})
    return turns

def load_archive(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(n for n in z.namelist() if re.fullmatch(r'impactLab/S\d+\.trs', n))
        return {Path(name).stem: parse_trs(z.read(name), Path(name).stem) for name in names}

def db_write(path, data):
    conn = sqlite3.connect(path)
    conn.executescript('''CREATE TABLE IF NOT EXISTS interviews (interview_id TEXT PRIMARY KEY);
       CREATE TABLE IF NOT EXISTS turns (interview_id TEXT, turn_index INTEGER, role TEXT, speaker_ids TEXT, start_seconds TEXT, end_seconds TEXT, text TEXT, PRIMARY KEY(interview_id,turn_index));''')
    with conn:
        for id, turns in data.items():
            conn.execute('INSERT OR REPLACE INTO interviews VALUES (?)', (id,))
            conn.execute('DELETE FROM turns WHERE interview_id=?', (id,))
            conn.executemany('INSERT INTO turns VALUES (?,?,?,?,?,?,?)',
                             [(id,i,t['role'],' '.join(t['speaker_ids']),t['start'],t['end'],t['text']) for i,t in enumerate(turns)])
    conn.close()

def bracket(age):
    if age is None or age < 0 or age > 110: return None
    return f'{age//10*10}-{age//10*10+9}' if age < 90 else '90+'

def baseline(id, turns):
    # Keep direct evidence only; do not force classifications from stereotypes or timelines.
    age_hits, born_hits, gender_hits, year_flags = [], [], [], []
    for t in turns:
        if t['role'] != 'interviewee':
            continue
        txt=t['text']
        for m in AGE.finditer(txt):
            a=int(m.group(1))
            if 0 <= a <= 110:
                age_hits.append((a,txt,t['start']))
        for m in BORN.finditer(txt):
            born_hits.append((int(m.group(1)),txt,t['start']))
            # A self-referential past-participle ending is grammatical evidence, not identity proof.
            gender_hits.append(('female' if re.search(r'née\s+en',m.group(0),re.I) else 'male',txt,t['start']))
        if OUT_OF_RANGE.search(txt):
            year_flags.append((txt,t['start']))
    ages=set(x[0] for x in age_hits)
    age=next(iter(ages)) if len(ages)==1 else None
    genders=set(x[0] for x in gender_hits)
    gender=next(iter(genders)) if len(genders)==1 else 'unknown'
    return {
      'interview_id': id, 'age_bracket': bracket(age), 'gender': gender,
      'interview_year': None, # year is not assumed from vocabulary
      'birth_year_candidates': sorted(set(x[0] for x in born_hits)),
      'out_of_domain_year_flag': bool(year_flags),
      'status': 'review_needed' if year_flags or len(ages)>1 or len(genders)>1 else 'baseline',
      'evidence': {
        'direct_age': [{'text':x[1], 'time':x[2]} for x in age_hits[:5]],
        'birth': [{'text':x[1], 'time':x[2]} for x in born_hits[:5]],
        'gender_grammar': [{'text':x[1], 'time':x[2]} for x in gender_hits[:5]],
        'out_of_domain_year': [{'text':x[0], 'time':x[1]} for x in year_flags[:5]]
      }
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--archive', default='data/impactLab.zip')
    p.add_argument('--out', default='outputs')
    p.add_argument('--sqlite', default='outputs/interviews.sqlite')
    args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    data=load_archive(args.archive)
    db_write(args.sqlite,data)
    predictions=[baseline(id,turns) for id,turns in data.items()]
    with (out/'baseline.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=['interview_id','age_bracket','gender','interview_year','out_of_domain_year_flag','status']);w.writeheader()
        for p0 in predictions:w.writerow({k:p0[k] for k in w.fieldnames})
    (out/'baseline_evidence.json').write_text(json.dumps(predictions,ensure_ascii=False,indent=2),encoding='utf-8')
    counts={'total_interviews':len(data), 'total_turns':sum(map(len,data.values())),
      'age_bracket_found':sum(bool(x['age_bracket']) for x in predictions),
      'gender_grammar_found':sum(x['gender']!='unknown' for x in predictions),
      'interview_year_found':sum(x['interview_year'] is not None for x in predictions),
      'out_of_domain_year_flags':sum(x['out_of_domain_year_flag'] for x in predictions)}
    (out/'summary.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
    print(json.dumps(counts,indent=2))
if __name__=='__main__':main()
