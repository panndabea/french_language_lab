import unittest
from src.segments import parse_segments
from src.frnum import parse_french_number, find_years, find_ages

OVERLAP = '''<Trans><Speakers><Speaker id="spk1" name="interviewer"/><Speaker id="spk2" name="interviewee"/><Speaker id="spk3" name="other1"/></Speakers><Episode><Section>
<Turn speaker="spk2" startTime="0" endTime="5"><Sync time="0"/>bonjour<Sync time="2.5"/>j'ai soixante-cinq ans</Turn>
<Turn speaker="spk1 spk2" startTime="5" endTime="7"><Sync time="5"/><Who nb="1"/>où ?<Who nb="2"/>on était à Saint Marceau</Turn>
<Turn speaker="spk2 spk3" startTime="7" endTime="9"><Sync time="7"/><Who nb="1"/>un<Who nb="2"/><Event desc="rire" type="noise"/>hm</Turn>
</Section></Episode></Trans>'''.encode()


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.segs = parse_segments(OVERLAP, 'S000')

    def test_sync_splits_single_speaker_turn_with_timestamps(self):
        first = [s for s in self.segs if s['turn_index'] == 0]
        self.assertEqual([(s['start'], s['text']) for s in first],
                         [('0', 'bonjour'), ('2.5', "j'ai soixante-cinq ans")])
        self.assertTrue(all(s['role'] == 'interviewee' and not s['overlap'] for s in first))

    def test_overlap_split_by_who_each_to_own_speaker(self):
        t1 = [s for s in self.segs if s['turn_index'] == 1]
        self.assertEqual([(s['speaker_id'], s['role'], s['text']) for s in t1],
                         [('spk1', 'interviewer', 'où ?'), ('spk2', 'interviewee', 'on était à Saint Marceau')])
        self.assertTrue(all(s['overlap'] for s in t1))

    def test_overlap_with_other_speaker(self):
        t2 = [s for s in self.segs if s['turn_index'] == 2]
        self.assertEqual([(s['role'], s['text']) for s in t2], [('interviewee', 'un'), ('other1', 'hm')])

    def test_malformed_who_falls_back_to_unattributed(self):
        bad = b'<Trans><Speakers><Speaker id="spk1" name="interviewer"/><Speaker id="spk2" name="interviewee"/></Speakers><Episode><Section><Turn speaker="spk1 spk2" startTime="0">mixed text<Who nb="7"/>more</Turn></Section></Episode></Trans>'
        segs = parse_segments(bad, 'S000')
        self.assertTrue(all(s['role'] == 'overlap' for s in segs))


class FrenchNumberTests(unittest.TestCase):
    def test_numbers(self):
        cases = {'deux mille dix': 2010, 'mille neuf cent soixante-dix': 1970, 'mil neuf cent soixante dix': 1970,
                 'dix-neuf cent soixante-dix': 1970, 'quatre-vingt-dix-neuf': 99, 'soixante et onze': 71,
                 'deux mille cinq': 2005, 'quatre-vingts': 80, 'trente-deux': 32, 'deux mille': 2000}
        for s, v in cases.items():
            self.assertEqual(parse_french_number(s), v, s)
        self.assertIsNone(parse_french_number('bonjour'))

    def test_find_years_words_and_digits(self):
        ys = [y['year'] for y in find_years("donc euh on est en deux mille dix ça fait dix ans et en 1968 aussi")]
        self.assertEqual(ys, [2010, 1968])

    def test_find_years_rejects_non_years(self):
        self.assertEqual(find_years('il y avait trois cents personnes et deux mille euros'), [])

    def test_find_years_present_anchor(self):
        y = find_years('on est en deux mille dix')[0]
        self.assertTrue(y['present_anchor'])
        self.assertFalse(find_years('en mille neuf cent soixante-huit')[0]['present_anchor'])

    def test_find_ages(self):
        self.assertEqual([a['age'] for a in find_ages("moi j'ai soixante-cinq ans maintenant")], [65])
        self.assertEqual([a['age'] for a in find_ages("j'ai 42 ans")], [42])
        # 'il a' is third person, must not count
        self.assertEqual(find_ages("il a quatre-vingts ans"), [])
        # past age "quand j'avais vingt ans" is not current age
        self.assertEqual(find_ages("quand j'avais vingt ans"), [])



class TwoDigitBirthTests(unittest.TestCase):
    def test_two_digit_birth_year(self):
        from src.frnum import find_birth_years
        self.assertEqual([b['year'] for b in find_birth_years("non je suis né en quarante et un")], [1941])
        self.assertEqual([b['year'] for b in find_birth_years("j'y suis née en mille neuf cent vingt neuf")], [1929])
        self.assertEqual([b['year'] for b in find_birth_years("je suis né en 41")], [1941])
        # two-digit years keep both century candidates
        self.assertEqual(find_birth_years("je suis de soixante dix-huit")[0]['candidates'], [1878, 1978])
        self.assertEqual(find_birth_years("je suis de douze")[0]['candidates'], [1912])  # 1812 implausible

    def test_place_not_year(self):
        from src.frnum import find_birth_years
        self.assertEqual(find_birth_years("je suis né en Lorraine"), [])
        self.assertEqual(find_birth_years("je suis née au cent deux au coin de la rue"), [])


    def test_day_of_month_not_year(self):
        from src.frnum import find_birth_years
        self.assertEqual(find_birth_years("moi je suis né un vingt mars"), [])
        self.assertEqual(find_birth_years("je suis née le douze avril"), [])

    def test_future_age(self):
        a = find_ages("je vais avoir quatre-vingt-onze ans le mois prochain")
        self.assertEqual([x['age'] for x in a], [90])


if __name__ == '__main__':
    unittest.main()
