import unittest

import model_health as H


class Judge(unittest.TestCase):
    def picks(self, n, said, won):
        k = round(n * won)
        return [(said, i < k) for i in range(n)]

    def test_statuses(self):
        self.assertEqual(H.judge(self.picks(40, .75, .5))['status'], 'collecting')     # too few to judge
        self.assertEqual(H.judge(self.picks(200, .75, .76))['status'], 'ok')
        self.assertEqual(H.judge(self.picks(200, .75, .71))['status'], 'watch')
        self.assertEqual(H.judge(self.picks(200, .75, .68))['status'], 'alert')
        self.assertEqual(H.judge(self.picks(200, .70, .78))['status'], 'cautious')

    def test_alert_from_sample_size(self):
        self.assertEqual(H.judge(self.picks(2000, .75, .715))['status'], 'alert')       # 3.5 points, but z < -2.5

    def test_football_counts_each_game_once(self):
        ledger = dict(days=[dict(picks=[dict(date='2026-11-22', market='ou15', selection='Over 1.5', probability=.8, status='won', counted=True, side='overs'),
                                        dict(date='2026-11-22', market='ou15', selection='Over 1.5', probability=.8, status='won', counted=False, side='overs')])])
        self.assertEqual(len([r for r in H.football_rows(ledger) if r[0] == 'overs']), 1)


if __name__ == '__main__':
    unittest.main()
