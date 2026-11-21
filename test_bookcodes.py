import unittest

import bookcodes as B


def leg(sel, market, home='Arsenal FC', away='Chelsea FC', **kw):
    return dict(home=home, away=away, selection=sel, market=market, league='Premier League', kickoff='2026-11-21T15:00:00Z', **kw)


class MapTests(unittest.TestCase):
    def test_football_markets(self):
        self.assertEqual(B.to_pick(leg('Arsenal FC or draw', 'dc'))['outcome'], '1X')
        self.assertEqual(B.to_pick(leg('Chelsea FC or draw', 'dc'))['outcome'], '2X')
        self.assertEqual(B.to_pick(leg('Arsenal FC or Chelsea FC', 'dc'))['outcome'], '12')
        p = B.to_pick(leg('Over 1.5', 'ou15'))
        self.assertEqual((p['market'], p['outcome'], p['line']), ('Over/Under', 'over', '1.5'))
        self.assertEqual(B.to_pick(leg('Under 3.5', 'ou35'))['outcome'], 'under')
        self.assertEqual(B.to_pick(leg('Chelsea FC win', '1x2'))['outcome'], 'away')
        self.assertEqual(B.to_pick(leg('Draw', '1x2'))['outcome'], 'draw')
        self.assertEqual(B.to_pick(leg('Not both teams score', 'btts'))['outcome'], 'no')

    def test_nba(self):
        p = B.to_pick(leg('Under 228.5 points', 'total', sport='nba', side='under', line=228.5))
        self.assertEqual((p['market'], p['outcome'], p['line']), ('Basketball Total', 'under', '228.5'))
        self.assertEqual(B.to_pick(leg('Chelsea FC to win', 'winner', sport='nba', team='Chelsea FC'))['outcome'], 'away')


class FakeApi:
    def __init__(self, resolve_status=('resolved', 'resolved')):
        self.calls, self.status = [], resolve_status

    def __call__(self, path, body):
        self.calls.append(path)
        if path == '/events/search':
            return dict(results=[dict(events=[dict(event_id=f"sr:{q['q']}", home=q['q'].split(' vs ')[0], away=q['q'].split(' vs ')[1],
                                                   confidence='exact')]) for q in body['queries']])
        if path == '/resolve':
            return dict(plan_id='plan_1', picks=[dict(index=i, status=s, bookable=True) for i, s in enumerate(self.status)])
        if path == '/book':
            return dict(code='AB12CD', verified=True, total_odds='2.10', picks=[1] * self.status.count('resolved'))
        if path == '/convert':
            return dict(target=dict(code='3XYZ123'), counts=dict(original=3, converted=3), partial=False)


class BookTests(unittest.TestCase):
    def setUp(self):
        B._cache.clear()

    def test_book_returns_code_and_lists_missing_games(self):
        api = FakeApi(('resolved', 'not_found'))
        r = B.book([leg('Over 1.5', 'ou15'), leg('Draw', '1x2', home='X', away='Y')], 'sportybet', key='k', fetch=api, now=1)
        self.assertEqual((r['code'], r['booked'], r['total']), ('AB12CD', 1, 2))
        self.assertEqual(r['missing'][0]['home'], 'X')
        self.assertEqual([c for c in api.calls if c != '/events/search'], ['/resolve', '/book'])

    def test_same_slip_is_cached_per_bookmaker(self):
        api = FakeApi(('resolved',))
        B.book([leg('Over 1.5', 'ou15')], 'sportybet', key='k', fetch=api, now=1)
        r = B.book([leg('Over 1.5', 'ou15')], 'sportybet', key='k', fetch=api, now=2)
        self.assertTrue(r['cached'])
        self.assertEqual(api.calls.count('/book'), 1)
        B.book([leg('Over 1.5', 'ou15')], 'bet9ja', key='k', fetch=api, now=3)
        self.assertEqual(api.calls.count('/book'), 2)

    def test_errors(self):
        with self.assertRaises(B.BookingError) as e:
            B.book([leg('Over 1.5', 'ou15')], 'sportybet', key='', fetch=FakeApi())
        self.assertEqual(e.exception.code, 'not_configured')
        with self.assertRaises(B.BookingError):
            B.book([leg('Over 1.5', 'ou15')], 'nobody', key='k', fetch=FakeApi())
        with self.assertRaises(B.BookingError) as e:
            B.book([leg('Over 1.5', 'ou15')], 'sportybet', key='k', fetch=FakeApi(('not_found',)), now=1)
        self.assertEqual(e.exception.code, 'not_found')

    def test_convert(self):
        r = B.convert(' ab12cd ', 'sportybet', 'bet9ja', key='k', fetch=FakeApi())
        self.assertEqual((r['code'], r['to_name'], r['converted']), ('3XYZ123', 'Bet9ja', 3))
        with self.assertRaises(B.BookingError):
            B.convert('AB12CD', 'sportybet', 'sportybet', key='k', fetch=FakeApi())
        with self.assertRaises(B.BookingError):
            B.convert('bad code!', 'sportybet', 'bet9ja', key='k', fetch=FakeApi())


class ChooseEventTests(unittest.TestCase):
    def test_kickoff_and_names_pick_the_right_game(self):
        leg = dict(home='Feyenoord Rotterdam', away='SBV Excelsior', kickoff='2026-11-21T17:45:00Z')
        wrong = dict(event_id='x', home='Jong Sparta Rotterdam', away='Quick Boys', kickoff='2026-11-21T14:00:00+00:00', confidence='fuzzy')
        right = dict(event_id='y', home='Feyenoord', away='Excelsior Rotterdam', kickoff='2026-11-21T17:45:00+00:00', confidence='exact')
        self.assertEqual(B.choose_event(leg, [wrong, right])['event_id'], 'y')
        self.assertIsNone(B.choose_event(leg, [wrong]))


if __name__ == '__main__':
    unittest.main()
