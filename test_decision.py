import unittest

from decision import assess


def forecast(status='research_only', market=True):
    value = dict(readiness={'status': status}, probabilities=[.55, .25, .20])
    if market:
        value['market'] = dict(gap=[.06, -.03, -.03], expected_return=[.10, -.1, -.1])
    return value


class DecisionTests(unittest.TestCase):
    def test_quality_gate_overrides_good_market(self):
        result = assess(forecast(status='review_required'))
        self.assertEqual(result['action'], 'withhold')

    def test_missing_market_withholds(self):
        self.assertEqual(assess(forecast(market=False))['action'], 'withhold')

    def test_candidate_requires_all_predeclared_thresholds(self):
        result = assess(forecast())
        self.assertEqual(result['action'], 'research_candidate')
        self.assertEqual(result['candidates'][0]['outcome'], 'home')

    def test_small_gap_withholds(self):
        value = forecast(); value['market']['gap'][0] = .01
        self.assertEqual(assess(value)['action'], 'withhold')


if __name__ == '__main__':
    unittest.main()
