import copy
import unittest
from src.llm_schema import (CHUNK_SCHEMA, DECISION_SCHEMA, check_schema, validate_chunk_output,
                            validate_decision, render_chunks)

SEGS = [
    {'speaker_id': 'spk1', 'role': 'interviewer', 'start': '0', 'overlap': False, 'text': 'vous avez quel âge ?'},
    {'speaker_id': 'spk2', 'role': 'interviewee', 'start': '2.5', 'overlap': False, 'text': "moi j'ai soixante-cinq ans"},
    {'speaker_id': 'spk2', 'role': 'interviewee', 'start': '5', 'overlap': True, 'text': 'on est en deux mille dix'},
]

OBS = {'field': 'age', 'candidate_value': '60-69', 'seg_index': 1, 'quote': "j'ai soixante-cinq ans",
       'speaker_role': 'interviewee', 'stance': 'supports', 'about_interviewee': True, 'note': 'direct statement'}
CHUNK = {'chunk_id': 'S000-c0', 'observations': [OBS]}
DECISION = {
    'age_bracket': '60-69', 'age_confidence': 'high', 'gender': 'unknown', 'gender_confidence': 'low',
    'recording_year_estimate': 2010, 'cohort': '2005', 'out_of_domain_year_flag': True,
    'hypotheses': [{'field': 'year', 'value': '2010', 'support_seg_indexes': [2], 'against_seg_indexes': []}],
    'rationale': 'x', 'exploratory': {'occupation': '', 'residence': '', 'movement': '', 'topics': []},
}


class SchemaTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(check_schema(CHUNK, CHUNK_SCHEMA), [])
        self.assertEqual(check_schema(DECISION, DECISION_SCHEMA), [])

    def test_extra_key_and_bad_enum(self):
        c = copy.deepcopy(CHUNK)
        c['observations'][0]['field'] = 'shoe_size'
        c['extra'] = 1
        errs = check_schema(c, CHUNK_SCHEMA)
        self.assertEqual(len(errs), 2)

    def test_missing_required(self):
        d = copy.deepcopy(DECISION)
        del d['gender']
        self.assertTrue(check_schema(d, DECISION_SCHEMA))

    def test_decision_age_enum(self):
        d = copy.deepcopy(DECISION)
        d['age_bracket'] = '65'
        self.assertTrue(validate_decision(d))


class GroundingTests(unittest.TestCase):
    def test_valid_grounding(self):
        self.assertEqual(validate_chunk_output(CHUNK, SEGS, chunk_range=(0, 3)), [])

    def test_fabricated_quote(self):
        c = copy.deepcopy(CHUNK)
        c['observations'][0]['quote'] = "j'ai soixante-dix ans"
        self.assertTrue(any('quote' in e for e in validate_chunk_output(c, SEGS, chunk_range=(0, 3))))

    def test_role_mismatch(self):
        c = copy.deepcopy(CHUNK)
        c['observations'][0]['seg_index'] = 0
        c['observations'][0]['quote'] = 'quel âge'
        self.assertTrue(any('role' in e for e in validate_chunk_output(c, SEGS, chunk_range=(0, 3))))

    def test_seg_outside_chunk(self):
        self.assertTrue(any('outside' in e for e in validate_chunk_output(CHUNK, SEGS, chunk_range=(2, 3))))


class ChunkingTests(unittest.TestCase):
    def test_no_truncation_and_overlap(self):
        segs = [{'speaker_id': 'spk2', 'role': 'interviewee', 'start': str(i), 'overlap': False, 'text': 'mot ' * 50}
                for i in range(100)]
        chunks = render_chunks(segs, max_chars=2000, overlap_segs=2)
        covered = set()
        for c in chunks:
            covered.update(range(*c['range']))
            self.assertLessEqual(len(c['text']), 2000 + 400)  # one segment may spill
        self.assertEqual(covered, set(range(100)))
        self.assertEqual(chunks[1]['range'][0], chunks[0]['range'][1] - 2)

    def test_render_marks_overlap(self):
        c = render_chunks(SEGS, max_chars=10_000)[0]
        self.assertIn('[2|interviewee|5|overlap]', c['text'])
        self.assertIn("[1|interviewee|2.5] moi j'ai soixante-cinq ans", c['text'])


if __name__ == '__main__':
    unittest.main()


class ApiCompatibilityTests(unittest.TestCase):
    """Live API (2026-11-07, req_011CgocNVVgJ1qqV2bNryeAN) rejected enum + type ['string','null']."""
    def _walk(self, node):
        if isinstance(node, dict):
            yield node
            for v in node.values():
                yield from self._walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from self._walk(v)

    def test_no_type_arrays_in_schemas(self):
        for schema in (CHUNK_SCHEMA, DECISION_SCHEMA):
            for node in self._walk(schema):
                self.assertNotIsInstance(node.get('type'), list, node)

    def test_normalize_decision_sentinels(self):
        from src.llm_schema import normalize_decision
        d = copy.deepcopy(DECISION)
        d.update(age_bracket='unknown', recording_year_estimate=0)
        d['exploratory'] = {'occupation': '', 'residence': 'Orléans', 'movement': '', 'topics': []}
        n = normalize_decision(d)
        self.assertIsNone(n['age_bracket'])
        self.assertIsNone(n['recording_year_estimate'])
        self.assertIsNone(n['exploratory']['occupation'])
        self.assertEqual(n['exploratory']['residence'], 'Orléans')
