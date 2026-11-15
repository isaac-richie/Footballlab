import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import nba_ledger as L


def row(gid='1', tip='2026-11-20T00:00Z', ml=.7, cover=.55, over=.4, status='scheduled', source='line'):
    return dict(id=gid, date=tip[:10], tipoff=tip, home='H', away='A', kind='regular', source=source, book='ESPN BET',
                moneyline=[ml, 1 - ml], spread_line=-4.5, cover=cover, total_line=220.5, over=over,
                expected_points=[112, 108], status=status,
                model=dict(moneyline=[.6, .4], cover=.5, over=.5, expected_points=[111, 109]))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.before = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)

    def test_first_is_frozen_last_follows_until_tipoff(self):
        L.register([row(ml=.7)], self.before, 'v1', self.dir)
        L.register([row(ml=.8)], self.before + dt.timedelta(hours=6), 'v1', self.dir)
        L.register([row(ml=.9)], self.before + dt.timedelta(hours=13), 'v1', self.dir)   # after tip-off: ignored
        first = json.loads((self.dir / 'first' / '1.json').read_text())
        last = json.loads((self.dir / 'last' / '1.json').read_text())
        self.assertEqual(first['moneyline'], .7)
        self.assertEqual(last['moneyline'], .8)

    def test_started_or_unknown_tipoff_never_written(self):
        new, _ = L.register([row(status='live'), row(gid='2', tip=None) if False else dict(row(gid='2'), tipoff=None)], self.before, 'v1', self.dir)
        self.assertEqual(new, 0)

    def test_grades_with_pushes_left_out(self):
        L.register([row(), row(gid='2'), row(gid='3')], self.before, 'v1', self.dir)
        games = [dict(id='1', status='final', score=[120, 100]),       # home wins, covers, under
                 dict(id='2', status='final', score=[110, 115]),       # away wins, no cover, over (225 > 220.5)
                 dict(id='3', status='postponed', score=None)]
        g = L.grade(games, self.dir)
        self.assertEqual((g['graded'], g['pending'], g['void']), (2, 0, 1))
        ml = g['shown']['moneyline']
        self.assertEqual(ml['picks'], 2)
        self.assertAlmostEqual(ml['won'], .5)
        self.assertAlmostEqual(ml['predicted'], .7)
        self.assertIn('model_only', g)

    def test_pending_until_final(self):
        L.register([row()], self.before, 'v1', self.dir)
        g = L.grade([dict(id='1', status='scheduled', score=None)], self.dir)
        self.assertEqual((g['graded'], g['pending']), (0, 1))


if __name__ == '__main__':
    unittest.main()
