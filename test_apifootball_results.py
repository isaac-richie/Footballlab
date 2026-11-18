import datetime as dt
import unittest

import apifootball_results as A


def fx(league_id, date, home, away, h, a, status='FT'):
    return dict(league=dict(id=league_id), fixture=dict(date=date + 'T19:00:00+00:00', status=dict(short=status)),
                teams=dict(home=dict(name=home), away=dict(name=away)), goals=dict(home=h, away=a))


def ours(date, home, away, goals=None, league='es.1'):
    return dict(league_id=league, season='2026-27', date=date, home=home, away=away, goals=goals)


TODAY = dt.date(2026, 11, 18)


class FetchTests(unittest.TestCase):
    def test_free_plan_falls_back_to_yesterday_and_today(self):
        calls = []

        def get(params, key):
            calls.append(params)
            if 'season' in params:
                raise A.PlanLimit('Free plans do not have access to this season')
            return [fx(140, params['date'], 'Real Madrid', 'Getafe', 2, 0), fx(999, params['date'], 'X', 'Y', 1, 0),
                    fx(140, params['date'], 'Sevilla', 'Betis', None, None, status='NS')]
        out, mode = A.fetch_finished('k', TODAY, get=get)
        self.assertEqual(mode, 'dates')
        self.assertEqual([c.get('date') for c in calls[1:]], ['2026-11-17', '2026-11-18'])
        self.assertEqual(len(out), 2)                      # our league, finished only, from both days
        self.assertTrue(all(lg == 'es.1' for lg, _ in out))

    def test_paid_plan_reads_whole_seasons(self):
        out, mode = A.fetch_finished('k', TODAY, leagues=('es.1',), get=lambda p, k: [fx(140, '2026-10-04', 'A', 'B', 1, 1)])
        self.assertEqual((mode, len(out)), ('season', 1))


class MergeTests(unittest.TestCase):
    def test_fills_missing_scores_and_never_overwrites(self):
        matches = [ours('2026-10-04', 'Real Madrid CF', 'Getafe CF'), ours('2026-09-20', 'Sevilla FC', 'Real Betis', [1, 1])]
        finished = [('es.1', fx(140, '2026-10-04', 'Real Madrid', 'Getafe', 3, 1)), ('es.1', fx(140, '2026-09-20', 'Sevilla', 'Real Betis', 2, 2))]
        filled, skipped = A.merge(matches, finished, TODAY)
        self.assertEqual(filled, {'es.1': 1})
        self.assertEqual(matches[0]['goals'], [3, 1])
        self.assertEqual(matches[0]['score_source'], 'api-football')
        self.assertEqual(matches[1]['goals'], [1, 1])      # existing score kept
        self.assertEqual(skipped, {})

    def test_skips_a_league_that_disagrees_with_known_scores(self):
        teams = [f'Club {c}' for c in 'ABCDEFGHIJKL']
        known = [ours(f'2026-09-{d + 1:02d}', teams[d], teams[d + 1], [1, 0]) for d in range(11)]
        gap = ours('2026-10-20', 'Club A', 'Club L')
        finished = [('es.1', fx(140, m['date'], m['home'], m['away'], 0, 3)) for m in known]   # all disagree
        finished.append(('es.1', fx(140, '2026-10-20', 'Club A', 'Club L', 2, 0)))
        filled, skipped = A.merge(known + [gap], finished, TODAY)
        self.assertEqual(filled, {})
        self.assertIn('es.1', skipped)
        self.assertIsNone(gap['goals'])

    def test_no_key_does_nothing(self):
        import os
        old = os.environ.pop('API_FOOTBALL_KEY', None)
        try:
            self.assertEqual(A.fill([], key=''), dict(skipped='no API_FOOTBALL_KEY'))
        finally:
            if old is not None:
                os.environ['API_FOOTBALL_KEY'] = old


class FreshnessTests(unittest.TestCase):
    def test_league_fresh_uses_the_latest_result(self):
        import app
        data = dict(matches=[ours('2026-11-08', 'A', 'B', [1, 0], 'en.1'), ours('2026-09-20', 'C', 'D', [2, 1], 'nl.1'),
                             ours('2026-11-22', 'E', 'F', None, 'nl.1')])
        self.assertTrue(app.league_fresh(data, 'en.1', TODAY))      # 10 days: an international break
        self.assertFalse(app.league_fresh(data, 'nl.1', TODAY))     # 59 days
        self.assertFalse(app.league_fresh(data, 'pt.1', TODAY))     # no results at all
        self.assertEqual(app.results_age(data, 'nl.1', TODAY), 59)


if __name__ == '__main__':
    unittest.main()
