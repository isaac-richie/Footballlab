import unittest

from markets import score_matrix
from model import calibrate, fit_ratings, newcomers
from odds_data import fair


def season_rows(season, year, teams, strong=(), weak=()):
    rows = []
    day = 1
    for h in teams:
        for a in teams:
            if h != a:
                hg = 3 if h in strong else 0 if h in weak else 1
                ag = 2 if a in strong else 0 if a in weak else 1
                rows.append(dict(date=f'{year}-{(day // 28) % 12 + 1:02d}-{day % 28 + 1:02d}', home=h, away=a,
                                 goals=[hg, ag], league_id='en.1', season=season))
                day += 1
    return rows


class RatingsTest(unittest.TestCase):
    def test_fitted_goals_match_weighted_averages(self):
        rows = season_rows('2024-25', 2024, list('ABCDEFGHIJK'), strong='A', weak='K')
        expected, meta = fit_ratings(rows, '2025-06-01', half_life_days=10 ** 6, ridge=.01)
        home = sum(expected(m['home'], m['away'])[0] for m in rows) / len(rows)
        self.assertAlmostEqual(home, sum(m['goals'][0] for m in rows) / len(rows), places=4)
        self.assertGreater(expected('A', 'K')[0], expected('K', 'A')[0])
        self.assertIn('converged', meta['solver'])

    def test_newcomer_offset_is_learned_and_applied(self):
        old = list('ABCDEFGHIJ')
        rows = season_rows('2023-24', 2023, old)
        rows += season_rows('2024-25', 2024, old[:-2] + ['X', 'Y'], weak='XY')
        flags = newcomers(rows + [dict(rows[0], season='2025-26', home='Z')], 'en.1')
        self.assertEqual(flags[('X', '2024-25')], 'up')
        self.assertEqual(flags[('Z', '2025-26')], 'up')
        expected, meta = fit_ratings(rows, '2025-06-01', teams=['Z'], newcomers=flags)
        self.assertLess(meta['newcomer_offsets']['up_attack'], -.1)
        self.assertLess(expected('Z', 'A', '2025-26')[0], expected('Z', 'A')[0])

    def test_margin_methods(self):
        odds = [1.30, 5.5, 10.0]
        for method in ('proportional', 'shin', 'power', 'odds_ratio', 'additive'):
            p = fair(odds, method)
            self.assertAlmostEqual(sum(p), 1)
        # Shin removes more margin from the longshot than proportional removal does.
        self.assertLess(fair(odds, 'shin')[2], fair(odds, 'proportional')[2])
        self.assertEqual([round(x, 6) for x in fair([2, 4, 4], 'shin')], [.5, .25, .25])

    def test_calibrated_grid_matches_calibrated_result(self):
        cal = dict(temperature=.82, draw_shift=.18)
        raw, grid = score_matrix(1.6, 1.1, -.05), score_matrix(1.6, 1.1, -.05, cal)
        side = lambda g, test: sum(p for (h, a), p in g.items() if test(h, a))
        target = calibrate([side(raw, lambda h, a: h > a), side(raw, lambda h, a: h == a), side(raw, lambda h, a: h < a)], **cal)
        self.assertAlmostEqual(side(grid, lambda h, a: h > a), target[0])
        self.assertAlmostEqual(side(grid, lambda h, a: h == a), target[1])
        self.assertAlmostEqual(sum(grid.values()), 1)
        # Within a result the shape is unchanged: 2-1 versus 1-0 keeps its ratio.
        self.assertAlmostEqual(grid[(2, 1)] / grid[(1, 0)], raw[(2, 1)] / raw[(1, 0)])


if __name__ == '__main__':
    unittest.main()
