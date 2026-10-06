import unittest
from analysis import briefing
from app import history


class BriefingTests(unittest.TestCase):
    def test_form_orientation_and_date_boundary(self):
        rows = [dict(home='A', away='B', goals=[2, 0], date='2025-01-01', league_id='en.1'),
                dict(home='B', away='A', goals=[1, 1], date='2025-01-02', league_id='en.1'),
                dict(home='A', away='B', goals=[9, 0], date='2025-01-03', league_id='en.1')]
        b = briefing(history({'matches': rows}, '2025-01-03', 'en.1'), 'A', 'B',
                     {'probabilities': [.5, .3, .2]})
        self.assertEqual(b['team_form'][0]['form'], ['D', 'W'])
        self.assertEqual(b['team_form'][1]['goals_against'], 3)
        self.assertEqual(b['team_form'][0]['points_per_match'], 2)
        self.assertEqual(b['alternative_probability'], .5)
        self.assertAlmostEqual(b['lead_margin'], .2)

    def test_missing_history_and_equal_probabilities(self):
        b = briefing([], 'A', 'B', {'probabilities': [1/3]*3})
        self.assertIsNone(b['team_form'][0]['points_per_match'])
        self.assertAlmostEqual(b['normalized_entropy'], 1)

    def test_history_window_is_bounded(self):
        rows = [dict(home='A', away='B', goals=[1, 0], date=f'2025-01-{i:02d}') for i in range(1, 21)]
        b = briefing(rows, 'A', 'B', {'probabilities': [.6, .2, .2]})
        self.assertEqual(b['team_form'][0]['matches'], 10)
        self.assertEqual(b['team_form'][0]['latest_date'], '2025-01-20')
