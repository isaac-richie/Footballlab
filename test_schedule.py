import datetime as dt
import unittest

import schedule


class ScheduleTests(unittest.TestCase):
    def test_kickoff_converts_uk_time_to_utc(self):
        self.assertEqual(schedule.kickoff_utc('2026-10-24', '17:30'), '2026-10-24T16:30:00Z')   # BST
        self.assertEqual(schedule.kickoff_utc('2026-12-05', '15:00'), '2026-12-05T15:00:00Z')   # GMT
        self.assertIsNone(schedule.kickoff_utc('2026-12-05', ''))

    def test_status(self):
        now = dt.datetime(2026, 10, 24, 17, 0, tzinfo=dt.timezone.utc)
        m = dict(date='2026-10-24', goals=None, kickoff='2026-10-24T16:30:00Z')
        self.assertEqual(schedule.status(m, now), 'live')
        self.assertEqual(schedule.status({**m, 'kickoff': '2026-10-24T18:00:00Z'}, now), 'scheduled')
        self.assertEqual(schedule.status({**m, 'kickoff': '2026-10-24T12:00:00Z'}, now), 'awaiting_result')
        self.assertEqual(schedule.status({**m, 'goals': [1, 0]}, now), 'finished')

    def test_reconcile_moves_dates_adds_results_and_flags_stale_fixtures(self):
        matches = [dict(league_id='en.1', league='L', season='2026-27', date='2026-10-31', home='A FC', away='B FC', goals=None, ht=None),
                   dict(league_id='en.1', league='L', season='2026-27', date='2026-10-25', home='C FC', away='D FC', goals=None, ht=None)]
        market = dict(records=[
            dict(league_id='en.1', date='2026-10-25', time='15:00', fd_home='A', fd_away='B', home='A FC', away='B FC', goals=None, upcoming=True, odds={}),
            dict(league_id='en.1', date='2026-10-26', time='20:00', fd_home='E', fd_away='F', home=None, away=None, goals=None, upcoming=True, odds={}),
            dict(league_id='en.1', date='2026-10-20', time='20:00', fd_home='C', fd_away='A', home='C FC', away='A FC', goals=[2, 1], odds={})])
        data = dict(matches=matches)
        schedule.reconcile(data, market, today='2026-10-24')
        a = next(m for m in data['matches'] if m['home'] == 'A FC')
        self.assertEqual((a['date'], a['kickoff']), ('2026-10-25', '2026-10-25T15:00:00Z'))   # clocks go back that morning
        self.assertTrue(next(m for m in data['matches'] if m['home'] == 'C FC' and m['away'] == 'D FC')['unconfirmed'])
        self.assertEqual(next(m for m in data['matches'] if m['away'] == 'A FC')['goals'], [2, 1])
        self.assertTrue(any(m['home'] == 'E' for m in data['matches']))


if __name__ == '__main__':
    unittest.main()
