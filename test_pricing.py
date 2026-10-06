import os
import unittest
from unittest.mock import patch

from implied import implied_rates
from live_odds import match_events, similarity, summarize_event
from markets import score_matrix
from odds_data import name_map, no_vig, parse_csv
from count_markets import count_markets
from config import load_environment


def targets(lh, la, rho=0.0):
    g = score_matrix(lh, la, rho)
    return ([sum(p for (h, a), p in g.items() if h > a), sum(p for (h, a), p in g.items() if h == a),
             sum(p for (h, a), p in g.items() if h < a)], sum(p for (h, a), p in g.items() if h + a > 2))


class PricingTests(unittest.TestCase):
    def test_implied_rates_recover_known_rates(self):
        for lh, la, rho in ((1.7, 0.9, -.05), (1.1, 1.4, 0.0), (2.6, 0.6, -.1)):
            probs, over = targets(lh, la, rho)
            mh, ma, err = implied_rates(probs, over, rho)
            self.assertAlmostEqual(mh, lh, places=3)
            self.assertAlmostEqual(ma, la, places=3)
            self.assertLess(err, 1e-5)

    def test_no_vig(self):
        self.assertEqual([round(x, 6) for x in no_vig([2, 4, 4])], [.5, .25, .25])
        self.assertAlmostEqual(sum(no_vig([1.9, 3.5, 4.4])), 1)

    def test_parse_csv_validates_fields(self):
        raw = ('﻿Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,HC,AC,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5,AHh\n'
               'E0,12/08/2025,Arsenal,Chelsea,2,1,3,0,7,4,1.8,3.9,4.5,1.7,2.2,-0.75\n'
               'E0,13/08/25,Spurs,Spurs,1,1,0,0,,,,,,,,\n'
               'E0,14/08/2025,Leeds,Everton,,,,,,,0.9,3,3,,,0.3\n').encode('utf-8')
        rows = parse_csv(raw, 'en.1', '2025-26')
        self.assertEqual(len(rows), 2)  # same-team row rejected
        a, b = rows
        self.assertEqual(a['date'], '2025-08-12')
        self.assertIsNone(a['ht'])  # half-time above full-time is dropped
        self.assertEqual(a['stats']['corners'], [7, 4])
        self.assertEqual(a['odds']['ah_line_open'], -.75)
        self.assertNotIn('avg_open', b['odds'])  # odds <= 1 invalidate the group
        self.assertNotIn('ah_line_open', b['odds'])  # not a quarter line

    def test_name_map_votes_and_refuses_collisions(self):
        matches, records = [], []
        for day in range(1, 8):
            date = f'2025-01-{day:02d}'
            matches.append(dict(league_id='en.1', date=date, home='Arsenal FC', away='Chelsea FC', goals=[day % 3, 1]))
            records.append(dict(league_id='en.1', date=date, fd_home='Arsenal', fd_away='Chelsea', goals=[day % 3, 1]))
        mapping, unresolved = name_map(records, matches)
        self.assertEqual(mapping[('en.1', 'Arsenal')], 'Arsenal FC')
        self.assertEqual(mapping[('en.1', 'Chelsea')], 'Chelsea FC')
        self.assertEqual(unresolved, [])

    def test_live_event_matching(self):
        self.assertLess(similarity('Real Madrid', 'Real Betis Balompié'), .6)
        fixtures = [dict(date='2026-10-17', home='Real Madrid CF', away='Club Atlético de Madrid'),
                    dict(date='2026-10-17', home='Real Betis Balompié', away='Sevilla FC')]
        event = dict(id='x', commence_time='2026-10-17T19:00:00Z', home_team='Real Madrid', away_team='Atletico Madrid',
                     bookmakers=[dict(title='A', markets=[dict(key='h2h', outcomes=[
                         dict(name='Real Madrid', price=1.9), dict(name='Draw', price=3.6), dict(name='Atletico Madrid', price=4.2)]),
                         dict(key='totals', outcomes=[dict(name='Over', price=1.8, point=2.5), dict(name='Under', price=2.0, point=2.5)])]),
                                 dict(title='B', markets=[dict(key='h2h', outcomes=[
                         dict(name='Real Madrid', price=1.95), dict(name='Draw', price=3.5), dict(name='Atletico Madrid', price=4.0)])])])
        matched = match_events([event], fixtures)
        self.assertEqual(list(matched), [('2026-10-17', 'Real Madrid CF', 'Club Atlético de Madrid')])
        odds = matched[('2026-10-17', 'Real Madrid CF', 'Club Atlético de Madrid')]
        self.assertEqual(odds['h2h']['home']['best'], 1.95)
        self.assertEqual(odds['h2h']['home']['best_book'], 'B')
        self.assertEqual(odds['totals']['2.5']['over']['best'], 1.8)
        self.assertIsNone(summarize_event(dict(home_team='a', away_team='b', bookmakers=[]))['h2h'])

    def test_count_markets_use_only_earlier_matches(self):
        rows, market = [], {}
        for i in range(250):
            date = f'2025-{1 + i // 28:02d}-{1 + i % 28:02d}'
            rows.append(dict(league_id='en.1', date=date, home='A', away='B', goals=[1, 1]))
            market[('en.1', date, 'A', 'B')] = dict(stats=dict(corners=[6, 4], yellow_cards=[2, 1], red_cards=[0, 0],
                                                              shots_on_target=[5, 3]))
        result = count_markets(rows, market, 'en.1', 'A', 'B', '2025-12-31')
        self.assertEqual(result['markets']['corners']['totals']['9.5'], 1.0)
        self.assertEqual(result['markets']['cards']['league_average'], 3)
        self.assertEqual(result['markets']['corners']['teams']['home']['average_for'], 6)
        self.assertIn('shots_on_target', result['markets'])
        thin = count_markets(rows[:50], market, 'en.1', 'A', 'B', '2025-12-31')
        self.assertEqual(thin['markets'], {})

    def test_odds_key_is_allowed_in_env(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text('ODDS_API_KEY=abc\n')
            load_environment(path)
            self.assertEqual(os.environ['ODDS_API_KEY'], 'abc')


class PredictPricingTests(unittest.TestCase):
    def test_entered_odds_drive_pricing_and_model_view_is_kept(self):
        from app import predict
        rows = [dict(date=f'2024-{1 + i // 28:02d}-{1 + i % 28:02d}', home=h, away=a, goals=[1 + i % 2, i % 3],
                     league_id='en.1', season='2024-25') for i in range(200) for h, a in [('A', 'B') if i % 2 else ('B', 'A')]]
        data = dict(matches=rows)
        request = dict(home='A', away='B', date='2025-02-01', league_id='en.1', odds=['1.5', '4.5', '7'], ou_odds=['1.8', '2.05'])
        r = predict(data, request)
        self.assertEqual(r['pricing']['source'], 'entered')
        fair = no_vig([1.5, 4.5, 7])
        self.assertAlmostEqual(r['probabilities'][0], fair[0], delta=.02)
        self.assertNotAlmostEqual(r['model_view']['probabilities'][0], r['probabilities'][0], places=2)
        self.assertEqual(predict(data, dict(request, odds=None, ou_odds=None))['pricing']['source'], 'model')


if __name__ == '__main__':
    unittest.main()
