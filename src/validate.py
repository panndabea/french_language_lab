"""Validate prediction rows and evidence records against the parsed source. No ground truth."""

AGE_VALUES = {'', None} | {f'{i}-{i + 9}' for i in range(0, 90, 10)} | {'90+'}
GENDER_VALUES = {'female', 'male', 'unknown'}
YEAR_VALUES = {'', None, '1970', '2005'}
COHORT_VALUES = {'1970', '2005', 'unknown'}


def _iter_quotes(ev):
    for cue_list in (ev or {}).values():
        for e in cue_list:
            if isinstance(e, dict) and 'quote' in e:
                yield e


def validate_outputs(rows, evidence, segments_by_id, expected_ids):
    errs = []
    ids = [r['interview_id'] for r in rows]
    if len(ids) != len(set(ids)):
        errs.append('duplicate interview ids in predictions')
    missing = set(expected_ids) - set(ids)
    if missing:
        errs.append(f'missing ids: {sorted(missing)[:10]}')
    extra = set(ids) - set(expected_ids)
    if extra:
        errs.append(f'unexpected ids: {sorted(extra)[:10]}')
    for r in rows:
        i = r['interview_id']
        if r.get('age_bracket') not in AGE_VALUES:
            errs.append(f'{i}: bad age_bracket {r.get("age_bracket")!r}')
        if r.get('gender') not in GENDER_VALUES:
            errs.append(f'{i}: bad gender {r.get("gender")!r}')
        if r.get('interview_year') not in YEAR_VALUES:
            errs.append(f'{i}: bad interview_year {r.get("interview_year")!r}')
        if 'cohort_hypothesis' in r and r['cohort_hypothesis'] not in COHORT_VALUES:
            errs.append(f'{i}: bad cohort_hypothesis {r["cohort_hypothesis"]!r}')
    for rec in evidence:
        i = rec['interview_id']
        index = {(s['speaker_id'], s['start'], s['text']) for s in segments_by_id.get(i, [])}
        for e in _iter_quotes(rec.get('evidence')):
            if (e['speaker_id'], e['start'], e['quote']) not in index:
                errs.append(f'{i}: quote not found verbatim for speaker {e["speaker_id"]} at {e["start"]}: {e["quote"][:60]!r}')
    return errs
