import unittest
from src.frnum import find_ages, find_birth_years
from src.rules_v2 import predict


def seg(text, role='interviewee', start='1', spk=None, overlap=False):
    return {'interview_id': 'S000', 'turn_index': 0, 'speaker_id': spk or {'interviewee': 'spk2', 'interviewer': 'spk1'}.get(role, 'spk3'),
            'role': role, 'overlap': overlap, 'start': start, 'text': text}


class AgeGuardTests(unittest.TestCase):
    def test_depuis_que_is_narrative(self):
        self.assertEqual(find_ages("depuis que j'ai quatorze ans"), [])

    def test_birth_years(self):
        self.assertEqual([b['year'] for b in find_birth_years("je suis née en mille neuf cent trente-deux")], [1932])
        self.assertEqual([b['year'] for b in find_birth_years("moi je suis de mille neuf cent quarante")], [1940])
        self.assertEqual(find_birth_years("il est né en mille neuf cent trente"), [])


class YearTests(unittest.TestCase):
    def test_present_anchor_2010_is_out_of_domain(self):
        p = predict('S000', [seg("donc euh on est en deux mille dix ça fait dix ans")])
        self.assertTrue(p['out_of_domain_year_flag'])
        self.assertEqual(p['recording_year_lower_bound'], 2010)
        self.assertIsNone(p['interview_year'])          # strict label not forced
        self.assertEqual(p['cohort_hypothesis'], '2005')  # nearest cohort, flagged

    def test_euro_plus_recent_years_gives_recent_cohort(self):
        p = predict('S000', [seg("ça coûte dix euros"), seg("depuis deux mille trois"), seg("en deux mille un")])
        self.assertEqual(p['cohort_hypothesis'], '2005')
        self.assertFalse(p['out_of_domain_year_flag'])
        self.assertEqual(p['interview_year'], '2005')

    def test_no_evidence_is_unknown(self):
        p = predict('S000', [seg("bonjour"), seg("oui")])
        self.assertIsNone(p['interview_year'])
        self.assertEqual(p['cohort_hypothesis'], 'unknown')

    def test_old_present_anchor(self):
        p = predict('S000', [seg("nous sommes en mille neuf cent soixante-neuf")])
        self.assertEqual(p['cohort_hypothesis'], '1970')
        self.assertEqual(p['interview_year'], '1970')

    def test_conflicting_era_evidence_is_unknown(self):
        p = predict('S000', [seg("nous sommes en mille neuf cent soixante-neuf"), seg("dix euros")])
        self.assertEqual(p['cohort_hypothesis'], 'unknown')
        self.assertEqual(p['status'], 'review_needed')


class GenderTests(unittest.TestCase):
    def test_self_agreement(self):
        p = predict('S000', [seg("je suis contente"), seg("je suis née ici")])
        self.assertEqual(p['gender'], 'female')

    def test_interviewer_agreement_not_counted_as_self(self):
        p = predict('S000', [seg("je suis content", role='interviewer')])
        self.assertEqual(p['gender'], 'unknown')

    def test_conflict_is_unknown(self):
        p = predict('S000', [seg("je suis contente"), seg("je suis heureux")])
        self.assertEqual(p['gender'], 'unknown')

    def test_relational_cue_alone_insufficient(self):
        p = predict('S000', [seg("mon mari travaillait")])
        self.assertEqual(p['gender'], 'unknown')


class AgeTests(unittest.TestCase):
    def test_direct_age(self):
        self.assertEqual(predict('S000', [seg("j'ai soixante-cinq ans")])['age_bracket'], '60-69')

    def test_conflicting_ages_unknown(self):
        p = predict('S000', [seg("j'ai vingt ans"), seg("j'ai vingt-neuf ans")])
        self.assertIsNone(p['age_bracket'])

    def test_birth_year_with_anchor(self):
        p = predict('S000', [seg("je suis né en mille neuf cent quarante-cinq"), seg("on est en deux mille dix")])
        self.assertEqual(p['age_bracket'], '60-69')

    def test_birth_year_ambiguous_range_left_unknown(self):
        # recent cohort without anchor: recording year range too wide for one bracket
        p = predict('S000', [seg("je suis né en mille neuf cent quarante-sept"), seg("dix euros"), seg("depuis deux mille trois")])
        self.assertIsNone(p['age_bracket'])
        self.assertIsNotNone(p['age_range_estimate'])

    def test_overlap_evidence_kept_and_flagged(self):
        p = predict('S000', [seg("j'ai soixante-cinq ans", overlap=True)])
        self.assertEqual(p['age_bracket'], '60-69')
        self.assertTrue(p['evidence']['age'][0]['overlap'])


class EvidenceTests(unittest.TestCase):
    def test_quotes_verbatim_with_speaker_and_time(self):
        s = seg("donc euh on est en deux mille dix", start='10.153')
        p = predict('S000', [s])
        e = p['evidence']['year'][0]
        self.assertEqual(e['quote'], s['text'])
        self.assertEqual((e['speaker_id'], e['start']), ('spk2', '10.153'))


if __name__ == '__main__':
    unittest.main()


class RevisedCueTests(unittest.TestCase):
    def test_evenements_de_mai_without_year_is_old(self):
        p = predict('S000', [seg("et les événements de mai qu'est-ce que vous en pensez", role='interviewer')])
        self.assertEqual(p['cohort_hypothesis'], '1970')

    def test_mai_68_retrospective_not_old_cue(self):
        p = predict('S000', [seg("en mai soixante-huit j'étais étudiant")])
        self.assertEqual(p['era_scores']['old'], 0)

    def test_year_profile_only_pre_1972(self):
        p = predict('S000', [seg("en mille neuf cent trente"), seg("en mille neuf cent quarante-cinq"), seg("en mille neuf cent soixante")])
        self.assertEqual(p['era_scores']['old'], 1)

    def test_address_downweighted_when_others_present(self):
        segs = [seg("merci madame", role='interviewer'), seg("merci madame", role='interviewer'), seg("oui", role='other1')]
        self.assertEqual(predict('S000', segs)['gender'], 'unknown')
        self.assertEqual(predict('S000', segs[:2])['gender'], 'female')

    def test_un_monsieur_is_reference_not_address(self):
        p = predict('S000', [seg("il y avait un monsieur qui venait", role='interviewer'), seg("le monsieur", role='interviewer')])
        self.assertEqual(p['gender_scores']['male'], 0)


class ImplausibleAgeTests(unittest.TestCase):
    def test_age_under_12_not_bracketed(self):
        p = predict('S000', [seg("mais j'ai deux ans pfou")])
        self.assertIsNone(p['age_bracket'])
        self.assertEqual(p['status'], 'review_needed')


class InterviewerBirthQuestionTests(unittest.TestCase):
    def test_confirmed_question_gives_birth_year(self):
        p = predict('S000', [seg("vous êtes né en quarante-sept ?", role='interviewer'), seg("oui c'est ça"),
                             seg("on est en deux mille dix")])
        self.assertEqual({e['value'] for e in p['evidence']['birth']}, {1947})
        self.assertEqual({e['role'] for e in p['evidence']['birth']}, {'interviewer', 'interviewee'})  # Q + answer quoted
        self.assertEqual(p['age_bracket'], '60-69')   # 2010-1947 -> 62-63

    def test_denied_question_ignored(self):
        p = predict('S000', [seg("vous êtes né en quarante-sept ?", role='interviewer'), seg("non quarante-huit")])
        self.assertEqual(p['evidence']['birth'], [])

    def test_unanswered_question_ignored(self):
        p = predict('S000', [seg("vous êtes née en mille neuf cent trente ?", role='interviewer'),
                             seg("ah bon", role='interviewer')])
        self.assertEqual(p['evidence']['birth'], [])


class ImpliedRecordingYearTests(unittest.TestCase):
    def test_s111_pattern_1878_resolved_by_age(self):
        p = predict('S000', [seg("eh ben je suis de soixante dix-huit je vais avoir quatre-vingt-onze ans le mois prochain")])
        self.assertEqual(p['implied_recording_years'], [1968, 1969])
        self.assertEqual(p['cohort_hypothesis'], '1970')
        self.assertEqual(p['age_bracket'], '90+')

    def test_s083_pattern_implies_2010_out_of_domain(self):
        p = predict('S000', [seg("je suis de cinquante-quatre"), seg("j'ai cinquante-cinq ans")])
        self.assertEqual(p['implied_recording_years'], [2009, 2010])
        self.assertEqual(p['cohort_hypothesis'], '2005')
        self.assertTrue(p['out_of_domain_year_flag'])
        self.assertEqual(p['age_bracket'], '50-59')

    def test_s120_pattern_1912_plus_57(self):
        p = predict('S000', [seg("par conséquent je suis de douze j'avais trois ans"), seg("j'ai cinquante-sept ans")])
        self.assertEqual(p['cohort_hypothesis'], '1970')
        self.assertFalse(p['out_of_domain_year_flag'])

    def test_two_digit_without_age_uses_cohort_feasibility(self):
        # cohort 1970 from événements de mai; 75 can only be 1875 (1975 is after recording)
        p = predict('S000', [seg("les événements de mai", role='interviewer'), seg("je suis de soixante-quinze")])
        self.assertEqual(p['age_bracket'], '90+')


class PilotRuleGapTests(unittest.TestCase):
    def test_singular_an(self):
        self.assertEqual([a['age'] for a in __import__('src.frnum', fromlist=['x']).find_ages("j'ai soixante et un an")], [61])

    def test_age_split_across_segments(self):
        # S001 2261-2262: "vous vous doutez bien que je vais avoir" | "soixante et un an"
        p = predict('S000', [seg("vous vous doutez bien que je vais avoir", start='4280.584'),
                             seg("soixante et un an", start='4281.786')])
        self.assertEqual(p['age_bracket'], '60-69')
        e = p['evidence']['age'][0]
        self.assertEqual((e['quote'], e['start']), ("soixante et un an", '4281.786'))
        self.assertEqual(e['context_quote'], "vous vous doutez bien que je vais avoir")

    def test_split_requires_same_speaker_consecutive(self):
        p = predict('S000', [seg("je vais avoir"), seg("soixante et un an", role='interviewer')])
        self.assertIsNone(p['age_bracket'])
