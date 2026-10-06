"""Formations, lineups and injuries from API-Football (api-sports.io).

Optional: needs API_FOOTBALL_KEY in .env.  The free plan allows about 100
requests a day, so every response is cached on disk and a daily budget is
enforced locally.  Confirmed lineups appear shortly before kickoff; until
then each team's most recent XI is shown as a clearly labelled probable setup.
Private research use: this data is not sent to the community league.
"""
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quality import atomic_write
from live_odds import similarity

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'reports' / 'lineups'
API = 'https://v3.football.api-sports.io/'
DAILY_BUDGET = 90  # leave headroom under the free plan's 100 a day
LEAGUE_IDS = {'en.1': 39, 'es.1': 140, 'it.1': 135, 'de.1': 78, 'fr.1': 61, 'it.2': 136, 'de.2': 79}


class SetupError(Exception):
    pass


def _redact(text, key):
    return text.replace(key, '***') if key else text


def _season(date):
    d = dt.date.fromisoformat(date)
    return d.year if d.month >= 7 else d.year - 1


def _budget_path(directory):
    return Path(directory) / f'budget-{dt.date.today().isoformat()}.json'


def _get(path, params, ttl, key, directory, fetch=None):
    """Cached GET. ttl in seconds; returns the API's `response` list."""
    directory = Path(directory)
    name = hashlib.sha256((path + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:32]
    cached = directory / f'{name}.json'
    try:
        entry = json.loads(cached.read_text())
        if time.time() - entry['at'] < ttl:
            return entry['response']
    except (OSError, ValueError, KeyError):
        entry = None
    budget_file = _budget_path(directory)
    try:
        used = json.loads(budget_file.read_text())['used']
    except (OSError, ValueError, KeyError):
        used = 0
    if used >= DAILY_BUDGET:
        if entry:
            return entry['response']
        raise SetupError(f'Daily request budget ({DAILY_BUDGET}) used up; try again tomorrow.')
    if fetch is None:
        def fetch(url):
            request = Request(url, headers={'x-apisports-key': key, 'User-Agent': 'football-lab'})
            with urlopen(request, timeout=20) as r:
                return json.loads(r.read()), r.headers.get('x-ratelimit-requests-remaining')
    try:
        body, remaining = fetch(API + path + '?' + urlencode(params))
    except Exception as exc:
        if entry:
            return entry['response']
        raise SetupError(_redact(str(exc), key))
    atomic_write(budget_file, json.dumps(dict(used=used + 1, remaining=remaining)))
    errors = body.get('errors')
    if errors:
        message = '; '.join(f'{v}' for v in (errors.values() if isinstance(errors, dict) else errors))
        raise SetupError(_redact(message, key))
    atomic_write(cached, json.dumps(dict(at=time.time(), response=body.get('response', []))))
    return body.get('response', [])


def _find_fixture(fixtures, home, away):
    scored = sorted(((min(similarity(f['teams']['home']['name'], home), similarity(f['teams']['away']['name'], away)), f)
                     for f in fixtures), key=lambda x: -x[0])
    if not scored or scored[0][0] < .6 or (len(scored) > 1 and scored[1][0] > scored[0][0] - .05):
        return None
    return scored[0][1]


def _team_block(lineup, source, played_on=None):
    team = lineup.get('team') or {}
    colors = team.get('colors') or {}
    def players(items):
        out = []
        for item in items or []:
            p = item.get('player') or {}
            out.append(dict(name=p.get('name'), number=p.get('number'), pos=p.get('pos'), grid=p.get('grid')))
        return out
    return dict(name=team.get('name'), formation=lineup.get('formation'), coach=(lineup.get('coach') or {}).get('name'),
                colors=dict(player=colors.get('player'), goalkeeper=colors.get('goalkeeper')),
                xi=players(lineup.get('startXI')), bench=players(lineup.get('substitutes')),
                source=source, played_on=played_on)


def match_setup(league_id, date, home, away, directory=None, fetch=None):
    """Confirmed lineups when published, otherwise each side's last-used XI."""
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key and fetch is None:
        return dict(status='unconfigured', reason='Add API_FOOTBALL_KEY to .env for formations and lineups.')
    if league_id not in LEAGUE_IDS:
        return dict(status='error', reason='League not mapped to API-Football.')
    directory = directory or CACHE
    try:
        upcoming = date >= dt.date.today().isoformat()
        fixtures = _get('fixtures', dict(league=LEAGUE_IDS[league_id], season=_season(date), date=date),
                        6 * 3600 if upcoming else 7 * 86400, key, directory, fetch)
        fixture = _find_fixture(fixtures, home, away)
        if not fixture:
            return dict(status='error', reason='Could not match this fixture in API-Football.')
        fid = fixture['fixture']['id']
        lineups = _get('fixtures/lineups', dict(fixture=fid), 900 if upcoming else 30 * 86400, key, directory, fetch)
        injuries = _get('injuries', dict(fixture=fid), 6 * 3600, key, directory, fetch)
        teams = []
        for side in ('home', 'away'):
            team = fixture['teams'][side]
            confirmed = next((l for l in lineups if (l.get('team') or {}).get('id') == team['id']), None)
            if confirmed and confirmed.get('startXI'):
                teams.append(_team_block(confirmed, 'confirmed'))
                continue
            last = _get('fixtures', dict(team=team['id'], last=1), 12 * 3600, key, directory, fetch)
            if not last:
                teams.append(dict(name=team['name'], source='unavailable', xi=[], bench=[]))
                continue
            previous = last[0]
            prev_lineups = _get('fixtures/lineups', dict(fixture=previous['fixture']['id']), 30 * 86400, key, directory, fetch)
            block = next((l for l in prev_lineups if (l.get('team') or {}).get('id') == team['id']), None)
            teams.append(_team_block(block, 'last_match', previous['fixture']['date'][:10]) if block
                         else dict(name=team['name'], source='unavailable', xi=[], bench=[]))
        out_players = [dict(team=(i.get('team') or {}).get('name'), player=(i.get('player') or {}).get('name'),
                            type=(i.get('player') or {}).get('type'), reason=(i.get('player') or {}).get('reason'))
                       for i in injuries]
        try:
            remaining = json.loads(_budget_path(directory).read_text()).get('remaining')
        except (OSError, ValueError):
            remaining = None
        return dict(status='ok', fixture_id=fid, kickoff=fixture['fixture'].get('date'),
                    venue=(fixture['fixture'].get('venue') or {}).get('name'),
                    referee=fixture['fixture'].get('referee'), teams=teams, unavailable=out_players,
                    requests_remaining=remaining)
    except SetupError as exc:
        return dict(status='error', reason=str(exc))
