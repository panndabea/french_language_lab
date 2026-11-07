import unittest
from src.validate import validate_outputs

SEGS = {'S001': [{'interview_id': 'S001', 'turn_index': 0, 'speaker_id': 'spk2', 'role': 'interviewee',
                  'overlap': False, 'start': '1.0', 'text': "j'ai soixante ans"}]}


def row(**kw):
    r = {'interview_id': 'S001', 'age_bracket': '60-69', 'gender': 'unknown', 'interview_year': '',
         'cohort_hypothesis': 'unknown', 'out_of_domain_year_flag': 'False', 'status': 'rules'}
    r.update(kw)
    return r


def evid(quote="j'ai soixante ans", spk='spk2', start='1.0'):
    return [{'interview_id': 'S001', 'evidence': {'age': [{'quote': quote, 'speaker_id': spk, 'start': start, 'turn_index': 0}]}}]


class ValidateTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate_outputs([row()], evid(), SEGS, expected_ids={'S001'}), [])

    def test_missing_and_duplicate_ids(self):
        errs = validate_outputs([row(), row()], evid(), SEGS, expected_ids={'S001', 'S002'})
        self.assertTrue(any('duplicate' in e for e in errs))
        self.assertTrue(any('missing' in e for e in errs))

    def test_bad_values(self):
        errs = validate_outputs([row(age_bracket='65', gender='f', interview_year='2010')], evid(), SEGS, expected_ids={'S001'})
        self.assertEqual(len(errs), 3)

    def test_fabricated_quote_detected(self):
        errs = validate_outputs([row()], evid(quote="j'ai soixante-dix ans"), SEGS, expected_ids={'S001'})
        self.assertTrue(any('quote' in e for e in errs))

    def test_wrong_speaker_detected(self):
        errs = validate_outputs([row()], evid(spk='spk1'), SEGS, expected_ids={'S001'})
        self.assertTrue(any('quote' in e for e in errs))


if __name__ == '__main__':
    unittest.main()
