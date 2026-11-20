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


if __name__ == '__main__':
    unittest.main()
