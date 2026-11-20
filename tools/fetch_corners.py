"""Download match statistics (corners, shots, cards) from API-Football for corner-model research.

One request lists a league season's finished games; then `fixtures?ids=` returns twenty games
at a time with their statistics, so three seasons of nine leagues cost about 430 requests.
Resumable: games already saved are skipped. Results stay in reports/cache (git-ignored):
API-Football's data is for showing our own forecasts, not for redistribution.

    python3 tools/fetch_corners.py              # 2024-25, 2025-26 and 2026-27 to date
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from football_live import IDS  # noqa: E402
from quality import atomic_write  # noqa: E402

OUT = ROOT / 'reports' / 'cache' / 'match_stats.json'
API = 'https://v3.football.api-sports.io/'
LEAGUES = ('en.1', 'es.1', 'it.1', 'de.1', 'fr.1', 'it.2', 'de.2', 'nl.1', 'pt.1')
SEASONS = (2024, 2025, 2026)
KEEP = {'Corner Kicks': 'corners', 'Total Shots': 'shots', 'Shots on Goal': 'shots_on_target', 'Yellow Cards': 'yellow',
        'Red Cards': 'red', 'Fouls': 'fouls', 'Ball Possession': 'possession', 'Shots insidebox': 'shots_inside'}
FLOOR = 1000            # stop when the day's remaining requests fall to this, so the site keeps working
_left = [None]


def get(path, params, key):
    time.sleep(.35)                                   # well under the plan's 300 a minute
    req = Request(API + path + '?' + urlencode(params), headers={'x-apisports-key': key, 'User-Agent': 'football-lab research'})
    with urlopen(req, timeout=40) as r:
        _left[0] = int(r.headers.get('x-ratelimit-requests-remaining') or 10 ** 6)
        body = json.loads(r.read())
    if body.get('errors'):
        raise RuntimeError(f'API-Football: {body["errors"]}')
    return body.get('response') or []


def num(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.rstrip('%')
    try:
        return float(v)
    except ValueError:
        return None


def main():
    config.load_environment()
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        sys.exit('Add API_FOOTBALL_KEY to .env')
    try:
        store = json.loads(OUT.read_text())
    except (OSError, ValueError):
        store = {}
    for league_id in LEAGUES:
        for season in SEASONS:
            games = get('fixtures', dict(league=IDS[league_id], season=season, status='FT-AET-PEN'), key)
            todo = [g['fixture']['id'] for g in games if str(g['fixture']['id']) not in store]
            print(f'{league_id} {season}: {len(games)} finished, {len(todo)} to fetch', flush=True)
            for i in range(0, len(todo), 20):
                if _left[0] is not None and _left[0] <= FLOOR:
                    atomic_write(OUT, json.dumps(store))
                    print(f'Stopped: {_left[0]} requests left today. Run again tomorrow to finish.')
                    return
                for f in get('fixtures', dict(ids='-'.join(map(str, todo[i:i + 20]))), key):
                    teams = {t['team']['id']: {KEEP[s['type']]: num(s['value']) for s in t.get('statistics') or [] if s['type'] in KEEP}
                             for t in f.get('statistics') or []}
                    h, a = f['teams']['home'], f['teams']['away']
                    store[str(f['fixture']['id'])] = dict(league_id=league_id, season=season, date=f['fixture']['date'][:10],
                                                          home=h['name'], away=a['name'], goals=[f['goals']['home'], f['goals']['away']],
                                                          ht=[f['score']['halftime']['home'], f['score']['halftime']['away']],
                                                          stats=[teams.get(h['id'], {}), teams.get(a['id'], {})])
            atomic_write(OUT, json.dumps(store))
    with_corners = sum(1 for g in store.values() if g['stats'][0].get('corners') is not None)
    print(json.dumps(dict(games=len(store), with_corners=with_corners, requests_left_today=_left[0])))


if __name__ == '__main__':
    main()
