"""Saudi Pro League results and fixtures from TheSportsDB's free API, round by round.

The free key lists at most 15 games per season but whole rounds, so seasons are read
one round at a time (about 34 requests a season, paced for the ~30/minute limit).
Kickoff times are UTC. Stored in saudi_data.json (git-ignored) and merged into the
private Lab only; never published to the community site.

    python3 app.py fetch-saudi
"""
import datetime as dt
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'saudi_data.json'
LEAGUE_ID, LEAGUE_NAME = 'sa.1', 'Saudi Arabia — Pro League'
API = 'https://www.thesportsdb.com/api/v1/json/123/eventsround.php?id=4668&r={r}&s={s}'
FIRST_YEAR = 2021


def _get(url, log):
    for wait in (65, 130, None):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'football-lab (private use)'}), timeout=25) as r:
                return json.loads(r.read() or b'{}').get('events') or []
        except HTTPError as exc:
            if exc.code != 429 or wait is None:
                raise
            log(f'rate limited, waiting {wait}s'); time.sleep(wait)
        except (URLError, TimeoutError, OSError) as exc:     # connection dropped: wait and retry
            if wait is None:
                raise
            log(f'network error ({exc}), retrying in {wait}s'); time.sleep(wait)


def _score(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_match(e, season):
    stamp = e.get('strTimestamp')
    hs, as_ = _score(e.get('intHomeScore')), _score(e.get('intAwayScore'))
    finished = (e.get('strStatus') or '').upper() in ('FT', 'AET', 'PEN', 'MATCH FINISHED') and hs is not None and as_ is not None
    return dict(league_id=LEAGUE_ID, league=LEAGUE_NAME, season=season, date=e['dateEvent'],
                home=e['strHomeTeam'], away=e['strAwayTeam'], goals=[hs, as_] if finished else None, ht=None,
                kickoff=(stamp.replace('+00:00', '') + 'Z') if stamp else None, confirmed=True,
                postponed=(e.get('strStatus') or '').lower().startswith(('postp', 'canc')),
                badges=[e.get('strHomeTeamBadge'), e.get('strAwayTeamBadge')], source_id=e.get('idEvent'))


def fetch(pause=2.3, log=print, refresh_from=None):
    """Download every round; finished past seasons are kept and not re-read."""
    today = dt.date.today()
    last = today.year if today.month >= 7 else today.year - 1
    old = load()
    keep = {s for s in old.get('complete_seasons', []) if s != refresh_from}
    matches = [m for m in old.get('matches', []) if m['season'] in keep]
    complete = sorted(keep)
    for year in range(FIRST_YEAR, last + 1):
        season = f'{year}-{str(year + 1)[-2:]}'
        if season in keep:
            continue
        rows = []
        for r in range(1, 39):
            events = _get(API.format(r=r, s=f'{year}-{year + 1}'), log)
            time.sleep(pause)
            if not events:
                break
            rows += [to_match(e, season) for e in events if e.get('dateEvent') and e.get('strHomeTeam')]
        log(f'{season}: {len(rows)} games, {sum(m["goals"] is not None for m in rows)} played')
        matches += rows
        if year < last and rows and all(m['goals'] is not None or m['postponed'] for m in rows):
            complete.append(season)
        _save(matches, complete)          # keep finished seasons even if a later one fails
    return dict(matches=len(matches), seasons=len({m['season'] for m in matches}))


def _save(matches, complete):
    payload = dict(fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(), source='TheSportsDB (free API)',
                   license='TheSportsDB terms; private research only, do not redistribute',
                   complete_seasons=complete, matches=matches)
    atomic_write(FILE, json.dumps(payload))


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def merge(data):
    """Add the stored Saudi games to the in-memory dataset (private Lab only)."""
    stored = load()
    rows = [m for m in stored.get('matches', []) if not m.get('postponed')]
    # A source record per season so the data-quality check can see how fresh it is.
    for season in sorted({m['season'] for m in rows}):
        data.setdefault('sources', []).append(dict(url=f'thesportsdb:4668/{season}/', league_id=LEAGUE_ID,
                                                   checked_at=stored.get('fetched_at'), license=stored.get('license')))
    data['matches'] = [m for m in data['matches'] if m['league_id'] != LEAGUE_ID] + [dict(m) for m in rows]
    return len(rows)
