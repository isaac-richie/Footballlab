import csv
import json
import tempfile
import unittest
from pathlib import Path

from stats import import_csv, market_rates, poisson_over


class StatsTests(unittest.TestCase):
    def fixture(self):
        return dict(league_id='en.1', date='2024-01-01', home='A', away='B', goals=[1, 0])

    def test_import_requires_exact_known_fixture_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path, output = Path(directory) / 'x.csv', Path(directory) / 'stats.json'
            csv_path.write_text('league_id,date,home,away,home_shots,away_shots,home_red_cards,away_red_cards,source\n'
                                'en.1,2024-01-01,A,B,11,8,0,1,manual licensed export\n')
            result = import_csv(csv_path, output, [self.fixture()])
            self.assertEqual(result['imported'], 1)
            self.assertEqual(json.loads(output.read_text())['records'][0]['home_shots'], 11)
            csv_path.write_text('league_id,date,home,away,home_shots,away_shots,home_red_cards,away_red_cards,source\n'
                                'en.1,2024-01-02,A,B,11,8,0,1,manual licensed export\n')
            with self.assertRaises(ValueError):
                import_csv(csv_path, output, [self.fixture()])

    def test_supplemental_rates_withhold_small_history(self):
        records = [dict(date='2024-01-01', home='A', away='B', home_shots=10, away_shots=8)] * 10
        self.assertIsNone(market_rates(records, 'A', 'B', '2025-01-01', 'home_shots', 'away_shots'))

    def test_poisson_over(self):
        self.assertGreater(poisson_over(20, 15.5), .8)
        self.assertLess(poisson_over(.1, .5), .1)


if __name__ == '__main__':
    unittest.main()
