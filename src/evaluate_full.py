"""Post-freeze scientific evaluation. Run ONLY on frozen predictions; never feeds back into predictions.

    python -m src.evaluate_full --predictions predictions_frozen.csv --rules outputs/predictions.csv \
        --ground-truth /secure/path/ground_truth.csv --out evaluation/

Reports coverage separately from accuracy, macro-F1, age exact/adjacent accuracy and bin-error distribution,
breakdowns by source / LLM status / confidence, a paired LLM-vs-rules comparison on the LLM-processed subset,
and a selection-bias check (gold label distribution processed vs unprocessed).
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

UNMAPPED = '__UNMAPPED__'
UNKNOWN = {'', 'unknown', 'null', 'none', 'na', 'n/a', '?', 'nan', '-'}
AGE_BINS = [f'{i}-{i + 9}' for i in range(0, 90, 10)] + ['90+']
ALIASES = {'age_bracket': ('age_bracket', 'age', 'age_group', 'tranche_age'),
           'gender': ('gender', 'sex', 'sexe', 'genre'),
           'interview_year': ('interview_year', 'year', 'annee', 'année', 'cohort', 'wave')}
# Interpretation (documented in the report): corpus waves map onto the task's nominal year labels.
WAVE_TO_LABEL = {'eslo1': '1970', 'eslo2': '2005'}


def norm_id(x):
    m = re.fullmatch(r'\s*[sS]?0*(\d+)\s*', str(x))
    return f'S{int(m.group(1)):03d}' if m else str(x).strip()


def _unk(x):
    return str(x if x is not None else '').strip().lower() in UNKNOWN


def norm_age(x):
    if _unk(x):
        return None
    s = re.sub(r'\s+', '', str(x)).replace('–', '-').replace('—', '-').lower()
    m = re.fullmatch(r'(\d{1,3})(?:-(\d{1,3})|\+)?(?:ans)?', s)
    if not m:
        return UNMAPPED
    lo = int(m.group(1))
    return '90+' if lo >= 90 else f'{lo // 10 * 10}-{lo // 10 * 10 + 9}'


def norm_gender(x):
    if _unk(x):
        return None
    s = str(x).strip().lower()
    if s in {'f', 'female', 'femme', 'woman', 'w', 'feminin', 'féminin'}:
        return 'female'
    if s in {'m', 'male', 'h', 'homme', 'man', 'masculin'}:
        return 'male'
    return UNMAPPED


def norm_year(x):
    if _unk(x):
        return None
    w = re.sub(r'\s+', '', str(x)).lower()
    if w in WAVE_TO_LABEL:
        return WAVE_TO_LABEL[w]
    m = re.fullmatch(r'\s*(\d{4})(?:\.0)?\s*', str(x))
    return m.group(1) if m else UNMAPPED


def _f1(pairs, classes):
    f1s = []
    for c in classes:
        tp = sum(g == c and p == c for g, p in pairs)
        fp = sum(g != c and p == c for g, p in pairs)
        fn = sum(g == c and p != c for g, p in pairs)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return round(sum(f1s) / len(f1s), 4) if f1s else None


def field_metrics(pairs):
    """pairs: (gold, pred) with gold not None; pred None = abstention."""
    n = len(pairs)
    ans = [(g, p) for g, p in pairs if p is not None]
    correct = sum(g == p for g, p in ans)
    classes = sorted({g for g, _ in pairs})
    conf = defaultdict(Counter)
    for g, p in pairs:
        conf[g][p if p is not None else 'abstain'] += 1
    return {'n_gold': n, 'answered': len(ans), 'abstained': n - len(ans),
            'coverage': round(len(ans) / n, 4) if n else None,
            'abstention_rate': round((n - len(ans)) / n, 4) if n else None,
            'correct': correct,
            'accuracy_when_answered': round(correct / len(ans), 4) if ans else None,
            'accuracy_all_items': round(correct / n, 4) if n else None,
            'macro_f1_answered': _f1(ans, classes) if ans else None,
            'macro_f1_abstain_as_wrong': _f1(pairs, classes) if n else None,
            'confusion': {g: dict(c) for g, c in sorted(conf.items())}}


def age_metrics(pairs):
    m = field_metrics(pairs)
    ans = [(g, p) for g, p in pairs if p is not None]
    diffs = Counter(str(AGE_BINS.index(p) - AGE_BINS.index(g)) for g, p in ans)
    m['exact_accuracy'] = m['accuracy_when_answered']
    m['adjacent_accuracy'] = round(sum(abs(int(d)) <= 1 for d in diffs.elements()) / len(ans), 4) if ans else None
    m['bin_error_distribution'] = dict(sorted(diffs.items(), key=lambda kv: int(kv[0])))
    m['mean_abs_bin_error'] = round(sum(abs(int(d)) for d in diffs.elements()) / len(ans), 4) if ans else None
    return m


def _gold_field(row, field):
    for k in ALIASES[field]:
        if k in row:
            return row[k]
    return ''


FIELD_SPECS = {  # name: (pred column, gold field, normalizer, metric fn, confidence column)
    'gender': ('gender', 'gender', norm_gender, field_metrics, 'gender_confidence'),
    'age_bracket': ('age_bracket', 'age_bracket', norm_age, age_metrics, 'age_confidence'),
    'interview_year_strict': ('interview_year', 'interview_year', norm_year, field_metrics, None),
    'cohort_hypothesis': ('cohort_hypothesis', 'interview_year', norm_year, field_metrics, None),
}


def evaluate(pred, gold, rules_pred=None):
    pred = {norm_id(k): v for k, v in pred.items()}
    gold = {norm_id(k): v for k, v in gold.items()}
    rules_pred = {norm_id(k): v for k, v in (rules_pred or {}).items()}
    common = sorted(set(pred) & set(gold))
    out = {'matching': {'n_predictions': len(pred), 'n_gold': len(gold), 'n_matched': len(common),
                        'missing_predictions': sorted(set(gold) - set(pred)),
                        'predictions_without_gold': sorted(set(pred) - set(gold)), 'unmapped_gold_values': []},
           'errors': [], 'selection_bias': {}}
    for name, (pcol, gfield, nf, mf, ccol) in FIELD_SPECS.items():
        rows = []
        for i in common:
            g = nf(_gold_field(gold[i], gfield))
            if g == UNMAPPED:
                out['matching']['unmapped_gold_values'].append((i, gfield, _gold_field(gold[i], gfield)))
                continue
            if g is None:
                continue
            p = nf(pred[i].get(pcol, ''))
            p = None if p == UNMAPPED else p
            rp = nf(rules_pred[i].get(pcol, '')) if i in rules_pred else None
            rp = None if rp == UNMAPPED else rp
            rows.append({'id': i, 'gold': g, 'pred': p, 'rules': rp, 'source': pred[i].get('source', ''),
                         'status': pred[i].get('llm_status', ''),
                         'conf': (pred[i].get(ccol) or 'none') if ccol else 'n/a'})
            if p is not None and p != g:
                out['errors'].append({'id': i, 'field': name, 'gold': g, 'pred': p, 'source': rows[-1]['source'],
                                      'confidence': rows[-1]['conf'], 'rules_pred': rp})
        pairs = lambda rs, key='pred': [(r['gold'], r[key]) for r in rs]
        group = lambda key: {k: mf(pairs([r for r in rows if r[key] == k])) for k in sorted({r[key] for r in rows})}
        llm_rows = [r for r in rows if r['source'] == 'llm']
        out[name] = {'overall': mf(pairs(rows)), 'by_source': group('source'), 'by_llm_status': group('status'),
                     'by_confidence': group('conf'),
                     'paired_on_llm_subset': {'llm': mf(pairs(llm_rows)), 'rules': mf(pairs(llm_rows, 'rules'))}}
        if gfield not in out['selection_bias']:
            proc = Counter(r['gold'] for r in rows if r['status'] in ('completed', 'failed'))
            unproc = Counter(r['gold'] for r in rows if r['status'] not in ('completed', 'failed'))
            out['selection_bias'][gfield] = {'processed': dict(proc), 'unprocessed': dict(unproc)}
    out['matching']['unmapped_gold_values'] = sorted(set(map(tuple, out['matching']['unmapped_gold_values'])))
    return out


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t') if sample else csv.excel
        rows = list(csv.DictReader(f, dialect=dialect))
    idcol = next((c for c in rows[0] if c.strip().lower() in ('interview_id', 'blind_id', 'id', 'file', 'filename', 'interview')), None)
    if idcol is None:
        raise ValueError(f'no interview id column in {list(rows[0])}')
    out = {}
    for r in rows:
        r = {k.strip().lower(): v for k, v in r.items()}
        i = norm_id(re.sub(r'\.trs$', '', r[idcol.strip().lower()]))
        if i in out:
            raise ValueError(f'duplicate id {i}')
        out[i] = r
    return out


def main():
    ap = argparse.ArgumentParser(description='Run ONLY after predictions are frozen.')
    ap.add_argument('--predictions', default='predictions_frozen.csv')
    ap.add_argument('--rules', default='outputs/predictions.csv')
    ap.add_argument('--ground-truth', required=True)
    ap.add_argument('--out', default='evaluation')
    a = ap.parse_args()
    sha = hashlib.sha256(Path(a.predictions).read_bytes()).hexdigest()
    r = evaluate(read_csv(a.predictions), read_csv(a.ground_truth), read_csv(a.rules))
    r['frozen_predictions_sha256'] = sha
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'evaluation.json').write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out / 'errors.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'field', 'gold', 'pred', 'source', 'confidence', 'rules_pred'])
        w.writeheader()
        w.writerows(r['errors'])
    summ = {k: r[k]['overall'] for k in FIELD_SPECS}
    print(json.dumps({'matching': r['matching'], 'overall': {k: {m: v[m] for m in ('n_gold', 'coverage', 'accuracy_when_answered',
                      'macro_f1_answered') if m in v} for k, v in summ.items()}}, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
