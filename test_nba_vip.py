import datetime as dt
import unittest

import nba_vip


class InPlayTests(unittest.TestCase):
    """A pick settles the moment the score decides it: totals only go up."""

    def test_football_overs_win_at_the_deciding_goal(self):
        self.assertIsNone(nba_vip.in_play('Over 1.5', [1, 0], 'ou15'))
        self.assertTrue(nba_vip.in_play('Over 1.5', [1, 1], 'ou15'))          # second goal: won
        self.assertIsNone(nba_vip.in_play('Over 2.5', [2, 0], 'ou25'))        # two goals do not win an Over 2.5
        self.assertTrue(nba_vip.in_play('Over 2.5', [2, 1], 'ou25'))

    def test_unders_lose_once_passed_and_btts(self):
        self.assertIsNone(nba_vip.in_play('Under 2.5', [1, 1], 'ou25'))
        self.assertFalse(nba_vip.in_play('Under 2.5', [2, 1], 'ou25'))
        self.assertIsNone(nba_vip.in_play('Both teams score', [2, 0], 'btts'))
        self.assertTrue(nba_vip.in_play('Both teams score', [2, 1], 'btts'))
        self.assertFalse(nba_vip.in_play('Not both teams score', [1, 1], 'btts'))
        self.assertIsNone(nba_vip.in_play('Arsenal win', [3, 0], '1x2'))       # results are never settled early

    def test_nba_points_and_what_an_over_still_needs(self):
        row = dict(selection='Over 216.5 points', market='total', status='live')
        nba_vip.settle_in_play(row, [100, 110])
        self.assertEqual((row['status'], row['needs']), ('live', 7))          # 210 now, 217 wins
        nba_vip.settle_in_play(row, [110, 107])
        self.assertEqual((row['status'], row['in_play']), ('won', True))


class SaveAndGradeTests(unittest.TestCase):
    def test_once_a_day_one_pick_per_game_untipped_only(self):
        now = dt.datetime(2026, 11, 18, 6, 0, tzinfo=dt.timezone.utc)
        totals = [dict(id='g1', date='2026-11-18', tipoff='2026-11-19T00:00:00Z', home='A', away='B', side='over', line=220.5, probability=.74),
                  dict(id='g2', date='2026-11-18', tipoff='2026-11-18T05:00:00Z', home='C', away='D', side='under', line=230.5, probability=.80),
                  dict(id='g1', date='2026-11-18', tipoff='2026-11-19T00:00:00Z', home='A', away='B', side='under', line=240.5, probability=.72),
                  dict(id='g3', date='2026-11-18', tipoff='2026-11-19T01:00:00Z', home='E', away='F', side='under', line=225.5, probability=.71)]
        store = dict(days={})
        self.assertTrue(nba_vip.freeze(store, totals, now.date(), now))
        self.assertEqual([p['id'] for p in store['days']['2026-11-18']['picks']], ['g1', 'g3'])   # g2 already tipped off
        self.assertFalse(nba_vip.freeze(store, totals[3:], now.date(), now))                       # never rewritten
        nba_vip.grade(store, [dict(id='g1', status='final', score=[118, 110]), dict(id='g3', status='postponed')])
        self.assertEqual([nba_vip.status_of(p) for p in store['days']['2026-11-18']['picks']], ['won', 'void'])

    def test_top_up_adds_new_picks_and_never_changes_saved_ones(self):
        now = dt.datetime(2026, 11, 20, 9, 0, tzinfo=dt.timezone.utc)
        tip = '2026-11-21T00:00:00Z'
        old = [dict(id='g1', date='2026-11-20', tipoff=tip, home='A', away='B', side='under', line=230.5, probability=.71)]
        store = dict(days={})
        nba_vip.freeze(store, old, now.date(), now)
        later = now + dt.timedelta(hours=2)
        totals = [dict(old[0], line=228.5, probability=.72),                                   # same game, new line: ignored
                  dict(id='g2', date='2026-11-20', tipoff=tip, home='C', away='D', side='over', line=220.5, probability=.70),
                  dict(id='g3', date='2026-11-20', tipoff='2026-11-20T10:00:00Z', home='E', away='F', side='over', line=219.5, probability=.70)]
        self.assertTrue(nba_vip.freeze(store, totals, now.date(), later))
        picks = store['days']['2026-11-20']['picks']
        self.assertEqual([(p['id'], p['line']) for p in picks], [('g1', 230.5), ('g2', 220.5)])   # g3 tipped off before the top-up
        self.assertEqual(picks[1]['saved_at'], later.isoformat())

    def test_surest_winners_join_from_other_games(self):
        now = dt.datetime(2026, 11, 21, 6, 0, tzinfo=dt.timezone.utc)
        tip = '2026-11-22T00:00:00Z'
        totals = [dict(id='g1', date='2026-11-21', tipoff=tip, home='A', away='B', side='under', line=230.5, probability=.71)]
        winners = [dict(id='g1', date='2026-11-21', tipoff=tip, home='A', away='B', team='A', probability=.90),   # game already taken
                   dict(id='g2', date='2026-11-21', tipoff=tip, home='C', away='D', team='D', probability=.86),
                   dict(id='g3', date='2026-11-21', tipoff=tip, home='E', away='F', team='E', probability=.79),   # below 80%
                   dict(id='g4', date='2026-11-21', tipoff=tip, home='G', away='H', team='G', probability=.84),
                   dict(id='g5', date='2026-11-21', tipoff=tip, home='I', away='J', team='I', probability=.83)]  # only two winners
        picks = nba_vip.choose(totals, now, winners=winners)
        self.assertEqual([(p['id'], nba_vip.label(p)) for p in picks],
                         [('g1', 'Under 230.5 points'), ('g2', 'D to win'), ('g4', 'G to win')])
        self.assertTrue(nba_vip.won(picks[1], [99, 104]))       # away team D won
        self.assertFalse(nba_vip.won(picks[2], [99, 104]))      # home team G lost

    def test_ticket_legs_use_live_scores(self):
        from unittest.mock import patch
        store = dict(days={'2026-11-18': dict(frozen_at='x', picks=[
            dict(id='g1', date='2026-11-18', tipoff='2026-11-19T00:00:00Z', home='A', away='B', home_abbr='AAA', side='over', line=220.5, probability=.74)])})
        with patch.object(nba_vip, 'load', return_value=store):
            rows, saved = nba_vip.ticket_legs(True, '2026-11-18', live={'g1': dict(status='live', score=[60, 55], clock='Q2 3:10')})
        self.assertTrue(saved)
        self.assertEqual((rows[0]['status'], rows[0]['clock'], rows[0]['needs'], rows[0]['sport']), ('live', 'Q2 3:10', 106, 'nba'))


class GameDayTests(unittest.TestCase):
    def test_new_york_date_keeps_a_night_together(self):
        late = dt.datetime(2026, 11, 21, 3, 30, tzinfo=dt.timezone.utc)        # 10:30pm ET on the 20th
        self.assertEqual(nba_vip.game_day(late).isoformat(), '2026-11-20')

    def test_old_slips_regroup_by_game_day_without_duplicates(self):
        pick = lambda i, d, won=None: dict(id=i, date=d, tipoff=d + 'T23:00:00Z', home='A', away='B', side='under', line=230.5, probability=.7, won=won)
        old = dict(days={'2026-11-19': dict(frozen_at='2026-11-19T14:00', picks=[pick('m', '2026-11-19', True), pick('b', '2026-11-20')]),
                         '2026-11-20': dict(frozen_at='2026-11-20T08:00', picks=[pick('b', '2026-11-20'), pick('s', '2026-11-21')])})
        new = nba_vip.by_game_day(old)['days']
        self.assertEqual({k: [p['id'] for p in v['picks']] for k, v in new.items()},
                         {'2026-11-19': ['m'], '2026-11-20': ['b'], '2026-11-21': ['s']})
        self.assertEqual(new['2026-11-20']['picks'][0]['saved_at'], '2026-11-19T14:00')      # first time it was published

    def test_freeze_only_takes_tonights_games(self):
        now = dt.datetime(2026, 11, 20, 9, 0, tzinfo=dt.timezone.utc)
        totals = [dict(id='t', date='2026-11-20', tipoff='2026-11-21T00:30:00Z', home='A', away='B', side='over', line=220.5, probability=.72),
                  dict(id='n', date='2026-11-21', tipoff='2026-11-22T00:30:00Z', home='C', away='D', side='over', line=221.5, probability=.80)]
        store = dict(days={})
        nba_vip.freeze(store, totals, now.date(), now)
        self.assertEqual(list(store['days']), ['2026-11-20'])
        self.assertEqual([p['id'] for p in store['days']['2026-11-20']['picks']], ['t'])

    def test_ledger_settles_finished_games_from_live_scores(self):
        from unittest.mock import patch
        store = dict(days={'2026-11-19': dict(frozen_at='x', picks=[
            dict(id='g', date='2026-11-19', tipoff='2026-11-20T01:00:00Z', home='A', away='B', side='under', line=230.5, probability=.71)])})
        with patch.object(nba_vip, 'load', return_value=store):
            led = nba_vip.ledger(True, live={'g': dict(status='final', score=[110, 104])})
        self.assertEqual((led['days'][0]['picks'][0]['status'], led['days'][0]['settled'], led['summary']['won']), ('won', True, 1))


if __name__ == '__main__':
    unittest.main()
