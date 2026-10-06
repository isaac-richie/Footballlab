import unittest

from app import distribution, slate
from markets import asian_line, extended_markets, fit_first_half_share, score_matrix
from quality import normalize, valid_halftime


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.share = dict(home=.45, away=.43, matches=500)
        self.m = extended_markets(1.5, 1.1, -.05, self.share)

    def test_partitions_sum_to_one(self):
        for key in ('exact_total', 'winning_margin', 'result_btts', 'btts_total', 'odd_even'):
            self.assertAlmostEqual(sum(self.m[key].values()), 1, places=9, msg=key)
        cs = self.m['correct_score']
        self.assertAlmostEqual(sum(map(sum, cs['grid'])) + cs['other_home'] + cs['other_draw'] + cs['other_away'], 1)
        for side in ('home', 'away'):
            self.assertAlmostEqual(sum(self.m['team_exact_goals'][side].values()), 1)
        ht = self.m['halftime']
        self.assertAlmostEqual(sum(ht['ht_ft'].values()), 1, places=6)
        self.assertAlmostEqual(sum(ht['result_first_half']), 1, places=6)
        self.assertAlmostEqual(ht['higher_first'] + ht['higher_second'] + ht['equal_halves'], 1, places=6)

    def test_consistent_with_full_time_distribution(self):
        base = distribution(1.5, 1.1, -.05)
        r = self.m['result_btts']
        self.assertAlmostEqual(r['home_yes'] + r['home_no'], base['probabilities'][0])
        self.assertAlmostEqual(self.m['btts_total']['yes_over'] + self.m['btts_total']['yes_under'], base['btts'])
        self.assertAlmostEqual(self.m['correct_score']['grid'][1][1], next(
            s['probability'] for s in base['scorelines'] if s['score'] == '1–1'))

    def test_asian_lines(self):
        grid = score_matrix(1.3, 1.3)
        level = asian_line(grid, 0, lambda h, a: h - a)
        self.assertAlmostEqual(level['push'], sum(p for (h, a), p in grid.items() if h == a))
        self.assertAlmostEqual(level['fair_odds'], 2)  # symmetric: win and loss equally likely
        quarter = asian_line(grid, -.25, lambda h, a: h - a)
        self.assertAlmostEqual(quarter['half_loss'], level['push'])
        self.assertEqual(quarter['push'], 0)
        half = asian_line(grid, -.5, lambda h, a: h - a)
        self.assertAlmostEqual(half['fair_odds'], 1 / half['win'])
        total = next(t for t in extended_markets(1.3, 1.3)['asian_total'] if t['line'] == 2.5)
        self.assertAlmostEqual(total['over']['win'] + total['under']['win'], 1)

    def test_halftime_share_uses_only_earlier_valid_rows(self):
        rows = [dict(date='2024-01-01', goals=[2, 2], ht=[1, 0]) for _ in range(250)]
        rows.append(dict(date='2025-01-01', goals=[9, 9], ht=[9, 9]))
        share = fit_first_half_share(rows, '2025-01-01')
        self.assertAlmostEqual(share['home'], .5)
        self.assertAlmostEqual(share['away'], 0)
        self.assertEqual(share['matches'], 250)
        self.assertIsNone(fit_first_half_share(rows[:50], '2025-01-01'))

    def test_halftime_validation(self):
        self.assertEqual(valid_halftime([1, 0], [2, 1]), [1, 0])
        self.assertIsNone(valid_halftime([3, 0], [2, 1]))
        self.assertIsNone(valid_halftime([1, 0], None))
        raw = '{"matches":[{"date":"2024-08-01","team1":"A","team2":"B","score":{"ht":[1,1],"ft":[2,1]}},' \
              '{"date":"2024-08-02","team1":"B","team2":"A","score":{"ft":[0,0]}}]}'
        rows = normalize(raw, 'en.1', 'L', '2024-25')
        self.assertEqual([r['ht'] for r in rows], [[1, 1], None])

    def test_slate_forecasts_future_fixtures_only(self):
        import datetime as dt
        today = dt.date.today()
        past = [dict(date=(today - dt.timedelta(days=1 + i % 300)).isoformat(), home=h, away=a, goals=[1, 0],
                     league_id='en.1', season='x') for i in range(120) for h, a in [('A', 'B')]]
        future = [dict(date=(today + dt.timedelta(days=3)).isoformat(), home='B', away='A', goals=None,
                       league_id='en.1', season='x'),
                  dict(date=today.isoformat(), home='A', away='B', goals=None, league_id='en.1', season='x')]
        result = slate(dict(matches=past + future, fetched_at='t-test', sources=[]), 'en.1')
        self.assertEqual(len(result['fixtures']), 1)
        self.assertAlmostEqual(sum(result['fixtures'][0]['probabilities']), 1)


if __name__ == '__main__':
    unittest.main()
