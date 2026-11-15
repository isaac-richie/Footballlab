import datetime as dt
import math
import random
import unittest

import nba
import nba_model as M


def season(n_days=120, seed=1, start='2025-10-21'):
    """A synthetic season: 30 teams with known offence/defence, regulation scores only."""
    rng = random.Random(seed)
    teams = [f'T{i:02d}' for i in range(30)]
    off = {t: rng.gauss(0, 4) for t in teams}
    dfn = {t: rng.gauss(0, 4) for t in teams}
    games, gid = [], 0
    day = dt.date.fromisoformat(start)
    for d in range(n_days):
        order = teams[:]
        rng.shuffle(order)
        for i in range(0, 14, 2):
            h, a = order[i], order[i + 1]
            eh = 112 + 1.25 + off[h] - dfn[a]
            ea = 112 - 1.25 + off[a] - dfn[h]
            sh, sa = round(rng.gauss(eh, 11)), round(rng.gauss(ea, 11))
            if sh == sa:
                sh += 1
            gid += 1
            q = lambda s: [s // 4, s // 4, s // 4, s - 3 * (s // 4)]
            games.append(dict(id=str(gid), season=2026, kind='regular', date=(day + dt.timedelta(days=d)).isoformat(), tipoff=None,
                              neutral=False, home=h, away=a, home_abbr=None, away_abbr=None, score=[sh, sa],
                              periods=[q(sh), q(sa)], status='final'))
    return games, off, dfn


class FitTests(unittest.TestCase):
    def test_recovers_known_ratings_and_home_edge(self):
        games, off, dfn = season()
        r = M.fit(games, '2026-03-01', settings=dict(half_life=10_000, ridge=1.0, b2b=False))
        self.assertAlmostEqual(r['home'], 2.5, delta=1.0)
        # About 56 games a team: ratings carry sampling noise, so test agreement, not equality.
        def corr(a, b):
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
            return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
        self.assertGreater(corr([r['offence'][t] for t in off], [off[t] for t in off]), .8)
        self.assertGreater(corr([r['defence'][t] for t in off], [dfn[t] for t in off]), .8)
        self.assertGreater(corr([r['offence'][t] + r['defence'][t] for t in off], [off[t] + dfn[t] for t in off]), .85)

    def test_uses_only_earlier_games(self):
        games, _, _ = season()
        a = M.fit(games, '2026-01-10')
        later = [dict(g, score=[200, 50], periods=[[50] * 4, [12, 12, 13, 13]]) if g['date'] >= '2026-01-10' else g for g in games]
        b = M.fit(later, '2026-01-10')
        self.assertEqual(a['offence'], b['offence'])

    def test_closing_line_shapes_the_target(self):
        g = dict(score=[130, 100], periods=[[30, 30, 35, 35], [25, 25, 25, 25]],
                 line=dict(close=dict(spread=-4.0, total=224.0, spread_prices=[1.91, 1.91], total_prices=[1.91, 1.91], moneyline=[None, None])))
        self.assertEqual(M.target(g, 0), (130, 100))
        h, a = M.target(g, 1.0)                       # the line alone: home by 4, about 224 in total
        self.assertAlmostEqual(h - a, 4.0, delta=.2)
        self.assertAlmostEqual(h + a, 224.0, delta=1.5)
        h, a = M.target(g, .7)                        # 70% line, 30% the 30-point blowout
        self.assertAlmostEqual(h - a, .7 * 4 + .3 * 30, delta=.2)
        self.assertEqual(M.target(dict(g, line=None), .7), (130, 100))   # no line stored: the score

    def test_last_season_still_counts_after_the_summer(self):
        games, off, dfn = season(n_days=120, start='2025-01-01')       # ends in April 2025
        early = M.fit(games, '2025-10-25', settings=dict(half_life=15, ridge=.5, gap=0, market=0, b2b=False))
        bridged = M.fit(games, '2025-10-25', settings=dict(half_life=15, ridge=.5, gap=115, market=0, b2b=False))
        self.assertGreater(bridged['effective_weight'], 50 * early['effective_weight'])

    def test_too_few_games(self):
        games, _, _ = season(n_days=3)
        with self.assertRaises(ValueError):
            M.fit(games, '2026-03-01')


class DistributionTests(unittest.TestCase):
    def test_grid_sums_to_one_and_has_no_ties(self):
        d = M.distribution(114, 109)
        self.assertAlmostEqual(sum(d['grid'].values()), 1, places=6)
        self.assertFalse(any(x == y for x, y in d['grid']))

    def test_even_game_is_even_and_overtime_rate_realistic(self):
        mk = M.markets(M.distribution(111, 111))
        self.assertAlmostEqual(mk['moneyline'][0], .5, places=3)
        self.assertGreater(mk['overtime'], .04)
        self.assertLess(mk['overtime'], .08)

    def test_markets_are_consistent(self):
        mk = M.markets(M.distribution(118, 106), -9.5, 230.5)
        self.assertAlmostEqual(sum(mk['moneyline']), 1, places=6)
        self.assertAlmostEqual(sum(mk['spread']), 1, places=6)
        self.assertAlmostEqual(sum(mk['total']), 1, places=6)
        c = mk['combos']['moneyline_total']
        self.assertAlmostEqual(c['home_over'] + c['home_under'], mk['moneyline'][0], places=6)
        s = mk['combos']['spread_total']
        self.assertAlmostEqual(s['home_over'] + s['home_under'], mk['spread'][0], places=6)
        self.assertAlmostEqual(mk['expected_margin'], 12, delta=.5)
        # Overtime adds a few points on average beyond regulation.
        self.assertGreater(mk['expected_total'], 224)
        ladder = [mk['totals'][k][0] for k in sorted(mk['totals'], key=float)]
        self.assertTrue(all(a >= b for a, b in zip(ladder, ladder[1:])))

    def test_whole_number_lines_push(self):
        mk = M.markets(M.distribution(112, 108), -4, 220)
        self.assertGreater(mk['spread'][1], 0)
        self.assertGreater(mk['total'][1], 0)

    def test_scores_correlate_with_shared_pace(self):
        mk = M.markets(M.distribution(110, 110))
        # Spread of the total exceeds that of the margin when both scores move together.
        self.assertGreater(mk['total_sd'], mk['margin_sd'])


class LineTests(unittest.TestCase):
    def test_fair_pair_removes_margin(self):
        p = M.fair_pair([1.91, 1.91])
        self.assertAlmostEqual(p[0], .5, places=6)
        self.assertAlmostEqual(sum(p), 1, places=6)
        self.assertIsNone(M.fair_pair([None, 1.9]))

    def test_implied_reproduces_line(self):
        line = dict(spread=-6.5, spread_prices=[1.91, 1.91], total=224.5, total_prices=[1.91, 1.91], moneyline=[None, None])
        mh, ma = M.implied(line, (110, 110))
        mk = M.markets(M.distribution(mh, ma, width=M.LINE_WIDTH), -6.5, 224.5)
        self.assertAlmostEqual(mk['spread'][0], .5, delta=.02)
        self.assertAlmostEqual(mk['total'][0], .5, delta=.02)

    def test_moneyline_only(self):
        mh, ma = M.implied(dict(moneyline=[1.5, 2.7]), (110, 110))
        self.assertGreater(mh, ma)
        self.assertAlmostEqual(mh + ma, 220, places=6)


class FeedTests(unittest.TestCase):
    def event(self, **kw):
        e = dict(id='1', date='2026-01-16T00:30Z', season=dict(year=2026, type=2),
                 status=dict(type=dict(name='STATUS_FINAL', completed=True, state='post')),
                 competitions=[dict(neutralSite=False, competitors=[
                     dict(homeAway='home', score='119', team=dict(displayName='Philadelphia 76ers', abbreviation='PHI', id='20'),
                          linescores=[dict(value=v) for v in (21, 26, 38, 24, 10)]),
                     dict(homeAway='away', score='125', team=dict(displayName='New York Knicks', abbreviation='NY', id='18'),
                          linescores=[dict(value=v) for v in (30, 30, 25, 24, 16)])])])
        e.update(kw)
        return e

    def test_final_with_overtime(self):
        g = nba.to_game(self.event())
        self.assertEqual(g['score'], [119, 125])
        self.assertEqual(M.regulation(g), (109, 109))
        self.assertEqual(g['date'], '2026-01-15')          # US Eastern game day
        self.assertEqual(g['status'], 'final')

    def test_all_star_and_preseason_skipped(self):
        e = self.event()
        e['competitions'][0]['competitors'][0]['team']['abbreviation'] = 'LEB'
        self.assertIsNone(nba.to_game(e))
        self.assertIsNone(nba.to_game(self.event(season=dict(year=2026, type=1))))

    def test_tied_final_rejected(self):
        e = self.event()
        e['competitions'][0]['competitors'][1]['score'] = '119'
        self.assertIsNone(nba.to_game(e)['score'])

    def test_back_to_back(self):
        games = [dict(id='1', date='2026-01-01', home='A', away='B'), dict(id='2', date='2026-01-02', home='C', away='A'),
                 dict(id='3', date='2026-01-04', home='B', away='C')]
        r = M.back_to_back(games)
        self.assertEqual(r[('2', 1)], 1)
        self.assertEqual(r[('2', 0)], 0)
        self.assertEqual(r[('3', 0)], 0)


if __name__ == '__main__':
    unittest.main()
