"""Reproducible results table from evaluation/evaluation.json -> evaluation/results_table.{csv,md}."""
import csv
import json
from pathlib import Path

E = json.loads(Path('evaluation/evaluation.json').read_text(encoding='utf-8'))
ROWS = []
for field, label in (('gender', 'Gender'), ('age_bracket', 'Age bracket'), ('cohort_hypothesis', 'Wave (cohort label)'),
                     ('interview_year_strict', 'Interview year (strict; blank if out-of-domain)')):
    for scope, m in (('All 192 (frozen: LLM 99 + rules fallback 93)', E[field]['overall']),
                     ('LLM-completed subset (n=99): LLM', E[field]['paired_on_llm_subset']['llm']),
                     ('LLM-completed subset (n=99): rules only', E[field]['paired_on_llm_subset']['rules']),
                     ('Rules-fallback subset (n=93)', E[field]['by_source'].get('rules_fallback', {}))):
        if not m:
            continue
        ROWS.append({'field': label, 'scope': scope, 'n': m['n_gold'], 'answered': m['answered'],
                     'coverage': m['coverage'], 'accuracy_when_answered': m['accuracy_when_answered'],
                     'accuracy_all_items': m['accuracy_all_items'], 'macro_f1_answered': m['macro_f1_answered'],
                     'adjacent_accuracy': m.get('adjacent_accuracy', '')})
with open('evaluation/results_table.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(ROWS[0]))
    w.writeheader()
    w.writerows(ROWS)
fmt = lambda v: f'{v:.1%}' if isinstance(v, float) else str(v)
md = ['| Field | Scope | n | Answered | Coverage | Acc. (answered) | Acc. (all items) | Macro-F1 (answered) | Adjacent acc. |',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|']
md += ['| ' + ' | '.join(fmt(r[k]) for k in r) + ' |' for r in ROWS]
Path('evaluation/results_table.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
print('\n'.join(md))
