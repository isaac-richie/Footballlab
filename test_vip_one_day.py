import datetime as dt
import unittest
from unittest import mock

import app


def leg(date, home, p=.8):
    fx = f'en.1|{date}|{home}|X'
    return dict(id=fx + '|ou15|Over 1.5', fixture=fx, league_id='en.1', date=date, home=home, away='X',
                market='ou15', market_label='Goals', selection='Over 1.5', probability=p, fair_odds=1 / p, source='model')


class VipOneDayTests(unittest.TestCase):
    def test_slip_keeps_only_todays_games(self):
        today = dt.date.today().isoformat()
        later = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        pool = [leg(today, 'A'), leg(later, 'B', .9), leg(today, 'C')]
        with mock.patch.object(app, 'parlay_candidates', return_value=pool), \
             mock.patch.object(app, 'league_fresh', return_value=True), \
             mock.patch.object(app, 'last_five', return_value={}):
            slip = app.vip_slip({'matches': []})
        self.assertTrue(slip['legs'])
        self.assertEqual({l['date'] for l in slip['legs']}, {today})


if __name__ == '__main__':
    unittest.main()
