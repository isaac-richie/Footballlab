import unittest
from app import distribution, history, market_comparison, predict
from model import fit_rates


class Tests(unittest.TestCase):
    def test_symmetric_distribution(self):
        result = distribution(1.4, 1.4)
        self.assertAlmostEqual(sum(result['probabilities']), 1)
        self.assertAlmostEqual(result['probabilities'][0], result['probabilities'][2])
        self.assertAlmostEqual(result['btts'], (1 - __import__('math').exp(-1.4)) ** 2)
        self.assertAlmostEqual(result['clean_sheets']['home'], result['clean_sheets']['away'])
        self.assertAlmostEqual(result['home_handicap_covers']['-0.5'], result['probabilities'][0])
        self.assertAlmostEqual(sum(result['first_goal'].values()), 1)
        self.assertAlmostEqual(result['first_goal']['no_goal'], 1 - result['total_goal_overs']['0.5'])
        self.assertAlmostEqual(result['first_goal']['home'], result['first_goal']['away'])
        self.assertAlmostEqual(result['double_chance']['home_or_draw'], 1 - result['probabilities'][2])
        self.assertAlmostEqual(result['draw_no_bet']['home_win_if_settled'], .5)
        self.assertAlmostEqual(result['draw_no_bet']['draw_push'], result['probabilities'][1])

    def test_dixon_coles_correction_is_normalized_and_changes_low_scores(self):
        base, corrected = distribution(1.2, 1.0), distribution(1.2, 1.0, -.08)
        self.assertAlmostEqual(sum(corrected['probabilities']), 1)
        self.assertNotEqual(base['scorelines'], corrected['scorelines'])
        with self.assertRaises(ValueError):
            distribution(6, 6, .2)

    def test_no_same_day_or_future_leakage(self):
        rows = [{'date':d, 'goals':[1, 0]} for d in ['2025-01-01','2025-01-02','2025-01-03']]
        for row in rows: row['league_id'] = 'en.1'
        self.assertEqual(history({'matches':rows}, '2025-01-02', 'en.1'), rows[:1])

    def test_odds(self):
        result = market_comparison([.5, .25, .25], [2, 4, 4])
        self.assertEqual(result['overround'], 0)
        self.assertEqual(result['gap'], [0, 0, 0])
        for odds in ([0, 2, 3], [float('nan'), 2, 3], [2, 3]):
            with self.assertRaises(ValueError):
                market_comparison([.5, .25, .25], odds)

    def test_predict_ignores_future_score_changes(self):
        rows = [dict(date='2024-01-01', home='A', away='B', goals=[2,1], league_id='en.1') for _ in range(100)]
        rows.append(dict(date='2025-03-01', home='A', away='B', goals=[0,9], league_id='en.1'))
        data = dict(matches=rows)
        for row in rows:
            row['season'] = '2024-25'
        request = dict(home='A', away='B', date='2025-02-01', league_id='en.1')
        before = predict(data, request)['probabilities']
        rows[-1]['goals'] = [9,0]
        self.assertEqual(before, predict(data, request)['probabilities'])

    def test_fitted_rates_are_finite_and_use_only_history(self):
        rows = []
        for day in range(100):
            rows.append(dict(date=f'2024-01-{(day % 28)+1:02d}', home='A', away='B', goals=[2, 1]))
        home, away, _, meta = fit_rates(rows, 'A', 'B', '2025-02-01')
        self.assertTrue(.05 <= home <= 6)
        self.assertTrue(.05 <= away <= 6)
        self.assertIn('converged', meta['solver'])


if __name__ == '__main__':
    unittest.main()
