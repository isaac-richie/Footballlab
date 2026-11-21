"""Real bookmaker booking codes, through the Manage Bet Codes API (managebetcodes.app).

Bookmakers have no public booking API. This service books a slip on SportyBet, Bet9ja, 1xBet and
others and returns that bookmaker's own code, and converts a code from one bookmaker to another.

  book(legs, bookmaker)   our picks -> /v1/resolve (team names, market, outcome, line) -> /v1/book
  convert(code, src, dst) /v1/convert

Needs MANAGEBETCODES_API_KEY (server side only; it never reaches the page). A booked or converted
code costs 2 credits, so each slip's code is cached per bookmaker for as long as it can be used.
"""
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = 'https://api.managebetcodes.app/v1'
# The bookmakers we offer, as the API names them: (key, label).
BOOKMAKERS = (('sportybet', 'SportyBet'), ('bet9ja', 'Bet9ja'), ('onexbet', '1xBet'), ('msport', 'MSport'),
              ('betking', 'BetKing'), ('football.com', 'Football.com'), ('betway', 'Betway'),
              ('sportybet_gh', 'SportyBet Ghana'), ('sportybet_ke', 'SportyBet Kenya'))
KEYS = {k for k, _ in BOOKMAKERS}
CODE_TTL = 6 * 3600
_cache, _lock = {}, threading.Lock()


class BookingError(Exception):
    def __init__(self, message, code='book_failed', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def api_key():
    return os.environ.get('MANAGEBETCODES_API_KEY', '').strip()


def configured():
    return bool(api_key())


def to_pick(leg):
    """One of our picks as the API's market / outcome / line, or None if we can't express it."""
    home, away, sel, m = leg['home'], leg['away'], leg['selection'], leg['market']
    base = dict(home_team=home, away_team=away)
    if leg.get('league'):
        base['league'] = leg['league']
    if leg.get('kickoff'):
        base['kickoff'] = leg['kickoff']
    if leg.get('sport') == 'nba':
        if m == 'total' and leg.get('line') is not None:
            return dict(base, market='Basketball Total', outcome=(leg.get('side') or sel.split()[0]).lower(), line=str(leg['line']))
        if m in ('winner', 'moneyline'):
            team = leg.get('team') or sel.replace(' to win', '')
            return dict(base, market='Winner (incl. Overtime)', outcome='home' if team == home else 'away')
        return None
    if m == '1x2':
        return dict(base, market='1X2', outcome='draw' if sel == 'Draw' else 'home' if sel == f'{home} win' else 'away')
    if m == 'dc':
        outcome = '1X' if sel == f'{home} or draw' else '2X' if sel == f'{away} or draw' else '12'
        return dict(base, market='Double Chance', outcome=outcome)
    if m.startswith('ou'):
        side, line = sel.split()[0].lower(), sel.split()[-1]
        return dict(base, market='Over/Under', outcome=side, line=line)
    if m == 'btts':
        return dict(base, market='Both Teams To Score', outcome='yes' if sel == 'Both teams score' else 'no')
    return None


def _call(path, body, key, fetch=None):
    data = json.dumps(body).encode()
    req = Request(API + path, data=data, method='POST',
                  headers={'X-API-Key': key, 'Content-Type': 'application/json', 'User-Agent': 'fairline'})
    if fetch:
        return fetch(path, body)
    try:
        with urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except HTTPError as e:
        try:
            err = json.loads(e.read()).get('error') or {}
        except ValueError:
            err = {}
        raise BookingError(err.get('message') or f'Booking service error {e.code}', err.get('code') or 'book_failed',
                           502 if e.code >= 500 else 400) from None
    except (URLError, TimeoutError, OSError):
        raise BookingError('The booking service did not answer. Try again in a minute.', 'unavailable', 502) from None


def book(legs, bookmaker, key=None, fetch=None, now=None):
    """Book our picks on `bookmaker`. Returns {code, bookmaker, booked, total, missing[], total_odds, verified}.

    Picks the bookmaker doesn't offer are left out and listed in `missing` (strict=False), so one
    missing game doesn't cost the whole code."""
    key = key or api_key()
    if not key:
        raise BookingError('Booking codes are not switched on yet.', 'not_configured', 503)
    if bookmaker not in KEYS:
        raise BookingError('Choose one of the listed bookmakers.', 'unsupported_bookmaker')
    now = now or time.time()
    picks, unmapped = [], []
    for leg in legs[:50]:
        p = to_pick(leg)
        (picks.append((leg, p)) if p else unmapped.append(leg))
    if not picks:
        raise BookingError('None of these picks can be booked.', 'nothing_to_book')
    cache_key = (bookmaker, tuple(sorted(json.dumps(p, sort_keys=True) for _, p in picks)))
    with _lock:
        hit = _cache.get(cache_key)
        if hit and now - hit[0] < CODE_TTL:
            return dict(hit[1], cached=True)
    res = _call('/resolve', dict(bookmaker=bookmaker, picks=[p for _, p in picks], strict=False, accept_odds_change=True), key, fetch)
    rows = res.get('picks') or []
    ok = [r for r in rows if r.get('status') == 'resolved' and r.get('bookable', True)]
    missing = [dict(home=picks[r['index']][0]['home'], away=picks[r['index']][0]['away'], selection=picks[r['index']][0]['selection'],
                    reason=r.get('status')) for r in rows if r not in ok and isinstance(r.get('index'), int) and r['index'] < len(picks)]
    missing += [dict(home=l['home'], away=l['away'], selection=l['selection'], reason='market_missing') for l in unmapped]
    if not ok or not res.get('plan_id'):
        raise BookingError(f"{dict(BOOKMAKERS)[bookmaker]} doesn't list these games yet.", 'not_found')
    out = _call('/book', dict(bookmaker=bookmaker, plan_id=res['plan_id'], strict=False, accept_odds_change=True), key, fetch)
    if not out.get('code'):
        raise BookingError('The bookmaker did not return a code. Try again.', 'book_failed', 502)
    result = dict(code=out['code'], bookmaker=bookmaker, bookmaker_name=dict(BOOKMAKERS)[bookmaker],
                  booked=len(out.get('picks') or ok), total=len(legs), missing=missing,
                  total_odds=out.get('total_odds'), verified=bool(out.get('verified')))
    with _lock:
        _cache[cache_key] = (now, result)
    return result


def convert(code, source, target, key=None, fetch=None):
    """Convert a booking code between bookmakers. Returns {code, from, to, converted, original, partial}."""
    key = key or api_key()
    if not key:
        raise BookingError('Code conversion is not switched on yet.', 'not_configured', 503)
    code = (code or '').strip().upper()
    if not code or len(code) > 24 or not code.replace('-', '').isalnum():
        raise BookingError('Enter a booking code.', 'invalid_code')
    if source not in KEYS or target not in KEYS or source == target:
        raise BookingError('Choose two different bookmakers.', 'unsupported_bookmaker')
    out = _call('/convert', dict(code=code, **{'from': source, 'to': target}), key, fetch)
    tgt = out.get('target') or {}
    if not tgt.get('code'):
        raise BookingError('That code could not be converted.', 'convert_failed')
    counts = out.get('counts') or {}
    return dict(code=tgt['code'], **{'from': source, 'to': target}, to_name=dict(BOOKMAKERS)[target],
                converted=counts.get('converted'), original=counts.get('original'), partial=bool(out.get('partial')))
