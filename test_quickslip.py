import unittest

import quickslip


def leg(game, p, market='ou25'):
    return dict(game=game, probability=p, market=market, id=f'{game}|{market}|{p}')


LEGS = [leg('g1', .95), leg('g1', .7, 'btts'), leg('g2', .88), leg('g3', .82), leg('g4', .72), leg('g4', .66, 'dc'),
        leg('g5', .68), leg('g6', .6), leg('g7', .5)]


class QuickSlipTests(unittest.TestCase):
    def test_one_pick_per_game_and_nothing_under_the_floor(self):
        for s in quickslip.STRATEGIES:
            out = quickslip.choose(LEGS, 7, s)
            self.assertEqual(len({l['game'] for l in out}), len(out), s)
            self.assertTrue(all(l['probability'] >= quickslip.FLOOR for l in out), s)

    def test_safest_takes_the_surest(self):
        self.assertEqual([l['probability'] for l in quickslip.choose(LEGS, 3, 'safest')], [.95, .88, .82])

    def test_balanced_adds_two_swings(self):
        out = quickslip.choose(LEGS, 4, 'balanced')
        self.assertEqual(sum(.60 <= l['probability'] <= .75 for l in out), 2)
        self.assertEqual(sum(l['probability'] >= .8 for l in out), 2)

    def test_banker_leads_with_85_plus(self):
        out = quickslip.choose(LEGS, 4, 'banker')
        self.assertEqual(out[0]['probability'], .95)
        self.assertTrue(all(.70 <= l['probability'] < .85 for l in out[2:]))

    def test_value_keeps_to_its_price_band_and_spreads_markets(self):
        many = [leg(f'v{i}', .7) for i in range(6)] + [leg('w1', .68, 'dc'), leg('w2', .69, 'btts')]
        out = quickslip.choose(many, 6, 'value', score=lambda l: 1)
        self.assertTrue(all(1.35 <= 1 / l['probability'] <= 1.85 for l in out))
        self.assertLessEqual(sum(l['market'] == 'ou25' for l in out), 2)

    def test_time_windows(self):
        self.assertEqual(quickslip.local_hour('2026-11-20T19:30:00Z', 60), 20)
        self.assertTrue(quickslip.in_window(20, 'late'))
        self.assertFalse(quickslip.in_window(20, 'early'))
        self.assertTrue(quickslip.in_window(None, 'all'))
        self.assertFalse(quickslip.in_window(None, 'late'))


if __name__ == '__main__':
    unittest.main()
