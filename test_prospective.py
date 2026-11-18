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

    def test_rescheduled_fixture_is_graded_on_its_new_date(self):
        fixture = dict(date='2026-11-07', league_id='en.1', league='England', home='A', away='B')
        analysis = dict(readiness={'status': 'review_required'}, probabilities=[.5, .3, .2],
                        expected_goals=[1.5, 1.], over25=.5, btts=.5, decision={'action': 'withhold'})
        report = dict(fixtures=[dict(fixture=fixture, analysis=analysis)], generated_at='2026-11-01T12:00:00+00:00',
                      run_id='r', data_hash='d', code_hash='c', model={'version': 'v1'})
        with tempfile.TemporaryDirectory() as temporary:
            register(report, temporary)
            moved = lambda date, goals: {'matches': [{**fixture, 'date': date, 'goals': goals}]}
            later = grade(moved('2026-11-08', [1, 0]), temporary, today='2026-11-10')
            self.assertEqual(later['fixtures'][0]['status'], 'graded')
            self.assertEqual(later['fixtures'][0]['played_on'], '2026-11-08')
            self.assertEqual(grade(moved('2026-11-20', None), temporary, today='2026-11-10')['fixtures'][0]['status'], 'pending')
            early = grade(moved('2026-11-01', [1, 0]), temporary, today='2026-11-10')
            self.assertEqual(early['fixtures'][0]['status'], 'void')
            self.assertEqual(early['void'], 1)
            far = grade(moved('2027-03-01', [1, 0]), temporary, today='2027-04-01')
            self.assertEqual(far['fixtures'][0]['status'], 'missing_result')

    def test_same_day_registration_is_excluded(self):
        fixture = dict(date='2026-10-10', league_id='en.1', home='A', away='B')
        report = dict(fixtures=[dict(fixture=fixture, analysis={'probabilities': [.5, .3, .2]})],
                      generated_at='2026-10-09T23:30:00+00:00', run_date='2026-10-10')
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(register(report, temporary), 0)


if __name__ == '__main__':
    unittest.main()
