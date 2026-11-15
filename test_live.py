import unittest

import football_live as F
import nba_live as N


def fx(league, home, away, code='2H', date='2026-11-21T15:00:00+00:00'):
    return dict(league=dict(id=league), fixture=dict(date=date, status=dict(short=code, elapsed=67)),
                teams=dict(home=dict(name=home), away=dict(name=away)), goals=dict(home=2, away=1))


class FootballLive(unittest.TestCase):
    sch = {'en.1': [('2026-11-21', 'Wolverhampton Wanderers FC', 'West Ham United FC'),
                    ('2026-11-21', 'Manchester City FC', 'Fulham FC')],
           'it.1': [('2026-11-21', 'FC Internazionale Milano', 'SSC Napoli')]}

    def test_short_names_match_the_days_fixture(self):
        out = F.snapshot([fx(39, 'Wolves', 'West Ham'), fx(135, 'Inter', 'Napoli', 'FT')], self.sch)
        self.assertEqual(out['2026-11-21|Wolverhampton Wanderers FC|West Ham United FC'],
                         dict(status='live', score=[2, 1], clock="67'"))
        self.assertEqual(out['2026-11-21|FC Internazionale Milano|SSC Napoli']['clock'], 'FT')

    def test_other_leagues_and_unstarted_are_skipped(self):
        self.assertEqual(F.snapshot([fx(40, 'Wolves', 'West Ham'), fx(39, 'Wolves', 'West Ham', 'NS')], self.sch), {})


class NbaLive(unittest.TestCase):
    def ev(self, **kw):
        e = dict(id=7, date='2026-11-15', season=2026, status='3rd Qtr', status_state='in', period=3, time='5:12',
                 postseason=False, postponed=False, home_team_score=88, visitor_team_score=80,
                 datetime='2026-11-15T18:00:00.000Z',
                 home_team=dict(abbreviation='PHI', full_name='Philadelphia 76ers'),
                 visitor_team=dict(abbreviation='IND', full_name='Indiana Pacers'))
        e.update(kw)
        return e

    def test_live_and_final(self):
        out = N.snapshot([self.ev(), self.ev(id=8, status='Final', status_state='final', period=4, date='2026-11-14')])
        self.assertEqual(out['bdl7'], dict(status='live', score=[88, 80], clock='Q3 5:12'))
        self.assertEqual(out['2026-11-15|PHI']['status'], 'live')
        self.assertEqual(out['bdl8']['clock'], 'Final')

    def test_scheduled_left_out(self):
        self.assertEqual(N.snapshot([self.ev(status_state='scheduled', period=0)]), {})


if __name__ == '__main__':
    unittest.main()
