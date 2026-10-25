"""UEFA Champions League results and fixtures from TheSportsDB's free API.

Read round by round (the free key caps whole-season lists at 15 games). Rounds
1-20 cover qualifying, the group or league phase; the knockout rounds use
TheSportsDB's own numbers. Stored in ucl_data.json (git-ignored) for the private
Lab only, like the Saudi league.

    python3 app.py fetch-ucl
"""
import datetime as dt
import json
import time
from pathlib import Path

from quality import atomic_write
from saudi import _get, to_match

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'ucl_data.json'
LEAGUE_ID, LEAGUE_NAME = 'ucl', 'Europe — Champions League'
API = 'https://www.thesportsdb.com/api/v1/json/123/eventsround.php?id=4480&r={r}&s={s}'
ROUNDS = list(range(1, 21)) + [16, 32, 125, 150, 160, 170, 180, 200, 500]
FIRST_YEAR = 2021


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(matches, complete):
    atomic_write(FILE, json.dumps(dict(fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(), source='TheSportsDB (free API)',
                                       license='TheSportsDB terms; private research only, do not redistribute',
                                       complete_seasons=complete, matches=matches)))


def fetch(pause=2.5, log=print):
    today = dt.date.today()
    last = today.year if today.month >= 7 else today.year - 1
    old = load()
    keep = set(old.get('complete_seasons', []))
    matches = [m for m in old.get('matches', []) if m['season'] in keep]
    complete = sorted(keep)
    for year in range(FIRST_YEAR, last + 1):
        season = f'{year}-{str(year + 1)[-2:]}'
        if season in keep:
            continue
        seen, rows = set(), []
        for r in ROUNDS:
            events = _get(API.format(r=r, s=f'{year}-{year + 1}'), log)
            time.sleep(pause)
            for e in events:
                if e.get('idEvent') in seen or not (e.get('dateEvent') and e.get('strHomeTeam')):
                    continue
                seen.add(e.get('idEvent'))
                m = to_match(e, season)
                m.update(league_id=LEAGUE_ID, league=LEAGUE_NAME, round=e.get('intRound'), stage=e.get('strRound') or None)
                rows.append(m)
        log(f'{season}: {len(rows)} games, {sum(m["goals"] is not None for m in rows)} played')
        matches += rows
        if year < last and rows and all(m['goals'] is not None or m['postponed'] for m in rows):
            complete.append(season)
        _save(matches, complete)
    return dict(matches=len(matches), seasons=len({m['season'] for m in matches}))


def resolve(matches, data):
    """Rename TheSportsDB clubs to the dataset's names where the club is one we track."""
    import badges
    from live_odds import similarity
    from ucl_model import TRACKED
    known = sorted({t for m in data['matches'] if m['league_id'] in TRACKED for t in (m['home'], m['away'])})
    by_badge = {v['matched']: n for n, v in badges.load_index().items() if v.get('matched')}
    cache = {}

    def name(t):
        if t not in cache:
            if t in by_badge:
                cache[t] = by_badge[t]
            else:
                best = max(known, key=lambda k: similarity(t, k), default=None)
                cache[t] = best if best and similarity(t, best) >= 0.8 else t
        return cache[t]
    return [{**m, 'home': name(m['home']), 'away': name(m['away'])} for m in matches]
