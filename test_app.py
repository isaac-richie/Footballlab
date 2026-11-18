import unittest
import app
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


class LastFiveTests(unittest.TestCase):
    def test_last_five_is_oldest_first_and_league_only(self):
        m = lambda d, h, a, g, lg='en.1': dict(date=d, home=h, away=a, goals=g, league_id=lg)
        data = dict(matches=[m('2026-10-01', 'A', 'B', [2, 0]), m('2026-10-08', 'B', 'A', [1, 1]),
                             m('2026-10-15', 'A', 'C', [0, 3]), m('2026-10-20', 'A', 'B', [1, 0], 'de.1'),
                             m('2026-10-22', 'C', 'A', None), m('2026-11-30', 'A', 'B', [5, 0])])
        f = app.last_five(data, 'en.1', '2026-11-01')
        self.assertEqual(f['A'], ['W', 'D', 'L'])      # other leagues, unplayed and future games left out
        self.assertEqual(f['B'], ['L', 'D'])
        self.assertEqual(f['C'], ['W'])
        many = dict(matches=[m(f'2026-09-{d:02d}', 'A', 'B', [1, 0]) for d in range(1, 9)])
        self.assertEqual(len(app.last_five(many, 'en.1', '2026-10-01')['A']), 5)


class VipTicketTests(unittest.TestCase):
    def test_ticket_keeps_saved_picks_and_tracks_their_state(self):
        import datetime as dt
        from unittest.mock import patch
        import record
        today = dt.date.today().isoformat()
        leg = lambda home, sel, status, p, goals=None: dict(league_id='en.1', date=today, home=home, away=home + ' B', market='ou15',
                                                            selection=sel, probability=p, status=status, **({'goals': goals} if goals else {}))
        day = dict(date=today, frozen_at=today + 'T07:00:00+00:00', picks=[
            leg('A', 'Over 1.5', 'won', .8, [2, 1]), leg('C', 'Over 1.5', 'pending', .82),
            leg('D', 'Over 1.5', 'pending', .85), leg('E', 'Over 1.5', 'pending', .79)])
        live = {f'{today}|C|C B': dict(status='live', score=[1, 0], clock="55'"),
                f'{today}|D|D B': dict(status='final', score=[0, 0], clock='FT')}
        with patch.object(record, 'vip_ledger', return_value=dict(days=[day])):
            t = app.vip_ticket(dict(matches=[]), 17, live_scores=live)
        by = {l['home']: l for l in t['legs']}
        self.assertTrue(t['saved'])
        self.assertEqual(by['A']['status'], 'won')                     # graded pick stays, with its score
        self.assertEqual((by['C']['status'], by['C']['clock']), ('live', "55'"))
        self.assertEqual(by['D']['status'], 'lost'); self.assertTrue(by['D']['provisional'])   # 0-0 misses Over 1.5
        self.assertEqual(by['E']['status'], 'scheduled')
        self.assertEqual(t['summary'], dict(picks=4, won=1, lost=1, live=1, scheduled=1, void=0))
        self.assertAlmostEqual(t['combined_probability'], .8 * .82 * .85 * .79)
