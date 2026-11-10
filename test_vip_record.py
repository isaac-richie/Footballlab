import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import record

TODAY = dt.date(2026, 11, 8)


def match(date, home, away, goals=None, league='en.1'):
    return dict(league_id=league, date=date, home=home, away=away, goals=goals)


def slip(*legs):
    return lambda data, n=None: dict(code='FL-VIP-TEST', legs=[dict(league_id='en.1', date=d, home=h, away=a, market=m,
                                                            selection=s, probability=p) for d, h, a, m, s, p in legs])


no_slate = lambda data, league_id: dict(fixtures=[])


class VipRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name) / 'record-live.json'
        patcher = mock.patch.object(record, 'LIVE', self.live)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_day(self, data, vip_fn, today=TODAY):
        return record.freeze_and_grade(data, ['en.1'], no_slate, vip_fn, 'test', today=today)

    def test_slip_frozen_once_and_never_overwritten(self):
        data = dict(matches=[match('2026-11-09', 'A', 'B')])
        self.run_day(data, slip(('2026-11-09', 'A', 'B', '1x2', 'A win', .75)))
        self.run_day(data, slip(('2026-11-09', 'A', 'B', '1x2', 'Draw', .80)))
        saved = json.loads(self.live.read_text())
        self.assertEqual([l['selection'] for l in saved['vip']['2026-11-08']], ['A win'])
        self.assertEqual(saved['vip_meta']['2026-11-08']['code'], 'FL-VIP-TEST')

    def test_grading_and_ledger_totals(self):
        legs = slip(('2026-11-09', 'A', 'B', '1x2', 'A win', .75), ('2026-11-09', 'C', 'D', 'ou25', 'Under 2.5', .70),
                    ('2026-11-10', 'E', 'F', 'btts', 'Both teams score', .72))
        self.run_day(dict(matches=[]), legs)
        played = dict(matches=[match('2026-11-09', 'A', 'B', [2, 0]), match('2026-11-09', 'C', 'D', [2, 2])])
        self.run_day(played, slip(), today=TODAY + dt.timedelta(days=2))
        ledger = record.vip_ledger()
        s = ledger['summary']
        self.assertEqual((s['settled'], s['won'], s['lost'], s['pending']), (2, 1, 1, 1))
        self.assertEqual(s['hit_rate'], .5)
        self.assertEqual(s['average_confidence'], .725)
        self.assertEqual([p['status'] for p in ledger['days'][0]['picks']], ['won', 'lost', 'pending'])
        self.assertFalse(ledger['days'][0]['settled'])

    def test_late_feed_is_pending_but_postponement_is_void(self):
        legs = slip(('2026-11-09', 'A', 'B', '1x2', 'A win', .75))
        self.run_day(dict(matches=[]), legs)
        later = TODAY + dt.timedelta(days=12)
        # No later results in the league: the feed is late, so the pick waits.
        self.run_day(dict(matches=[match('2026-11-01', 'X', 'Y', [1, 0])]), slip(), today=later)
        self.assertEqual(record.vip_ledger()['summary']['pending'], 1)
        # Later games have results but this one never got one: postponed, so void.
        self.run_day(dict(matches=[match('2026-11-15', 'X', 'Y', [1, 0])]), slip(), today=later)
        s = record.vip_ledger()['summary']
        self.assertEqual((s['void'], s['settled'], s['hit_rate']), (1, 0, None))
        # A result that turns up afterwards still grades it.
        self.run_day(dict(matches=[match('2026-11-09', 'A', 'B', [0, 1]), match('2026-11-15', 'X', 'Y', [1, 0])]), slip(), today=later)
        self.assertEqual(record.vip_ledger()['days'][0]['picks'][0]['status'], 'lost')

    def test_streak_and_perfect_slip(self):
        legs = slip(('2026-11-09', 'A', 'B', 'dc', 'A or draw', .8), ('2026-11-09', 'C', 'D', 'ou15', 'Over 1.5', .8))
        self.run_day(dict(matches=[match('2026-11-09', 'A', 'B', [1, 1]), match('2026-11-09', 'C', 'D', [3, 1])]), legs)
        s = record.vip_ledger()['summary']
        self.assertEqual((s['win_streak'], s['perfect_slips'], s['settled_slips']), (2, 1, 1))

    def test_vip_rule_is_goals_only(self):
        leg = lambda fx, m, sel, p: dict(fixture=fx, league_id='en.1', market=m, selection=sel, probability=p)
        picks = record.vip_from([
            leg('A v B', 'btts', 'Both teams score', .88), leg('A v B', 'dc', 'A or draw', .90),
            leg('A v B', 'ou15', 'Over 1.5', .85), leg('A v B', 'ou25', 'Over 2.5', .66),      # Over 2.5 wins the game
            leg('C v D', 'ou25', 'Over 2.5', .60), leg('C v D', 'ou15', 'Over 1.5', .80), leg('C v D', 'dc', 'C or draw', .91),
            leg('E v F', 'ou25', 'Under 2.5', .70), leg('E v F', 'ou15', 'Over 1.5', .70), leg('E v F', 'dc', 'E or draw', .82),
            leg('G v H', 'ou15', 'Over 1.5', .77), leg('G v H', 'dc', 'G or draw', .79),      # nothing reaches its floor
            leg('I v J', 'ou15', 'Over 1.5', .95)])                                            # near-certain: no value
        self.assertEqual(sorted((p['fixture'], p['selection']) for p in picks),
                         [('A v B', 'Over 2.5'), ('C v D', 'Over 1.5')])

    def test_missing_file_gives_empty_ledger(self):
        s = record.vip_ledger()['summary']
        self.assertEqual((s['slips'], s['picks'], s['hit_rate']), (0, 0, None))


if __name__ == '__main__':
    unittest.main()
