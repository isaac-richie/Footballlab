"""Book today's football VIP slip on the main bookies ahead of time (run by the daily job).

Booking a 17-pick slip takes about a minute through the booking service, longer than the hosted
site allows for one request, so the morning job books it once and saves the codes in
reports/vip_codes.json. The VIP page shows them instantly; other bookies are booked on request.

    python3 vip_booking.py                 # SportyBet
    python3 vip_booking.py sportybet bet9ja
"""
import datetime as dt
import json
import sys
from pathlib import Path

import bookcodes
from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'reports' / 'vip_codes.json'
DEFAULT = ('sportybet',)


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def today_codes(today=None):
    """{bookmaker: booking} saved for today's slip, or {}."""
    d = load()
    return d.get('bookings', {}) if d.get('date') == (today or dt.date.today().isoformat()) else {}


def nba_codes(day=None):
    """{bookmaker: booking} saved for today's NBA game day (New York date), or {}."""
    import nba_vip
    n = load().get('nba') or {}
    return n.get('bookings', {}) if n.get('date') == (day or nba_vip.game_day().isoformat()) else {}


def run(bookmakers=DEFAULT):
    import app
    import config
    config.load_environment()
    if not bookcodes.configured():
        print(json.dumps(dict(vip_booking='skipped: no MANAGEBETCODES_API_KEY')))
        return
    data = app.load()
    ticket = app.vip_ticket(data, live_scores={})
    legs = [dict(l, sport=l.get('sport', 'football')) for l in ticket['legs'] if l['status'] == 'scheduled']
    today = dt.date.today().isoformat()
    saved = load() if load().get('date') == today else dict(date=today, slip=ticket.get('code'), bookings={})
    for bm in bookmakers:
        if bm in saved['bookings'] or not legs:
            continue
        try:
            r = bookcodes.book(legs, bm)
            saved['bookings'][bm] = dict(r, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'))
        except bookcodes.BookingError as exc:
            saved['bookings'][bm] = dict(error=str(exc), code=None)
    saved['nba'] = book_nba(bookmakers, (load().get('nba') or {}))
    atomic_write(FILE, json.dumps(saved, indent=1))
    print(json.dumps(dict(vip_booking={k: v.get('code') for k, v in saved['bookings'].items()},
                          nba={k: v.get('code') for k, v in saved['nba'].get('bookings', {}).items()})))


def book_nba(bookmakers, old):
    """Book the NBA VIP slip for today's game day; keeps a booking already made for that day."""
    import app
    import nba_app
    import nba_vip
    day = nba_vip.game_day().isoformat()
    out = old if old.get('date') == day else dict(date=day, bookings={})
    try:
        legs = [dict(l, sport='nba') for l in app.nba_vip_ticket(nba_app)['legs'] if l['status'] == 'scheduled']
    except Exception as exc:                       # NBA is an extra: never break the football booking
        print(json.dumps(dict(nba_booking=f'skipped: {exc}'[:200])))
        return out
    for bm in bookmakers:
        if bm in out['bookings'] or not legs:
            continue
        try:
            r = bookcodes.book(legs, bm)
            out['bookings'][bm] = dict(r, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'))
        except bookcodes.BookingError as exc:
            out['bookings'][bm] = dict(error=str(exc), code=None)
    return out


if __name__ == '__main__':
    run(tuple(sys.argv[1:]) or DEFAULT)
