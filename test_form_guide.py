import unittest

from analysis import form_guide


def m(date, h, a, g, ht=None, lg='en.1'):
    season = '2026-27' if date >= '2026-07-01' else '2024-25'
    return dict(date=date, home=h, away=a, goals=g, ht=ht, league_id=lg, league='England — Premier League', season=season)


GAMES = [m('2026-08-20', 'A', 'B', [2, 1], [1, 0]), m('2026-09-10', 'B', 'A', [0, 0], [0, 0]), m('2026-09-20', 'A', 'C', [4, 0], [1, 0]),
         m('2026-10-01', 'C', 'B', [1, 3], [1, 1]), m('2025-03-01', 'A', 'B', [1, 2], [0, 1], lg='en.1'), m('2026-12-01', 'A', 'B', [9, 9])]


class FormGuideTests(unittest.TestCase):
    def test_head_to_head_counts_every_meeting_before_the_date(self):
        g = form_guide(GAMES, 'en.1', 'A', 'B', '2026-11-20')
        self.assertEqual(len(g['h2h']['games']), 3)                    # the December game is after asof
        self.assertEqual(g['h2h']['wins'], dict(home=1, draw=1, away=1))
        self.assertEqual(g['h2h']['games'][0]['league'], 'Premier League')

    def test_season_table_and_halves(self):
        a, b = form_guide(GAMES, 'en.1', 'A', 'B', '2026-11-20')['teams']
        self.assertEqual((a['played'], a['won'], a['drawn'], a['lost'], a['points']), (3, 2, 1, 0, 7))
        self.assertEqual(a['biggest_win'], '4-0')
        self.assertEqual(a['clean_sheets'], 2)
        self.assertEqual(a['streak'], 'W1')
        self.assertEqual(b['streak'], 'W1')
        self.assertEqual(a['halves']['scored'], [2, 5])                # first halves 0+1+0+1, second 1+1+0+3


if __name__ == '__main__':
    unittest.main()
