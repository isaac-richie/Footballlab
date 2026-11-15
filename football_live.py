"""Live football scores for the board, from API-Football (free plan: 100 requests a day).

One request (`fixtures?date=<today>`) returns every match of the day worldwide with
its status, minute and score; only our leagues are kept and their team names are
matched to ours. The answer is cached in the process and at the CDN: 10 minutes
from 10:00 to 23:00 UTC (when nearly all our matches are played), an hour otherwise,
so a day costs at most about 90 requests. Grading still comes from the result feeds.
"""
import datetime as dt
import json
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from live_odds import similarity
from lineups import LEAGUE_IDS

API = 'https://v3.football.api-sports.io/fixtures'
IDS = dict(LEAGUE_IDS, **{'nl.1': 88, 'pt.1': 94, 'tr.1': 203, 'sco.1': 179, 'be.1': 144, 'sa.1': 307, 'ucl': 2})
LIVE = {'1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE', 'INT', 'SUSP'}
DONE = {'FT', 'AET', 'PEN'}
_cache = dict(at=0.0, ttl=0, value=None)
_lock = threading.Lock()


def ttl(now):
    return 600 if 10 <= now.hour < 23 else 3600


def _pair(date, home, away, fixtures):
    """Our (home, away) for an API fixture: the scheduled match that day whose names fit best."""
    day = dt.date.fromisoformat(date)
    near = {(day + dt.timedelta(days=d)).isoformat() for d in (-1, 0, 1)}
    scored = sorted((((similarity(home, h) + similarity(away, a)) / 2, (d, h, a)) for d, h, a in fixtures if d in near),
                    reverse=True)
    if not scored or scored[0][0] < .45 or (len(scored) > 1 and scored[1][0] > scored[0][0] - .1):
        return None
    return scored[0][1]


def snapshot(fixtures, schedule):
    """{"date|home|away" in our names: row} for matches that have started.

    schedule: {league_id: [(date, home, away), ...]} of our own fixtures."""
    by_id = {v: k for k, v in IDS.items()}
    out = {}
    for f in fixtures:
        lg = by_id.get((f.get('league') or {}).get('id'))
        st = ((f.get('fixture') or {}).get('status') or {})
        code = st.get('short')
        if not lg or code not in LIVE | DONE:
            continue
        date = (f['fixture'].get('date') or '')[:10]
        match = _pair(date, f['teams']['home']['name'], f['teams']['away']['name'], schedule.get(lg) or [])
        if not match:
            continue
        g = f.get('goals') or {}
        state = 'final' if code in DONE else 'live'
        clock = 'FT' if state == 'final' else 'HT' if code == 'HT' else f"{st.get('elapsed') or ''}'" + (f"+{st['extra']}" if st.get('extra') else '')
        out['|'.join(match)] = dict(status=state, score=[g.get('home') or 0, g.get('away') or 0], clock=clock)
    return out


def live(schedule, key=None, now=None):
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return dict(games={}, error='no key')
    now = now or dt.datetime.now(dt.timezone.utc)
    with _lock:
        if _cache['value'] is not None and time.monotonic() - _cache['at'] < _cache['ttl']:
            return _cache['value']
        try:
            url = API + '?' + urlencode(dict(date=now.date().isoformat(), timezone='UTC'))
            with urlopen(Request(url, headers={'x-apisports-key': key, 'User-Agent': 'football-lab'}), timeout=20) as r:
                body = json.loads(r.read())
            if body.get('errors'):
                raise RuntimeError('API-Football refused the request')
            value = dict(games=snapshot(body.get('response') or [], schedule), fetched_at=now.isoformat(), ttl=ttl(now))
        except Exception as exc:
            value = _cache['value'] or dict(games={}, error=str(exc).replace(key, '***')[:200])
        _cache.update(at=time.monotonic(), ttl=ttl(now), value=value)
        return value
