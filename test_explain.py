import unittest

import explain


def game(date, home, away, goals):
    return dict(date=date, home=home, away=away, goals=goals, league_id='en.1')


ROWS = [game(f'2026-10-{d:02d}', 'A' if d % 2 else 'X', 'X' if d % 2 else 'A', [2, 2]) for d in range(1, 11)] + \
       [game(f'2026-10-{d:02d}', 'B' if d % 2 else 'Y', 'Y' if d % 2 else 'B', [1, 0]) for d in range(1, 11)]


class ExplainTests(unittest.TestCase):
    def test_goal_reason_counts_recent_overs(self):
        leg = dict(home='A', away='B', market='ou25', selection='Over 2.5', probability=.7)
        why = explain.reason(leg, ROWS)
        self.assertIn("10 of A's last 10 and 0 of B's last 10 went over 2.5", why)

    def test_under_counts_the_other_side(self):
        leg = dict(home='A', away='B', market='ou25', selection='Under 2.5', probability=.6)
        self.assertIn("0 of A's last 10 and 10 of B's last 10 went under 2.5", explain.reason(leg, ROWS))

    def test_btts_and_thin_history(self):
        leg = dict(home='A', away='B', market='btts', selection='Both teams score', probability=.6)
        self.assertIn("Both teams scored in 10 of A's last 10 and 0 of B's", explain.reason(leg, ROWS))
        self.assertIn('little recent history', explain.reason(dict(leg, home='Nobody'), ROWS))

    def test_confidence_rises_with_a_record_that_beats_its_chance(self):
        leg = dict(market='ou15', probability=.84)
        plain = explain.confidence(leg)
        good = explain.confidence(leg, {('ou15', '80-90%'): [100, 92, 83.0]})
        bad = explain.confidence(leg, {('ou15', '80-90%'): [100, 70, 83.0]})
        self.assertLess(bad['score'], plain['score'])
        self.assertLess(plain['score'], good['score'])
        self.assertEqual(good['parts'], ['80-90% 1.5-goal picks won 92% of 100 (said 83%)'])
        # Too few graded picks: the record is left neutral.
        self.assertEqual(explain.confidence(leg, {('ou15', '80-90%'): [5, 5, 4.2]})['score'], plain['score'])

    def test_track_table_reads_graded_vip_legs(self):
        rec = {'days': {'d': {'vip': [dict(market='ou25', probability=.72, won=True), dict(market='ou25', probability=.74, won=False),
                                       dict(market='ou25', probability=.74, won=None)]}}}
        self.assertEqual(explain.track_table(rec), {('ou25', '70-80%'): [2, 1, 1.46]})

    def test_nba_total_reason(self):
        leg = dict(sport='nba', market='total', side='under', line=228.5, expected_total=218.2, probability=.71)
        self.assertIn('10 below this line', explain.reason(leg, []))

    def test_annotate_never_raises(self):
        legs = [dict(league_id='en.1', home='A', away='B', market='ou25', selection='Over 2.5', probability=.7)]
        explain.annotate(legs, lambda lid: 1 / 0)
        self.assertIsNone(legs[0]['why'])


if __name__ == '__main__':
    unittest.main()
