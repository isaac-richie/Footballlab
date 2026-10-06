import json
import tempfile
import unittest
from unittest.mock import patch

from lineups import DAILY_BUDGET, match_setup


def player(name, number, pos, grid):
    return dict(player=dict(id=number, name=name, number=number, pos=pos, grid=grid))


LINEUP_HOME = dict(team=dict(id=42, name='Arsenal', colors=dict(player=dict(primary='ff0000', number='ffffff', border='ff0000'),
                                                                 goalkeeper=dict(primary='00ff00', number='000000', border='00ff00'))),
                   formation='4-3-3', coach=dict(name='M. Arteta'),
                   startXI=[player('D. Raya', 22, 'G', '1:1')] + [player(f'D{i}', i, 'D', f'2:{i}') for i in range(1, 5)] +
                   [player(f'M{i}', 5 + i, 'M', f'3:{i}') for i in range(1, 4)] + [player(f'F{i}', 8 + i, 'F', f'4:{i}') for i in range(1, 4)],
                   substitutes=[player('Sub', 30, 'M', None)])
FIXTURES = dict(response=[dict(fixture=dict(id=1001, date='2026-10-10T14:00:00+00:00', referee='M. Oliver', venue=dict(name='Emirates Stadium')),
                               teams=dict(home=dict(id=42, name='Arsenal'), away=dict(id=63, name='Leeds')))], errors=[])


class LineupTests(unittest.TestCase):
    def fake(self, routes):
        calls = []
        def fetch(url):
            calls.append(url)
            for fragment, body in routes:
                if fragment in url:
                    return body, '77'
            raise AssertionError('unexpected ' + url)
        return fetch, calls

    def test_confirmed_and_fallback_lineups(self):
        last_away = dict(response=[dict(fixture=dict(id=900, date='2026-10-03T14:00:00+00:00'))], errors=[])
        away_prev = dict(response=[dict(LINEUP_HOME, team=dict(id=63, name='Leeds', colors={}), formation='5-4-1')], errors=[])
        fetch, calls = self.fake([('fixtures/lineups?fixture=1001', dict(response=[LINEUP_HOME], errors=[])),
                                  ('fixtures/lineups?fixture=900', away_prev), ('injuries', dict(response=[dict(
                                      team=dict(name='Leeds'), player=dict(name='X', type='Missing Fixture', reason='Knee Injury'))], errors=[])),
                                  ('team=63', last_away), ('fixtures?', FIXTURES)])
        with tempfile.TemporaryDirectory() as d:
            r = match_setup('en.1', '2099-10-10', 'Arsenal FC', 'Leeds United FC', d, fetch)
            self.assertEqual(r['status'], 'ok')
            home, away = r['teams']
            self.assertEqual((home['source'], home['formation'], len(home['xi'])), ('confirmed', '4-3-3', 11))
            self.assertEqual(home['xi'][0]['grid'], '1:1')
            self.assertEqual((away['source'], away['formation'], away['played_on']), ('last_match', '5-4-1', '2026-10-03'))
            self.assertEqual(r['unavailable'][0]['reason'], 'Knee Injury')
            self.assertEqual(r['requests_remaining'], '77')
            n = len(calls)
            match_setup('en.1', '2099-10-10', 'Arsenal FC', 'Leeds United FC', d, fetch)
            self.assertEqual(len(calls), n)  # second view is served from cache

    def test_plan_errors_are_reported_not_raised(self):
        fetch, _ = self.fake([('fixtures?', dict(response=[], errors=dict(plan='Free plans do not have access to this season.')))])
        with tempfile.TemporaryDirectory() as d:
            r = match_setup('en.1', '2099-10-10', 'Arsenal FC', 'Leeds United FC', d, fetch)
        self.assertEqual(r['status'], 'error')
        self.assertIn('Free plans', r['reason'])

    def test_budget_is_enforced(self):
        fetch, calls = self.fake([('fixtures?', FIXTURES)])
        with tempfile.TemporaryDirectory() as d:
            import datetime as dt
            from pathlib import Path
            (Path(d) / f'budget-{dt.date.today().isoformat()}.json').write_text(json.dumps(dict(used=DAILY_BUDGET)))
            r = match_setup('en.1', '2099-10-10', 'Arsenal FC', 'Leeds United FC', d, fetch)
        self.assertEqual(r['status'], 'error')
        self.assertIn('budget', r['reason'])
        self.assertEqual(calls, [])

    def test_unconfigured(self):
        with patch.dict('os.environ', {'API_FOOTBALL_KEY': ''}):
            self.assertEqual(match_setup('en.1', '2026-10-10', 'A', 'B')['status'], 'unconfigured')


if __name__ == '__main__':
    unittest.main()
