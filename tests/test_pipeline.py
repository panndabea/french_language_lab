import unittest
from src.pipeline import parse_trs, baseline, bracket

SAMPLE=b'''<Trans><Speakers><Speaker id="spk1" name="interviewer"/><Speaker id="spk2" name="interviewee"/></Speakers><Episode><Section><Turn speaker="spk1" startTime="0">j'ai 99 ans</Turn><Turn speaker="spk2" startTime="1"><Sync time="1"/>je suis n\xc3\xa9e en 1940</Turn><Turn speaker="spk2" startTime="2">j'ai 65 ans</Turn><Turn speaker="spk1 spk2" startTime="3">j'ai 42 ans</Turn></Section></Episode></Trans>'''
class Tests(unittest.TestCase):
    def test_parsing_and_roles(self):
        turns=parse_trs(SAMPLE,'S000')
        self.assertEqual([t['role'] for t in turns],['interviewer','interviewee','interviewee','overlap'])
        self.assertEqual(turns[1]['text'],'je suis n\u00e9e en 1940')
    def test_baseline_excludes_interviewer_and_overlap(self):
        p=baseline('S000',parse_trs(SAMPLE,'S000'))
        self.assertEqual(p['age_bracket'],'60-69')
        self.assertEqual(p['gender'],'female')
        self.assertIsNone(p['interview_year'])
    def test_date_conflict_flag(self):
        ts=[{'role':'interviewee','text':'donc on est en deux mille dix', 'start':'10'}]
        self.assertTrue(baseline('S000',ts)['out_of_domain_year_flag'])
    def test_brackets(self):
        self.assertEqual(bracket(30),'30-39')
        self.assertEqual(bracket(40),'40-49')
        self.assertIsNone(bracket(None))
if __name__=='__main__':unittest.main()

from src.evaluate import analyze
class EvaluationTests(unittest.TestCase):
    def test_coverage_distinct_from_accuracy(self):
        g={'S001':{'age_bracket':'30-39','gender':'female','interview_year':'2005'},
           'S002':{'age_bracket':'40-49','gender':'male','interview_year':'1970'}}
        p={'S001':{'age_bracket':'30-39','gender':'female','interview_year':''},
           'S002':{'age_bracket':'','gender':'unknown','interview_year':'1970'}}
        r=analyze(p,g)
        self.assertEqual(r['age_bracket']['coverage'],.5)
        self.assertEqual(r['age_bracket']['accuracy_when_answered'],1)
        self.assertEqual(r['gender']['coverage'],.5)
