"""Fixed JSON schemas, strict validator and chunk renderer for the Claude extraction stage.

Schemas are JSON Schema subsets usable with `output_config.format` (strict JSON
outputs); `check_schema` re-validates locally (no third-party dependency), and
`validate_chunk_output` checks every quote is a verbatim substring of the cited
segment with matching role. No silent truncation: every segment is covered.
"""

AGE_ENUM = [f'{i}-{i + 9}' for i in range(0, 90, 10)] + ['90+']
FIELD_ENUM = ['age', 'gender', 'year', 'occupation', 'residence', 'movement', 'topic']
CONF = ['low', 'medium', 'high']

OBSERVATION = {
    'type': 'object', 'additionalProperties': False,
    'required': ['field', 'candidate_value', 'seg_index', 'quote', 'speaker_role', 'stance', 'about_interviewee', 'note'],
    'properties': {
        'field': {'type': 'string', 'enum': FIELD_ENUM},
        'candidate_value': {'type': 'string'},
        'seg_index': {'type': 'integer'},
        'quote': {'type': 'string'},
        'speaker_role': {'type': 'string', 'enum': ['interviewee', 'interviewer', 'other']},
        'stance': {'type': 'string', 'enum': ['supports', 'contradicts', 'context']},
        'about_interviewee': {'type': 'boolean'},
        'note': {'type': 'string'},
    },
}
CHUNK_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['chunk_id', 'observations'],
    'properties': {'chunk_id': {'type': 'string'}, 'observations': {'type': 'array', 'items': OBSERVATION}},
}
# The live API rejects `type: [..., 'null']` combined with enum (400, 2026-11-07); use sentinels instead:
# age_bracket 'unknown', recording_year_estimate 0, free-text '' -> normalized to None by normalize_decision.
FREE_STR = {'type': 'string'}
DECISION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['age_bracket', 'age_confidence', 'gender', 'gender_confidence', 'recording_year_estimate', 'cohort',
                 'out_of_domain_year_flag', 'hypotheses', 'rationale', 'exploratory'],
    'properties': {
        'age_bracket': {'type': 'string', 'enum': AGE_ENUM + ['unknown']},
        'age_confidence': {'type': 'string', 'enum': CONF},
        'gender': {'type': 'string', 'enum': ['female', 'male', 'unknown']},
        'gender_confidence': {'type': 'string', 'enum': CONF},
        'recording_year_estimate': {'type': 'integer'},
        'cohort': {'type': 'string', 'enum': ['1970', '2005', 'unknown']},
        'out_of_domain_year_flag': {'type': 'boolean'},
        'hypotheses': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['field', 'value', 'support_seg_indexes', 'against_seg_indexes'],
            'properties': {'field': {'type': 'string', 'enum': ['age', 'gender', 'year']}, 'value': {'type': 'string'},
                           'support_seg_indexes': {'type': 'array', 'items': {'type': 'integer'}},
                           'against_seg_indexes': {'type': 'array', 'items': {'type': 'integer'}}}}},
        'rationale': {'type': 'string'},
        'exploratory': {'type': 'object', 'additionalProperties': False,
                        'required': ['occupation', 'residence', 'movement', 'topics'],
                        'properties': {'occupation': FREE_STR, 'residence': FREE_STR, 'movement': FREE_STR,
                                       'topics': {'type': 'array', 'items': {'type': 'string'}}}},
    },
}

_PY = {'string': str, 'integer': int, 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}


def _type_ok(v, t):
    types = t if isinstance(t, list) else [t]
    for name in types:
        if name == 'integer' and isinstance(v, bool):
            continue
        if isinstance(v, _PY[name]):
            return True
    return False


def check_schema(obj, schema, path='$'):
    errs = []
    if 'type' in schema and not _type_ok(obj, schema['type']):
        return [f'{path}: expected {schema["type"]}, got {type(obj).__name__}']
    if 'enum' in schema and obj not in schema['enum']:
        errs.append(f'{path}: {obj!r} not in enum')
    if isinstance(obj, dict) and 'properties' in schema:
        for k in schema.get('required', []):
            if k not in obj:
                errs.append(f'{path}: missing required {k}')
        if schema.get('additionalProperties') is False:
            for k in obj:
                if k not in schema['properties']:
                    errs.append(f'{path}: unexpected key {k}')
        for k, sub in schema['properties'].items():
            if k in obj:
                errs += check_schema(obj[k], sub, f'{path}.{k}')
    if isinstance(obj, list) and 'items' in schema:
        for i, v in enumerate(obj):
            errs += check_schema(v, schema['items'], f'{path}[{i}]')
    return errs


def _role_bucket(role):
    return role if role in ('interviewee', 'interviewer') else 'other'


def validate_chunk_output(obj, segments, chunk_range):
    errs = check_schema(obj, CHUNK_SCHEMA)
    if errs:
        return errs
    lo, hi = chunk_range
    for k, o in enumerate(obj['observations']):
        i = o['seg_index']
        if not lo <= i < hi:
            errs.append(f'obs[{k}]: seg_index {i} outside chunk {chunk_range}')
            continue
        s = segments[i]
        if o['quote'] not in s['text'] or not o['quote'].strip():
            errs.append(f'obs[{k}]: quote not verbatim in seg {i}')
        if _role_bucket(s['role']) != o['speaker_role']:
            errs.append(f'obs[{k}]: speaker_role {o["speaker_role"]} != parsed role {s["role"]}')
    return errs


def normalize_decision(obj):
    """Map API-compatible sentinels back to None."""
    if obj is None:
        return None
    d = dict(obj)
    if d.get('age_bracket') == 'unknown':
        d['age_bracket'] = None
    if not d.get('recording_year_estimate'):
        d['recording_year_estimate'] = None
    if isinstance(d.get('exploratory'), dict):
        d['exploratory'] = {k: (v if v not in ('', None) else None) if k != 'topics' else v
                            for k, v in d['exploratory'].items()}
    return d


def validate_decision(obj):
    return check_schema(obj, DECISION_SCHEMA)


def render_segment(i, s):
    tag = f'[{i}|{s["role"]}|{s["start"]}' + ('|overlap]' if s.get('overlap') else ']')
    return f'{tag} {s["text"]}'


def render_chunks(segments, max_chars=100_000, overlap_segs=10):
    """Split into consecutive chunks of <= max_chars (a single segment may spill), with overlap. Covers all."""
    chunks, start, n = [], 0, len(segments)
    while start < n:
        lines, size, end = [], 0, start
        while end < n:
            line = render_segment(end, segments[end])
            if lines and size + len(line) + 1 > max_chars:
                break
            lines.append(line)
            size += len(line) + 1
            end += 1
        chunks.append({'range': (start, end), 'text': '\n'.join(lines)})
        if end >= n:
            break
        start = max(end - overlap_segs, start + 1)
    return chunks
