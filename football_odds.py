"""Best bookmaker prices for our football picks (API-Football Pro, pre-match odds).

For each (league, date) two requests fetch every bookmaker's prices and the fixture list (odds
carry only a fixture id). We keep the best price across bookmakers for the selections we pick:
Over/Under 1.5, 2.5, 3.5 and the match winner. Bookmaker names are not shown on the site.
Cached for 30 minutes in the process (and at the CDN by the routes that use it).
"""
import datetime as dt
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

from football_live import IDS, _pair

API = 'https://v3.football.api-sports.io/'
TTL = 1800
_cache, _lock = {}, threading.Lock()


def _get(path, params, key):
    req = Request(API + path + '?' + urlencode(params), headers={'x-apisports-key': key, 'User-Agent': 'football-lab'})
    with urlopen(req, timeout=25) as r:
        body = json.loads(r.read())
    if body.get('errors'):
        raise RuntimeError('API-Football refused the request')
    return body.get('response') or [], (body.get('paging') or {}).get('total', 1)


def _season(date):
    d = dt.date.fromisoformat(date)
    return d.year if d.month >= 7 else d.year - 1


def best_prices(league_id, date, schedule, key=None):
    """{(date, our home, our away): {selection: best price}} for one league and day."""
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key or league_id not in IDS:
        return {}
    ck = (league_id, date)
    with _lock:
        hit = _cache.get(ck)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
    out = {}
    try:
        params = dict(league=IDS[league_id], season=_season(date), date=date)
        fixtures, _ = _get('fixtures', params, key)
        names = {f['fixture']['id']: (f['teams']['home']['name'], f['teams']['away']['name']) for f in fixtures}
        page, pages = 1, 1
        while page <= pages and page <= 3:
            odds, pages = _get('odds', dict(params, page=page), key)
            for f in odds:
                fid = f['fixture']['id']
                if fid not in names:
                    continue
                ours = _pair(date, *names[fid], schedule)
                if not ours:
                    continue
                best = {}
                for b in f.get('bookmakers') or []:
                    for bet in b.get('bets') or []:
                        if bet['id'] not in (1, 5):
                            continue
                        for v in bet.get('values') or []:
                            sel = {'Home': 'home', 'Away': 'away', 'Draw': 'draw'}.get(v['value'], v['value']) if bet['id'] == 1 else v['value']
                            try:
                                price = float(v['odd'])
                            except (TypeError, ValueError):
                                continue
                            if price > best.get(sel, 0):
                                best[sel] = price
                out[ours] = best
            page += 1
    except Exception:
        out = (_cache.get(ck) or (0, {}))[1]          # keep the last good answer
    with _lock:
        _cache[ck] = (time.monotonic(), out)
    return out


def price_for(leg, prices):
    """The best price for one of our picks (football VIP leg shape), or None."""
    p = prices.get((leg['date'], leg['home'], leg['away'])) or {}
    sel = leg['selection']
    if leg.get('market') == '1x2':
        sel = 'home' if sel == f"{leg['home']} win" else 'away' if sel == f"{leg['away']} win" else 'draw'
    return p.get(sel)


# ---------- Daily snapshot for the VIP slip ----------

from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'reports' / 'vip_odds.json'


def leg_key(leg):
    return '|'.join((leg['date'], leg['home'], leg['away'], leg['selection']))


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return dict(prices={})


def snapshot(data, legs, schedule_fn, now=None):
    """Best prices for these VIP legs. The first price seen for a pick is kept (the price when we
    posted it); the latest price is updated on each run until kickoff."""
    from quality import atomic_write
    now = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    store = load()
    schedule = schedule_fn(data, days=4)
    seen, found = {}, 0
    for leg in legs:
        k = (leg['league_id'], leg['date'])
        if k not in seen:
            seen[k] = best_prices(leg['league_id'], leg['date'], schedule.get(leg['league_id'], []))
        price = price_for(leg, seen[k])
        if not price:
            continue
        found += 1
        row = store['prices'].setdefault(leg_key(leg), dict(first=price, first_at=now))
        row.update(latest=price, latest_at=now)
    store['updated_at'] = now
    atomic_write(FILE, json.dumps(store, indent=0))
    return dict(legs=len(legs), priced=found, league_days=len(seen))


if __name__ == '__main__':
    import config
    config.load_environment()
    import app
    import record
    data = app.load()
    today = dt.date.today().isoformat()
    legs = app.vip_slip(data, 17)['legs']
    have = {leg_key(l) for l in legs}
    for day in record.vip_ledger(max_days=3)['days']:            # the saved slips too, for games still to play
        legs += [p for p in day['picks'] if p['date'] >= today and p['status'] == 'pending' and leg_key(p) not in have]
        have |= {leg_key(p) for p in day['picks']}
    print(json.dumps(dict(vip_odds=snapshot(data, legs, app.football_schedule))))
