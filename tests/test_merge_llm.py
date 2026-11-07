import unittest
from src.merge_llm import merge

SEGS = {'S001': [{'speaker_id': 'spk2', 'role': 'interviewee', 'start': '1.0', 'overlap': False, 'text': "j'ai soixante ans"}],
        'S002': [{'speaker_id': 'spk2', 'role': 'interviewee', 'start': '2.0', 'overlap': False, 'text': 'oui'}]}
RULES = {'S001': {'interview_id': 'S001', 'age_bracket': None, 'gender': 'male', 'interview_year': '1970',
                  'cohort_hypothesis': '1970', 'out_of_domain_year_flag': False, 'recording_year_lower_bound': None},
         'S002': {'interview_id': 'S002', 'age_bracket': '30-39', 'gender': 'female', 'interview_year': None,
                  'cohort_hypothesis': 'unknown', 'out_of_domain_year_flag': False, 'recording_year_lower_bound': None}}
LLM = [{'interview_id': 'S001', 'grounding_errors': [],
        'decision': {'age_bracket': '60-69', 'age_confidence': 'high', 'gender': 'male', 'gender_confidence': 'high',
                     'recording_year_estimate': 2010, 'cohort': '2005', 'out_of_domain_year_flag': True,
                     'hypotheses': [], 'rationale': 'r', 'exploratory': {'occupation': None, 'residence': None, 'movement': None, 'topics': []}},
        'observations': [{'field': 'age', 'candidate_value': '60-69', 'seg_index': 0, 'quote': "j'ai soixante ans",
                          'speaker_role': 'interviewee', 'stance': 'supports', 'about_interviewee': True, 'note': ''}],
        'provenance': {'model': 'm'}}]


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.evidence, self.errs = merge(LLM, RULES, SEGS)
        self.by = {r['interview_id']: r for r in self.rows}

    def test_one_row_per_interview_with_source(self):
        self.assertEqual(sorted(self.by), ['S001', 'S002'])
        self.assertEqual(self.by['S001']['source'], 'llm')
        self.assertEqual(self.by['S002']['source'], 'rules_fallback')

    def test_out_of_domain_blanks_strict_year(self):
        r = self.by['S001']
        self.assertEqual((r['interview_year'], r['cohort_hypothesis'], r['out_of_domain_year_flag']), ('', '2005', 'True'))

    def test_rules_disagreement_recorded(self):
        self.assertEqual(self.by['S001']['disagrees_with_rules'], 'cohort_hypothesis')  # blank strict year = abstention, not disagreement

    def test_evidence_enriched_and_valid(self):
        e = self.evidence[0]['evidence']['llm_observations'][0]
        self.assertEqual((e['speaker_id'], e['start']), ('spk2', '1.0'))
        self.assertEqual(self.errs, [])
