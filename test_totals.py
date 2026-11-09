import datetime as dt
import random
import unittest

import market_ratings


def season(seed=1):
    """A synthetic scorelines-only league: 20 teams, two seasons of double round robins."""
    rnd, teams, rows = random.Random(seed), [f'T{i}' for i in range(20)], []
    day = dt.date(2024, 8, 1)
    for _ in range(2):
        for h in teams:
            for a in teams:
                if h != a:
                    rows.append(dict(league_id='xx.1', season='2024-25', date=day.isoformat(), home=h, away=a,
                                     goals=[rnd.choice([0, 1, 1, 2, 2, 3]), rnd.choice([0, 0, 1, 1, 2])]))
                    day += dt.timedelta(hours=8)
    return rows


class TotalsTest(unittest.TestCase):
    def test_with_totals_keeps_balance_and_takes_total(self):
        base = lambda h, a, s=None: (2.0, 1.0)
        tot = lambda h, a, s=None: (1.2, 1.2)
        lh, la = market_ratings.with_totals(base, tot)('A', 'B')
        self.assertAlmostEqual(lh + la, 2.4)
        self.assertAlmostEqual(lh / la, 2.0)

    def test_scorelines_fit_uses_shrunk_totals(self):
        old = market_ratings.table
        market_ratings.table = lambda: {}
        try:
            rows = season()
            expected, rho, meta = market_ratings.fit(rows, '2027-01-01', ('T0', 'T1'))
        finally:
            market_ratings.table = old
        self.assertEqual(meta['targets'], 'scorelines')
        self.assertEqual(meta['totals_ridge'], market_ratings.TOTALS_RIDGE)
        self.assertIsNotNone(expected.state)
        lh, la = expected('T0', 'T1')
        self.assertTrue(0.05 <= la < lh <= 6)


if __name__ == '__main__':
    unittest.main()
