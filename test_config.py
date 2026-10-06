import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from config import load_environment


class ConfigTests(unittest.TestCase):
    def test_local_file_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text('# local\nTYPESAFE_API_KEY="test-only"\n')
            load_environment(path)
            self.assertEqual(os.environ['TYPESAFE_API_KEY'], 'test-only')
            os.environ['TYPESAFE_API_KEY'] = ''
            load_environment(path)
            self.assertEqual(os.environ['TYPESAFE_API_KEY'], '')

    def test_missing_file_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            load_environment(Path(directory) / '.env')

    def test_invalid_entries_do_not_expose_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            for line in ('UNKNOWN=private-value', 'TYPESAFE_API_KEY="private-value'):
                path.write_text(line)
                with self.assertRaises(ValueError) as caught:
                    load_environment(path)
                self.assertNotIn('private-value', str(caught.exception))
