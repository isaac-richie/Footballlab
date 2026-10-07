import math
import unittest

from app import distribution
from parlay import build, legs_for


def fixtures(n):
    out = []
    for i in range(n):
        f = dict(league_id='en.1', date='2026-10-10', home=f'H{i}', away=f'A{i}')
        out += legs_for(f, distribution(1.2 + i * 0.1, 1.0), 'model')
    return out


class ParlayTests(unittest.TestCase):
    def test_one_leg_per_fixture_and_product(self):
        r = build(fixtures(6), 4)
        self.assertEqual(len(r['legs']), 4)
        self.assertEqual(len({l['fixture'] for l in r['legs']}), 4)
        self.assertAlmostEqual(r['probability'], math.prod(l['probability'] for l in r['legs']))
        self.assertAlmostEqual(r['fair_odds'], 1 / r['probability'])

    def test_filters_lock_exclude_and_shuffle(self):
        c = fixtures(8)
        r = build(c, 3, min_p=0.3, max_p=0.6, markets=['ou25', 'btts'])
        self.assertTrue(all(0.3 <= l['probability'] <= 0.6 and l['market'] in ('ou25', 'btts') for l in r['legs']))
        lock = next(l for l in c if l['selection'] == 'Draw')
        r2 = build(c, 3, locked=[lock['id']], seed=5)
        self.assertEqual(r2['legs'][0]['id'], lock['id'])
        r3 = build(c, 3, exclude=[r['legs'][0]['fixture']])
        self.assertNotIn(r['legs'][0]['fixture'], {l['fixture'] for l in r3['legs']})
        self.assertEqual(build(c, 5, seed=3)['legs'], build(c, 5, seed=3)['legs'])
        self.assertNotEqual([l['id'] for l in build(c, 5, seed=3)['legs']], [l['id'] for l in build(c, 5, seed=4)['legs']])

    def test_incomplete_when_not_enough_fixtures(self):
        r = build(fixtures(2), 5)
        self.assertFalse(r['complete'])
        self.assertEqual(len(r['legs']), 2)


if __name__ == '__main__':
    unittest.main()
