import tempfile
import unittest

from live_odds import movement, movement_summary, record_history
from simulate import simulate, table


class SeasonTests(unittest.TestCase):
    def test_table_tiebreaks(self):
        rows = table([('A', 'B', 2, 0), ('C', 'D', 1, 0), ('B', 'C', 1, 1)], ['A', 'B', 'C', 'D'])
        self.assertEqual(rows[0]['team'], 'C')  # 4 points
        self.assertEqual(rows[1]['team'], 'A')  # 3 points

    def test_simulation_probabilities_are_coherent(self):
        teams = ['A', 'B', 'C', 'D']
        remaining = [(h, a) for h in teams for a in teams if h != a]
        rates = {(h, a): (2.2 if h == 'A' else 1.2, .6 if h == 'A' else 1.2 if a != 'A' else 2.0) for h, a in remaining}
        r = simulate([], remaining, rates, 'en.1', runs=2000)
        by = {t['current']['team']: t for t in r['teams']}
        for t in r['teams']:
            self.assertAlmostEqual(sum(t['positions']), 1)
        self.assertAlmostEqual(sum(t['title'] for t in r['teams']), 1)
        self.assertGreater(by['A']['title'], .5)
        self.assertEqual(r['teams'][0]['current']['team'], 'A')
        self.assertEqual(simulate([], remaining, rates, 'en.1', runs=300)['teams'][0]['positions'],
                         simulate([], remaining, rates, 'en.1', runs=300)['teams'][0]['positions'])  # seeded

    def test_finished_season_is_rejected(self):
        with self.assertRaises(ValueError):
            simulate([('A', 'B', 1, 0)], [], {}, 'en.1')

    def test_odds_history_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            def snap(t, home):
                record_history('en.1', t, {('2026-10-17', 'A', 'B'): dict(h2h=dict(
                    home=dict(median=home), draw=dict(median=3.5), away=dict(median=4.0)))}, directory)
            snap('2026-10-10T10:00:00+00:00', 2.2)
            snap('2026-10-12T10:00:00+00:00', 1.9)
            path = movement('en.1', '2026-10-17|A|B', directory)
            self.assertEqual(len(path), 2)
            summary = movement_summary('en.1', directory)['2026-10-17|A|B']
            self.assertGreater(summary['change'][0], .03)
            self.assertTrue(summary['sharp'])
            self.assertAlmostEqual(sum(summary['change']), 0)


if __name__ == '__main__':
    unittest.main()
