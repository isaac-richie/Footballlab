import datetime as dt
import tempfile
import unittest
from pathlib import Path

import nba_picks_ledger as L

NOW = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)
PICK = dict(id='g1', date='2026-11-19', tipoff='2026-11-20T00:00:00Z', home='Home', away='Away', home_abbr='H', away_abbr='A')


class PicksLedger(unittest.TestCase):
    def test_saved_before_tipoff_then_marked(self):
        with tempfile.TemporaryDirectory() as d:
            p = dict(picks=[dict(PICK, team='Home', probability=.7)], totals=[dict(PICK, side='under', line=220.5, probability=.71)])
            self.assertEqual(L.save(p, NOW, d), 1)
            self.assertEqual(L.save(p, NOW + dt.timedelta(hours=13), d), 0)      # after tip-off: never rewritten
            games = [dict(id='g1', status='final', score=[110, 105])]
            r = L.results(games, d)
            row = r['days'][0]['picks'][0]
            self.assertTrue(row['winner']['won'])
            self.assertTrue(row['total']['won'])                                  # 215 points: under 220.5 won
            self.assertEqual((r['winner'], r['total']), (dict(won=1, lost=0), dict(won=1, lost=0)))

    def test_pending_until_final(self):
        with tempfile.TemporaryDirectory() as d:
            L.save(dict(picks=[dict(PICK, team='Away', probability=.65)]), NOW, d)
            r = L.results([dict(id='g1', status='scheduled', score=None)], d)
            self.assertEqual(r['days'][0]['pending'], 1)


if __name__ == '__main__':
    unittest.main()
