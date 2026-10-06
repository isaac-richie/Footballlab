import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from evaluation_cache import cached_evaluate


class CacheTests(unittest.TestCase):
    def test_hit_and_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            compute = Mock(return_value={'matches': 10})
            args = dict(directory=directory, day='2026-09-22', revision='v1')
            for _ in range(2):
                self.assertEqual(cached_evaluate({}, 'en.1', compute, **args), {'matches': 10})
            self.assertEqual(compute.call_count, 1)
            cached_evaluate({'changed': True}, 'en.1', compute, **args)
            args['day'] = '2026-09-23'
            cached_evaluate({'changed': True}, 'en.1', compute, **args)
            args['revision'] = 'v2'
            cached_evaluate({'changed': True}, 'en.1', compute, **args)
            cached_evaluate({'changed': True}, 'es.1', compute, **args)
            self.assertEqual(compute.call_count, 5)

    def test_corrupt_and_modified_result_recomputed(self):
        with tempfile.TemporaryDirectory() as directory:
            compute = Mock(return_value={'matches': 10})
            def run():
                return cached_evaluate({}, 'en.1', compute, directory, revision='v1')
            run()
            path = next(Path(directory).glob('*.json'))
            path.write_text('broken')
            run()
            entry = json.loads(path.read_text())
            entry['result']['matches'] = 999
            path.write_text(json.dumps(entry))
            self.assertEqual(run()['matches'], 10)
            self.assertEqual(compute.call_count, 3)

    def test_concurrent_requests_compute_once(self):
        with tempfile.TemporaryDirectory() as directory:
            compute = Mock(return_value={'matches': 10})
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: cached_evaluate({}, 'en.1', compute,
                                    directory, revision='v1'), range(8)))
            self.assertEqual(compute.call_count, 1)
            self.assertTrue(all(r == {'matches': 10} for r in results))

    def test_storage_failure_does_not_fail_evaluation(self):
        with tempfile.TemporaryDirectory() as directory, patch('evaluation_cache.atomic_write', side_effect=OSError):
            self.assertEqual(cached_evaluate({}, 'en.1', lambda *_: {'ok': True}, directory), {'ok': True})

    def test_failed_evaluation_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                cached_evaluate({}, 'en.1', Mock(side_effect=ValueError('bad data')), directory)
            self.assertEqual(list(Path(directory).iterdir()), [])
