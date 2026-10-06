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
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'test'}, clear=False), patch('jev_reviewer._permit', return_value=False):
            result = review({})
        self.assertEqual(result['status'], 'throttled')


if __name__ == '__main__':
    unittest.main()
