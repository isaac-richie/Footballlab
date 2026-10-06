import tempfile
import unittest
from pathlib import Path

from prospective import grade, register


class ProspectiveTests(unittest.TestCase):
    def test_first_forecast_is_frozen_and_later_result_is_scored(self):
        fixture = dict(date='2026-10-10', league_id='en.1', league='England', home='A', away='B')
        analysis = dict(readiness={'status': 'review_required'}, probabilities=[.6, .25, .15],
                        expected_goals=[2., 1.], over25=.55, btts=.5,
                        decision={'action': 'withhold'})
        report = dict(fixtures=[dict(fixture=fixture, analysis=analysis)],
                      generated_at='2026-10-09T12:00:00+00:00', run_id='first',
                      data_hash='data-1', code_hash='code-1', model={'version': 'v1'})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(register(report, directory), 1)
            report['run_id'] = 'second'
            analysis['probabilities'] = [.1, .2, .7]
            self.assertEqual(register(report, directory), 0)
            data = {'matches': [{**fixture, 'goals': [2, 1]}]}
            result = grade(data, directory, today='2026-10-11')
            self.assertEqual(result['overall']['matches'], 1)
            self.assertEqual(result['fixtures'][0]['run_id'], 'first')
            self.assertAlmostEqual(result['overall']['log_loss'], -__import__('math').log(.6))

    def test_same_day_registration_is_excluded(self):
        fixture = dict(date='2026-10-10', league_id='en.1', home='A', away='B')
        report = dict(fixtures=[dict(fixture=fixture, analysis={'probabilities': [.5, .3, .2]})],
                      generated_at='2026-10-09T23:30:00+00:00', run_date='2026-10-10')
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(register(report, temporary), 0)


if __name__ == '__main__':
    unittest.main()
