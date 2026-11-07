import json
import tempfile
import unittest
from pathlib import Path
from src.llm_infer import plan, run_interview, BudgetExceeded, ApprovalRequired, check_approval, PRICING

SEGS = [{'speaker_id': 'spk2', 'role': 'interviewee', 'start': str(i), 'overlap': False,
         'text': "moi j'ai soixante-cinq ans" if i == 3 else 'oui ' * 30} for i in range(40)]


class FakeClient:
    """Returns canned JSON; counts calls. No network."""
    def __init__(self, bad_first=False):
        self.calls = 0
        self.bad_first = bad_first

    def complete(self, system, user, schema, model, effort, max_tokens):
        self.calls += 1
        if 'observations' in schema['properties']:
            cid = user.split('chunk_id=')[1].split('\n')[0]
            obs = []
            if '[3|' in user:
                q = "j'ai soixante-cinq ans" if not (self.bad_first and self.calls == 1) else "j'ai soixante-dix ans"
                obs = [{'field': 'age', 'candidate_value': '60-69', 'seg_index': 3, 'quote': q, 'speaker_role': 'interviewee',
                        'stance': 'supports', 'about_interviewee': True, 'note': ''}]
            out = {'chunk_id': cid, 'observations': obs}
        else:
            out = {'age_bracket': '60-69', 'age_confidence': 'high', 'gender': 'unknown', 'gender_confidence': 'low',
                   'recording_year_estimate': 0, 'cohort': 'unknown', 'out_of_domain_year_flag': False,
                   'hypotheses': [], 'rationale': 'r', 'exploratory': {'occupation': '', 'residence': '',
                                                                         'movement': '', 'topics': []}}
        return json.dumps(out), {'input_tokens': 1000, 'output_tokens': 200}


class PlanTests(unittest.TestCase):
    def test_plan_counts_and_cost_no_calls(self):
        p = plan({'S000': SEGS, 'S001': SEGS}, max_chars=500, model='claude-opus-5-5')
        self.assertEqual(p['interviews'], 2)
        self.assertGreater(p['chunks'], 2)
        self.assertGreater(p['estimated_cost_usd']['claude-opus-5-5'], 0)
        self.assertIn('claude-haiku-5-5', p['estimated_cost_usd'])

    def test_approval_required(self):
        with self.assertRaises(ApprovalRequired):
            check_approval(execute=True, budget=None, ids=['S001'])
        with self.assertRaises(ApprovalRequired):
            check_approval(execute=True, budget=5.0, ids=None)
        check_approval(execute=True, budget=5.0, ids=['S001'])


class RunTests(unittest.TestCase):
    def test_run_validates_caches_and_records(self):
        with tempfile.TemporaryDirectory() as d:
            c = FakeClient()
            ledger = {'spent_usd': 0.0, 'budget_usd': 10.0}
            r = run_interview('S000', SEGS, c, Path(d), model='claude-opus-5-5', effort='medium', max_chars=500, ledger=ledger)
            n = c.calls
            self.assertEqual(r['decision']['age_bracket'], '60-69')
            self.assertEqual(r['grounding_errors'], [])
            self.assertIn('prompt_sha256', r['provenance'])
            self.assertEqual(r['provenance']['chunks_covered'], r['provenance']['chunks_total'])
            # second run: fully cached, zero new calls
            run_interview('S000', SEGS, c, Path(d), model='claude-opus-5-5', effort='medium', max_chars=500, ledger=ledger)
            self.assertEqual(c.calls, n)

    def test_fabricated_quote_retried_once_then_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            c = FakeClient(bad_first=True)
            ledger = {'spent_usd': 0.0, 'budget_usd': 10.0}
            r = run_interview('S000', SEGS, c, Path(d), model='claude-opus-5-5', effort='medium', max_chars=10_000, ledger=ledger)
            self.assertEqual(r['grounding_errors'], [])
            self.assertEqual(r['provenance']['retries'], 1)

    def test_budget_stop(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = {'spent_usd': 0.0, 'budget_usd': 0.001}
            with self.assertRaises(BudgetExceeded):
                run_interview('S000', SEGS, FakeClient(), Path(d), model='claude-opus-5-5', effort='medium', max_chars=500, ledger=ledger)

    def test_pricing_table_has_default_model(self):
        self.assertIn('claude-opus-5-5', PRICING)


if __name__ == '__main__':
    unittest.main()


class RobustnessTests(unittest.TestCase):
    def test_usage_stored_in_cache(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = {'spent_usd': 0.0, 'budget_usd': 10.0}
            run_interview('S000', SEGS, FakeClient(), Path(d), model='claude-opus-5-5', effort='medium', max_chars=500, ledger=ledger)
            recs = [json.loads(p.read_text()) for p in Path(d).glob('*.json')]
            self.assertTrue(recs and all(r['usage'] and r['cost_usd'] > 0 for r in recs))

    def test_api_error_is_recorded_not_raised(self):
        class Boom(FakeClient):
            def complete(self, system, user, schema, model, effort, max_tokens):
                if 'observations' not in schema['properties']:
                    raise RuntimeError('400 invalid schema')
                return super().complete(system, user, schema, model, effort, max_tokens)
        with tempfile.TemporaryDirectory() as d:
            ledger = {'spent_usd': 0.0, 'budget_usd': 10.0}
            r = run_interview('S000', SEGS, Boom(), Path(d), model='claude-opus-5-5', effort='medium', max_chars=500, ledger=ledger)
            self.assertIsNone(r['decision'])
            self.assertTrue(any('400 invalid schema' in e for e in r['grounding_errors']))
            self.assertGreater(ledger['spent_usd'], 0)  # extraction spend kept
