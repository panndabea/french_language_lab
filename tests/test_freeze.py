import unittest
from src.freeze import build_frozen_rows
from tests.test_merge_llm import LLM, RULES, SEGS


class FreezeTests(unittest.TestCase):
    def test_status_column_and_failed_falls_back(self):
        llm = [dict(LLM[0], status='completed'),
               dict(LLM[0], interview_id='S002', status='failed', grounding_errors=['c0: quote not verbatim'])]
        rows, _, errs = build_frozen_rows(llm, RULES, SEGS)
        by = {r['interview_id']: r for r in rows}
        self.assertEqual((by['S001']['source'], by['S001']['llm_status']), ('llm', 'completed'))
        self.assertEqual((by['S002']['source'], by['S002']['llm_status']), ('rules_fallback', 'failed'))
        self.assertEqual(errs, [])

    def test_unprocessed_marked(self):
        rows, _, _ = build_frozen_rows([dict(LLM[0], status='completed')], RULES, SEGS)
        self.assertEqual({r['interview_id']: r['llm_status'] for r in rows}['S002'], 'unprocessed')
