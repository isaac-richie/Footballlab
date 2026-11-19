"""NBA results and schedule from balldontlie (https://www.balldontlie.io) for the hosted site.

The local Lab reads ESPN (nba.py), which has no published reuse terms and also
carries bookmaker lines. The hosted site uses this file instead: scores, quarter
scores and the schedule only, from a keyed API, stored in nba_public.json in the
same game shape as nba.py so the same model and pages work on it.

Needs BALLDONTLIE_API_KEY. The free plan allows 5 requests a minute, so requests
are spaced out; the first run reads three seasons (about ten minutes), later runs
only the open dates and the next three weeks (a few requests).

    python3 nba_public.py           # fetch, then freeze and grade the public forward record
"""
import datetime as dt
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'nba_public.json'
API = 'https://api.balldontlie.io/v1/games'
SOURCE = 'balldontlie'
SEASONS_BACK = 2                       # seasons before the current one (the ratings look back 400 days)
GAP = 12.5                             # seconds between requests: 5 a minute on the free plan
# balldontlie abbreviations -> the ESPN ones the pages use for colours and logos
ABBR = {'GSW': 'GS', 'NOP': 'NO', 'NYK': 'NY', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH'}
TEAMS = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GS', 'HOU', 'IND', 'LAC', 'LAL', 'MEM',
         'MIA', 'MIL', 'MIN', 'NO', 'NY', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SA', 'TOR', 'UTAH', 'WSH'}
_last = [0.0]


def load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return dict(games=[], complete_seasons=[], fetched_at=None, source_id=SOURCE)
    data['source_id'] = SOURCE
    return data


def _get(params, key, tries=5):
    url = API + '?' + urlencode(params, doseq=True)
    for attempt in range(tries):
        wait = GAP - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urlopen(Request(url, headers={'Authorization': key, 'Accept': 'application/json'}), timeout=30) as r:
                return json.loads(r.read())
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError('balldontlie refused the key (check BALLDONTLIE_API_KEY).') from exc
            if attempt == tries - 1 or exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(30 if exc.code == 429 else 5)
        except (URLError, TimeoutError, OSError, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(5)


def _pages(params, key):
    cursor = None
    while True:
        page = _get(dict(params, per_page=100, **({'cursor': cursor} if cursor else {})), key)
        yield from page.get('data', [])
        cursor = (page.get('meta') or {}).get('next_cursor')
        if not cursor:
            return


def to_game(e):
    """One balldontlie game in nba.py's shape, or None when it is not two current franchises."""
    h, a = ABBR.get(e['home_team']['abbreviation'], e['home_team']['abbreviation']), \
        ABBR.get(e['visitor_team']['abbreviation'], e['visitor_team']['abbreviation'])
    if h not in TEAMS or a not in TEAMS:
        return None
    state = e.get('status_state') or ('final' if e.get('status') == 'Final' else None)
    final = state == 'final' or e.get('status') == 'Final'
    hs, vs = e.get('home_team_score'), e.get('visitor_team_score')
    if final and (not hs or not vs or hs == vs):
        final = False

    def quarters(side):
        q = [e.get(f'{side}_q{i}') for i in range(1, 5)]
        ot = [e.get(f'{side}_ot{i}') for i in range(1, 4)]
        if any(x is None for x in q):
            return None
        return q + [x for x in ot if x is not None]
    ph, pa = quarters('home'), quarters('visitor')
    periods = [ph, pa] if final and ph and pa and sum(ph) == hs and sum(pa) == vs and len(ph) == len(pa) else None
    tip = e.get('datetime')
    if tip and not tip.startswith(e['date'][:4]):
        tip = None
    status = 'final' if final else 'postponed' if e.get('postponed') else 'live' if state == 'in' or (e.get('period') or 0) > 0 else 'scheduled'
    return dict(id='bdl' + str(e['id']), season=e['season'] + 1, kind='playoffs' if e.get('postseason') else 'regular',
                date=e['date'][:10], tipoff=tip.replace('.000Z', 'Z') if tip else None, neutral=False,
                home=e['home_team']['full_name'], away=e['visitor_team']['full_name'], home_abbr=h, away_abbr=a,
                score=[hs, vs] if final else None, periods=periods, status=status)


def current_season(today):
    """balldontlie names a season by its starting year: 2026 is 2026-27."""
    return today.year if today.month >= 8 else today.year - 1


def fetch(key=None, today=None, log=print):
    key = key or os.environ.get('BALLDONTLIE_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Add BALLDONTLIE_API_KEY to .env (or the GitHub secrets).')
    today = today or dt.date.today()
    data = load()
    games = {g['id']: g for g in data['games']}
    now = current_season(today)
    requests = 0
    for season in range(now - SEASONS_BACK, now + 1):
        have = [g for g in games.values() if g['season'] == season + 1]
        if season + 1 in data['complete_seasons']:
            continue
        if have and season == now:
            open_ = [g['date'] for g in have if g['status'] != 'final' and g['date'] < today.isoformat()]
            start = min(open_ + [(today - dt.timedelta(days=3)).isoformat()])
            params = dict(start_date=start, end_date=(today + dt.timedelta(days=21)).isoformat())
        else:
            params = {'seasons[]': [season]}
        log(f'season {season}-{str(season + 1)[2:]}: {params}')
        for e in _pages(params, key):
            g = to_game(e)
            if g:
                games[g['id']] = g
        requests += 1
        if season < now and all(g['status'] in ('final', 'postponed') for g in games.values() if g['season'] == season + 1):
            data['complete_seasons'].append(season + 1)
    data['games'] = sorted(games.values(), key=lambda g: (g['tipoff'] or g['date'], g['id']))
    data['fetched_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    data['source'] = 'balldontlie API (scores and schedule)'
    data['source_id'] = SOURCE
    atomic_write(FILE, json.dumps(data, separators=(',', ':')))
    return dict(games=len(data['games']), final=sum(g['status'] == 'final' for g in data['games']),
                upcoming=sum(g['status'] == 'scheduled' and g['date'] >= today.isoformat() for g in data['games']))


if __name__ == '__main__':
    import config
    config.load_environment()
    print(json.dumps(fetch()))
    os.environ.setdefault('NBA_PUBLIC', '1')
    import nba_app
    print(json.dumps(dict(board=nba_app.save_board())))
    import nba_picks_ledger
    print(json.dumps(dict(saved_picks=nba_picks_ledger.save(nba_app.picks()))))
    import nba_ledger
    print(json.dumps(dict(ledger=nba_ledger.run(public=True))))
    import nba_vip
    print(json.dumps(dict(vip=nba_vip.run(public=True))))   # save today's NBA VIP picks, grade earlier ones
