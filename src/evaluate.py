"""Standalone post-freeze evaluation. Never run this as part of model development."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

FIELDS=('age_bracket','gender','interview_year')

def read_csv(path):
    with open(path,newline='',encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    if not rows or 'interview_id' not in rows[0]:
        raise ValueError('Missing interview_id column')
    out={}
    for r in rows:
        id=r['interview_id'].strip()
        if not id or id in out: raise ValueError(f'Duplicate or missing ID: {id}')
        out[id]=r
    return out

def normalize(x):
    s=str(x or '').strip().lower()
    if s in {'','null','unknown','none','?','na','n/a'}:return None
    return s

def analyze(pred,truth):
    if set(pred)!=set(truth):
        raise ValueError(f'ID mismatch: missing predictions: {sorted(set(truth)-set(pred))[:8]}; no gold: {sorted(set(pred)-set(truth))[:8]}')
    results={}
    for field in FIELDS:
        if any(field not in r for r in pred.values()) or any(field not in r for r in truth.values()):
            raise ValueError(f'Missing field {field}')
        gold_known=[id for id in truth if normalize(truth[id][field]) is not None]
        covered=[id for id in gold_known if normalize(pred[id][field]) is not None]
        correct=sum(normalize(pred[id][field])==normalize(truth[id][field]) for id in covered)
        confusion=Counter((normalize(truth[id][field]),normalize(pred[id][field])) for id in gold_known)
        results[field]={
          'gold_labeled':len(gold_known), 'answered':len(covered),
          'coverage':round(len(covered)/len(gold_known),4) if gold_known else None,
          'accuracy_when_answered':round(correct/len(covered),4) if covered else None,
          'correct':correct,
          'confusion': [{'ground_truth':a,'prediction':b,'count':v} for (a,b),v in sorted(confusion.items(),key=lambda kv:(str(kv[0][0]),str(kv[0][1])))]
        }
    return results

def main():
    p=argparse.ArgumentParser(description='Run ONLY after predictions are frozen.')
    p.add_argument('--predictions',required=True)
    p.add_argument('--ground-truth',required=True)
    p.add_argument('--output',default='evaluation.json')
    a=p.parse_args()
    r=analyze(read_csv(a.predictions),read_csv(a.ground_truth))
    Path(a.output).write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(r,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
