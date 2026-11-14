"""NBA results, fixtures and bookmaker lines from ESPN's public JSON feeds.

The scoreboard is read one US game day at a time (date ranges are refused), and
each game keeps its quarter scores, so regulation and overtime points are known
separately. Lines come from ESPN's odds feed, one request per game: the opening
and closing (or current) spread, total and moneyline of the first sportsbook
listed, normally ESPN BET.

Unofficial feeds with no published reuse terms: stored in nba_data.json
(git-ignored) for the private Lab only, never published or committed.

    python3 app.py fetch-nba            # results and schedule, then lines for recent and upcoming games
    python3 app.py fetch-nba --lines    # also back-fill lines for every stored game (slow, once)
"""
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'nba_data.json'
LEAGUE_ID, LEAGUE_NAME = 'nba', 'USA — NBA'
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}'
ODDS = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{e}/competitions/{e}/odds'
FIRST_SEASON = 2022                     # ESPN season years end the season: 2022 is 2021-22
SEASON_TYPES = {2: 'regular', 3: 'playoffs', 5: 'play-in'}   # preseason (1) and All-Star (4) are left out
EASTERN = ZoneInfo('America/New_York')
LICENSE = 'ESPN public feeds; reuse terms unpublished; private research only, do not redistribute'
# The 30 franchises by ESPN abbreviation. All-Star games arrive as regular-season
# events and NBA Cup knockouts as "TBD" placeholders; neither has two of these.
TEAMS = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GS', 'HOU', 'IND', 'LAC', 'LAL', 'MEM',
         'MIA', 'MIL', 'MIN', 'NO', 'NY', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SA', 'TOR', 'UTAH', 'WSH'}


def load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return dict(games=[], complete_seasons=[], fetched_at=None)
    data['games'] = [g for g in data['games'] if g.get('home_abbr') in TEAMS and g.get('away_abbr') in TEAMS]
    return data


def save(data):
    data['fetched_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    data['source'], data['license'] = 'ESPN (public scoreboard and odds feeds)', LICENSE
    data['games'].sort(key=lambda g: (g['tipoff'] or g['date'], g['id']))
    atomic_write(FILE, json.dumps(data, separators=(',', ':')))


def _get(url, tries=4):
    for attempt in range(tries):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'football-lab (private research)', 'Accept': 'application/json'}), timeout=25) as r:
                return json.loads(r.read() or b'{}')
        except HTTPError as exc:
            if exc.code == 404:
                return {}
            if attempt == tries - 1 or exc.code not in (429, 500, 502, 503, 504):
                raise
        except (URLError, TimeoutError, OSError, ValueError):
            if attempt == tries - 1:
                raise
        time.sleep(3 * (attempt + 1))


def season_label(year):
    return f'{year - 1}-{str(year)[2:]}'


def to_game(event):
    """One scoreboard event as a stored game, or None when it is not a counted NBA game."""
    kind = SEASON_TYPES.get((event.get('season') or {}).get('type'))
    comp = (event.get('competitions') or [{}])[0]
    sides = {c.get('homeAway'): c for c in comp.get('competitors', [])}
    if not kind or set(sides) != {'home', 'away'} or any(c['team'].get('abbreviation') not in TEAMS for c in sides.values()):
        return None
    status = (event.get('status') or {}).get('type') or {}
    tipoff = event.get('date')
    when = dt.datetime.fromisoformat(tipoff.replace('Z', '+00:00')) if tipoff else None
    final = bool(status.get('completed')) and status.get('name') == 'STATUS_FINAL'
    def side(c):
        quarters = [int(q.get('value') or 0) for q in c.get('linescores') or []]
        return dict(team=c['team']['displayName'], abbr=c['team'].get('abbreviation'), team_id=c['team'].get('id'),
                    score=int(float(c['score'])) if final and c.get('score') not in (None, '') else None,
                    periods=quarters if final else None)
    h, a = side(sides['home']), side(sides['away'])
    if final and (h['score'] is None or a['score'] is None or h['score'] == a['score']):
        final = False                    # a tied or scoreless "final" is a feed error, not a result
    if final and h['periods'] and a['periods'] and (sum(h['periods']) != h['score'] or sum(a['periods']) != a['score']):
        h['periods'] = a['periods'] = None   # quarter scores that do not add up are dropped, the final kept
    return dict(id=event['id'], season=event['season']['year'], kind=kind,
                date=when.astimezone(EASTERN).date().isoformat() if when else event.get('date', '')[:10],
                tipoff=tipoff, neutral=bool(comp.get('neutralSite')), home=h['team'], away=a['team'],
                home_abbr=h['abbr'], away_abbr=a['abbr'],
                score=[h['score'], a['score']] if final else None,
                periods=[h['periods'], a['periods']] if final and h['periods'] and a['periods'] else None,
                status='final' if final else 'postponed' if status.get('name') in ('STATUS_POSTPONED', 'STATUS_CANCELED') else
                       'live' if status.get('state') == 'in' else 'scheduled')


def _parse_line(item):
    """Opening and closing lines from one sportsbook item, all prices decimal."""
    def num(text):
        try:
            return float(str(text).replace('+', ''))
        except (TypeError, ValueError):
            return None
    out = {}
    for stage in ('open', 'close', 'current'):
        h, a, t = ((item.get('homeTeamOdds') or {}).get(stage) or {}, (item.get('awayTeamOdds') or {}).get(stage) or {},
                   item.get(stage) or {})
        line = dict(spread=num((h.get('pointSpread') or {}).get('american')),
                    spread_prices=[(h.get('spread') or {}).get('decimal'), (a.get('spread') or {}).get('decimal')],
                    moneyline=[(h.get('moneyLine') or {}).get('decimal'), (a.get('moneyLine') or {}).get('decimal')],
                    total=num((t.get('total') or {}).get('american')),
                    total_prices=[(t.get('over') or {}).get('decimal'), (t.get('under') or {}).get('decimal')])
        if any(v is not None for v in (line['spread'], line['total'])) or all(line['moneyline']):
            out[stage] = line
    if 'close' not in out and 'current' in out:
        out['close'] = out['current']
    out.pop('current', None)
    if out:
        out['book'] = (item.get('provider') or {}).get('name')
    return out or None


def fetch_line(game_id):
    items = (_get(ODDS.format(e=game_id)) or {}).get('items') or []
    items = [i for i in items if 'live' not in ((i.get('provider') or {}).get('name') or '').lower()]
    items.sort(key=lambda i: int((i.get('provider') or {}).get('priority') or 0))
    for item in items:
        line = _parse_line(item)
        if line:
            line['fetched_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            return line
    return None


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def current_season(today=None):
    today = today or dt.date.today()
    return today.year + 1 if today.month >= 8 else today.year


def fetch(log=print, lines='recent', workers=4, today=None):
    """Read results and the schedule; past complete seasons are read once.

    lines: 'recent' fetches lines for games in the last 3 days and the next 10,
    'all' back-fills every stored game without a closing line, None skips lines.
    """
    today = today or dt.date.today()
    data = load()
    games = {g['id']: g for g in data['games']}
    now_season = current_season(today)
    days = []
    for year in range(FIRST_SEASON, now_season + 1):
        if year in data['complete_seasons']:
            continue
        start, end = dt.date(year - 1, 10, 1), dt.date(year, 6, 30)
        if year == now_season:
            pending = [dt.date.fromisoformat(g['date']) for g in games.values()
                       if g['season'] == year and g['status'] in ('scheduled', 'live') and g['date'] < today.isoformat()]
            have = any(g['season'] == year for g in games.values())
            if have:     # the full schedule is stored once; later reads cover open games and the next three weeks
                start = max(start, min(pending + [today - dt.timedelta(days=3)]))
                end = min(end, today + dt.timedelta(days=21))
        days += list(_days(start, end))
    log(f'reading {len(days)} game days')
    def read(day):
        return [g for g in (to_game(e) for e in (_get(SCOREBOARD.format(d=day.strftime('%Y%m%d'))) or {}).get('events', [])) if g]
    failed = 0
    with ThreadPoolExecutor(workers) as pool:
        for i, (day, result) in enumerate(zip(days, pool.map(lambda d: _safe(read, d), days))):
            if result is None:
                failed += 1
                continue
            for g in result:
                old = games.get(g['id'])
                if old and old.get('line'):
                    g['line'] = old['line']
                games[g['id']] = g
            if i % 60 == 59:
                log(f'  {day}: {len(games)} games so far')
    data['games'] = list(games.values())
    for year in range(FIRST_SEASON, now_season):
        season_games = [g for g in games.values() if g['season'] == year]
        if not failed and season_games and all(g['status'] in ('final', 'postponed') for g in season_games) and year not in data['complete_seasons']:
            data['complete_seasons'].append(year)
    save(data)
    got = 0
    if lines:
        lo, hi = (today - dt.timedelta(days=3)).isoformat(), (today + dt.timedelta(days=10)).isoformat()
        # Newest first, so an interrupted back-fill still covers the seasons the lab scores.
        want = [g for g in reversed(data['games']) if (lines == 'all' and g['season'] >= FIRST_SEASON + 2 and g['status'] == 'final'
                                                       and not (g.get('line') or {}).get('close'))
                or (lo <= g['date'] <= hi and g['status'] != 'postponed')]
        log(f'reading lines for {len(want)} games')
        with ThreadPoolExecutor(workers) as pool:
            for i, (g, line) in enumerate(zip(want, pool.map(lambda g: _safe(fetch_line, g['id']), want))):
                if line:
                    g['line'] = line; got += 1
                if i % 500 == 499:
                    save(data); log(f'  {i + 1} games checked, {got} with lines')
        save(data)
    return dict(games=len(data['games']), final=sum(g['status'] == 'final' for g in data['games']),
                upcoming=sum(g['status'] == 'scheduled' and g['date'] >= today.isoformat() for g in data['games']),
                day_failures=failed, lines_found=got, complete_seasons=data['complete_seasons'])


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception:
        return None


if __name__ == '__main__':
    import sys
    print(json.dumps(fetch(lines='all' if '--lines' in sys.argv else 'recent', workers=8)))
