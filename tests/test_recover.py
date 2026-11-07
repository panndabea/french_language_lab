import tempfile
import unittest
from pathlib import Path
from src.llm_infer import run_interview
from src.recover import NoNetworkClient, classify
from tests.test_llm_infer import FakeClient, SEGS


class RecoverTests(unittest.TestCase):
    def test_replay_from_cache_identical_and_no_calls(self):
        with tempfile.TemporaryDirectory() as d:
            kw = dict(model='claude-opus-5-5', effort='medium', max_chars=500)
            live = run_interview('S000', SEGS, FakeClient(), Path(d), ledger={'spent_usd': 0, 'budget_usd': 9}, **kw)
            nn = NoNetworkClient()
            rep = run_interview('S000', SEGS, nn, Path(d), ledger={'spent_usd': 0, 'budget_usd': 9}, **kw)
            self.assertEqual(nn.attempts, 0)
            self.assertEqual(rep['decision'], live['decision'])
            self.assertEqual(classify(rep), 'completed')

    def test_uncached_is_unprocessed_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as d:
            nn = NoNetworkClient()
            rep = run_interview('S000', SEGS, nn, Path(d), model='claude-opus-5-5', effort='medium', max_chars=500,
                                ledger={'spent_usd': 0, 'budget_usd': 9})
            self.assertGreater(nn.attempts, 0)   # attempted, refused locally
            self.assertEqual(classify(rep), 'unprocessed')

    def test_classify(self):
        base = {'decision': None, 'grounding_errors': [], 'provenance': {'chunks_total': 2, 'chunks_covered': 0}}
        self.assertEqual(classify(dict(base, provenance={'chunks_total': 2, 'chunks_covered': 1})), 'incomplete')
        self.assertEqual(classify(dict(base, decision={'x': 1}, grounding_errors=['c1: quote not verbatim'],
                                       provenance={'chunks_total': 2, 'chunks_covered': 1})), 'failed')


class PartialEvidenceTests(unittest.TestCase):
    def test_decision_from_partial_chunks_is_failed(self):
        # S074: chunk c0 timed out live (not cached); decision made from 2/3 chunks
        r = {'decision': {'x': 1}, 'grounding_errors': ['S074-c0: api_error: NoNetworkRefused: offline replay'],
             'provenance': {'chunks_total': 3, 'chunks_covered': 2}}
        self.assertEqual(classify(r), 'failed')
