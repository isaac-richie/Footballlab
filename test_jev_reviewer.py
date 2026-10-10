import os
import unittest
from unittest.mock import patch

from jev_reviewer import review


class JevReviewerTests(unittest.TestCase):
    def test_key_absent_is_explicit_and_makes_no_call(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}, clear=False):
            result = review({})
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('not present', result['reason'])

    def test_local_throttle_is_explicit(self):
        import jev_reviewer
        jev_reviewer._cache.clear()
        forecast = {'model': {'version': 'v'}, 'analysis_date': '2026-10-10', 'readiness': {'status': 'research_only', 'issues': []},
                    'recent_team_samples': {}, 'expected_goals': [1.5, 1.1], 'probabilities': [.5, .3, .2], 'decision': {'action': 'withhold'}}
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'test'}, clear=False), patch('jev_reviewer._permit', return_value=False):
            result = review(forecast)
        self.assertEqual(result['status'], 'throttled')


    def test_identical_evidence_is_cached(self):
        import io, json as _json, jev_reviewer
        forecast = {'model': {'version': 'v'}, 'analysis_date': '2026-10-10', 'readiness': {'status': 'research_only', 'issues': []},
                    'recent_team_samples': {}, 'expected_goals': [1.5, 1.1], 'probabilities': [.5, .3, .2],
                    'decision': {'action': 'withhold'}, 'latest_result': '2026-10-01', 'pricing': {'source': 'live', 'fit_error': 0.001}}
        body = _json.dumps({'answers': {'needs_human_review': {'type': 'noul', 'noul': 0.1}}, 'usage': {}}).encode()
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        jev_reviewer._cache.clear()
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'k'}), patch('jev_reviewer.urlopen', return_value=Resp(body)) as call, \
             patch('jev_reviewer._permit', return_value=True):
            first, second = review(forecast), review(forecast)
        self.assertEqual(call.call_count, 1)
        self.assertFalse(first['cached']); self.assertTrue(second['cached'])
        sent = _json.loads(_json.loads(call.call_args[0][0].data)['state'])
        self.assertEqual(sent['pricing_source'], 'live'); self.assertEqual(sent['days_since_latest_result'], 9)


if __name__ == '__main__':
    unittest.main()
