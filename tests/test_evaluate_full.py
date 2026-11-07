"""Synthetic-only tests for the post-freeze evaluator. No real ground truth is read here."""
import unittest
from src.evaluate_full import norm_id, norm_age, norm_gender, norm_year, field_metrics, age_metrics, evaluate

P = {  # frozen-style predictions
    'S001': {'age_bracket': '60-69', 'gender': 'male', 'interview_year': '1970', 'cohort_hypothesis': '1970',
             'source': 'llm', 'llm_status': 'completed', 'age_confidence': 'high', 'gender_confidence': 'high'},
    'S002': {'age_bracket': '30-39', 'gender': 'female', 'interview_year': '', 'cohort_hypothesis': '2005',
             'source': 'llm', 'llm_status': 'completed', 'age_confidence': 'low', 'gender_confidence': 'high'},
    'S003': {'age_bracket': '', 'gender': 'unknown', 'interview_year': '', 'cohort_hypothesis': 'unknown',
             'source': 'rules_fallback', 'llm_status': 'unprocessed', 'age_confidence': '', 'gender_confidence': ''},
}
G = {
    'S001': {'age_bracket': '70-79', 'gender': 'M', 'interview_year': '1970'},
    'S002': {'age_bracket': '30–39', 'gender': 'femme', 'interview_year': '2005'},
    'S003': {'age_bracket': '45', 'gender': 'F', 'interview_year': '1970'},
}


class NormalizeTests(unittest.TestCase):
    def test_ids(self):
        self.assertEqual([norm_id(x) for x in ('S001', 's1', '1', ' S035 ', '035')], ['S001', 'S001', 'S001', 'S035', 'S035'])

    def test_age(self):
        self.assertEqual([norm_age(x) for x in ('60-69', '60–69', '60 - 69', '45', '90+', '95', '', 'unknown')],
                         ['60-69', '60-69', '60-69', '40-49', '90+', '90+', None, None])

    def test_gender_year(self):
        self.assertEqual([norm_gender(x) for x in ('F', 'femme', 'Female', 'H', 'homme', 'm', 'unknown', '')],
                         ['female', 'female', 'female', 'male', 'male', 'male', None, None])
        self.assertEqual([norm_year(x) for x in ('1970', '2005', '1970.0', '', 'unknown')], ['1970', '2005', '1970', None, None])


class MetricTests(unittest.TestCase):
    def test_field_metrics_coverage_accuracy_macro_f1(self):
        m = field_metrics([('male', 'male'), ('female', 'female'), ('female', None), ('male', 'female')])
        self.assertEqual(m['n_gold'], 4)
        self.assertEqual(m['answered'], 3)
        self.assertAlmostEqual(m['coverage'], 0.75)
        self.assertAlmostEqual(m['accuracy_when_answered'], 2 / 3, places=4)
        self.assertAlmostEqual(m['accuracy_all_items'], 0.5)
        # answered-only macro F1: male P=1 R=.5 F=.667; female P=.5 R=1 F=.667
        self.assertAlmostEqual(m['macro_f1_answered'], 0.6667, places=3)
        self.assertEqual(m['confusion']['male']['female'], 1)

    def test_age_adjacent_and_error_distribution(self):
        m = age_metrics([('60-69', '60-69'), ('70-79', '60-69'), ('30-39', '60-69'), ('90+', '80-89'), ('20-29', None)])
        self.assertEqual(m['answered'], 4)
        self.assertAlmostEqual(m['exact_accuracy'], 0.25)
        self.assertAlmostEqual(m['adjacent_accuracy'], 0.75)  # exact or ±1 bin
        self.assertEqual(m['bin_error_distribution'], {'-1': 2, '0': 1, '3': 1})  # pred - gold, in bins


class EvaluateTests(unittest.TestCase):
    def test_end_to_end(self):
        r = evaluate(P, G, rules_pred=P)
        self.assertEqual(r['matching']['missing_predictions'], [])
        self.assertEqual(r['gender']['overall']['accuracy_when_answered'], 1.0)
        self.assertEqual(r['interview_year_strict']['overall']['answered'], 1)
        self.assertEqual(r['cohort_hypothesis']['overall']['answered'], 2)
        self.assertIn('llm', r['gender']['by_source'])
        self.assertIn('low', r['age_bracket']['by_confidence'])
        self.assertIn('processed', r['selection_bias']['interview_year'])
        self.assertEqual(r['age_bracket']['overall']['adjacent_accuracy'], 1.0)
        self.assertTrue(r['errors'])  # S001 age wrong is listed

    def test_id_mismatch_reported(self):
        r = evaluate(P, dict(G, S999={'age_bracket': '', 'gender': 'F', 'interview_year': '1970'}), rules_pred=P)
        self.assertEqual(r['matching']['missing_predictions'], ['S999'])

    def test_unmapped_gold_value_flagged(self):
        r = evaluate(P, dict(G, S003={'age_bracket': 'old', 'gender': 'F', 'interview_year': '1970'}), rules_pred=P)
        self.assertIn('S003', str(r['matching']['unmapped_gold_values']))


if __name__ == '__main__':
    unittest.main()


class EsloFormatTests(unittest.TestCase):
    """Ground-truth format seen 2026-11-07 (after freeze): blind_id, age, sex, wave (ESLO1/ESLO2), recording_id."""
    def test_wave_mapping(self):
        self.assertEqual([norm_year(x) for x in ('ESLO1', 'eslo2', 'ESLO 1')], ['1970', '2005', '1970'])

    def test_read_tsv_with_blind_id_and_aliases(self):
        import tempfile, os
        from src.evaluate_full import read_csv, _gold_field
        with tempfile.NamedTemporaryFile('w', suffix='.tsv', delete=False, encoding='utf-8') as f:
            f.write('blind_id\tage\tsex\twave\trecording_id\nS001\t61\tm\tESLO1\tESLO1_ENT_045\n')
        try:
            g = read_csv(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(norm_year(_gold_field(g['S001'], 'interview_year')), '1970')
        self.assertEqual(norm_gender(_gold_field(g['S001'], 'gender')), 'male')
        self.assertEqual(norm_age(_gold_field(g['S001'], 'age_bracket')), '60-69')
