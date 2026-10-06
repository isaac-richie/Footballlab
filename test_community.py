import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'community'))
import sync  # noqa: E402


def match(day, home, away, goals, league='en.1'):
    return dict(date=day.isoformat(), home=home, away=away, goals=goals, league_id=league, season='2026-27')


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 10, 6)
        history = [match(self.today - dt.timedelta(days=20 + i % 300), h, a, [i % 3, (i + 1) % 2])
                   for i in range(240) for h, a in [('A', 'B') if i % 2 else ('B', 'A')]]
        self.data = dict(fetched_at='t', matches=history + [
            match(self.today + dt.timedelta(days=3), 'A', 'B', None),
            match(self.today - dt.timedelta(days=2), 'B', 'A', [2, 1]),
            match(self.today - dt.timedelta(days=5), 'A', 'B', None),       # unplayed: postponed
            match(self.today + dt.timedelta(days=3), 'X', 'Y', None, 'it.2'),  # Serie B never published
        ])

    def test_rows(self):
        with patch('app.market_prices', return_value=None) as prices:
            upcoming, results = sync.build_rows(self.data, self.today)
        prices.assert_called()  # fixture_rates may look, but sync must use model rates only
        self.assertEqual(len(upcoming), 1)
        u = upcoming[0]
        self.assertEqual(u['status'], 'scheduled')
        self.assertAlmostEqual(u['lab_home'] + u['lab_draw'] + u['lab_away'], 1, places=3)
        self.assertNotIn('it.2', {r['league_id'] for r in upcoming + results})
        statuses = sorted(r['status'] for r in results)
        self.assertEqual(statuses, ['finished', 'postponed'])
        for r in results:
            self.assertNotIn('lab_home', r)   # results never overwrite the frozen forecast
            self.assertNotIn('kickoff_at', r)
        self.assertEqual(len({tuple(sorted(r)) for r in upcoming}), 1)  # uniform keys for bulk upsert
        self.assertEqual(len({tuple(sorted(r)) for r in results}), 1)

    def test_lab_ignores_bookmaker_prices(self):
        fake = dict(source='entered', label='x', h2h=[1.1, 9, 20], ou25=None)
        with patch('app.market_prices', return_value=fake):
            with_odds, _ = sync.build_rows(self.data, self.today)
        with patch('app.market_prices', return_value=None):
            without, _ = sync.build_rows(self.data, self.today)
        self.assertEqual(with_odds[0]['lab_home'], without[0]['lab_home'])


class BackupTests(unittest.TestCase):
    def test_pages_until_short_page_with_stable_order(self):
        import backup
        pages = [[{'i': n} for n in range(1000)], [{'i': n} for n in range(1000, 1450)]]
        seen = []
        def fetch(request):
            seen.append((request.full_url, request.get_header('Range')))
            return pages[len(seen) - 1]
        rows = backup.export('https://x.supabase.co', 'k', 'predictions', 'user_id,fixture_id', fetch)
        self.assertEqual(len(rows), 1450)
        self.assertEqual([r for _, r in seen], ['0-999', '1000-1999'])
        self.assertTrue(all('order=user_id,fixture_id' in u for u, _ in seen))


if __name__ == '__main__':
    unittest.main()
