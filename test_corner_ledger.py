import unittest
from unittest import mock

import corner_ledger as L


def fc(under):
    return dict(status='ok', expected_total=9.5, lines=[dict(line=k, under=u, over=1 - u) for k, u in zip((8.5, 9.5, 10.5, 11.5), under)])


class CornerLedger(unittest.TestCase):
    def test_stronger_tested_line_first(self):
        self.assertEqual(L.choose(fc((.3, .45, .66, .78)))['line'], 10.5)     # Under 10.5 at 65%+ beats Under 11.5
        self.assertEqual(L.choose(fc((.3, .45, .60, .72)))['line'], 11.5)
        self.assertIsNone(L.choose(fc((.3, .45, .60, .68))))
        self.assertIsNone(L.choose(dict(status='unavailable')))

    def test_grading_from_corner_counts(self):
        store = dict(picks={'k': dict(league_id='en.1', date='2026-11-21', home='A FC', away='B FC', side='under', line=10.5,
                                      probability=.66, saved_at='2026-11-20T08:00:00')})
        rows = [dict(league_id='en.1', date='2026-11-21', home='A', away='B', corners=[6, 3], goals=[1, 0])]
        with mock.patch('corners.load', return_value=rows), \
                mock.patch('corners.name_map', return_value={('en.1', 'A'): 'A FC', ('en.1', 'B'): 'B FC'}):
            self.assertEqual(L.grade(dict(matches=[]), store), 1)
        p = store['picks']['k']
        self.assertEqual((p['corners'], p['won']), (9, True))
        s = L.summary(store)
        self.assertEqual((s['settled'], s['won'], s['by_line']['10.5']['picks']), (1, 1, 1))


if __name__ == '__main__':
    unittest.main()
