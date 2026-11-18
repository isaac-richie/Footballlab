"""Fill missing scores from API-Football when the open feeds fall behind.

OpenFootball stopped updating on 20 Sept 2026, and OpenLigaDB has no maintained feed for
La Liga, Serie A, Ligue 1, the Eredivisie or the Primeira Liga. API-Football has every result.

Two modes, chosen by what the plan allows:
  season  one request per league for every finished game this season (paid plans), which also
          fills any gap at once;
  dates   yesterday and today for all leagues in two requests (the free plan only serves
          today plus or minus one day), which keeps results current from now on.

Safety, as in app.patch_openligadb: games are matched to ours by date (within a day) and team
names; an existing score is never overwritten; and a league is skipped entirely if API-Football
disagrees with scores we already have on more than 5% of at least 10 shared games.

Needs API_FOOTBALL_KEY. Results come from API-Football's terms, so keep their use to showing
our own forecasts and results unless the provider confirms more.
"""
import datetime as dt
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from football_live import IDS, _pair

API = 'https://v3.football.api-sports.io/fixtures'
FINISHED = {'FT', 'AET', 'PEN'}
LEAGUES = ('en.1', 'es.1', 'it.1', 'de.1', 'fr.1', 'it.2', 'de.2', 'nl.1', 'pt.1')


class PlanLimit(Exception):
    """The plan does not cover this request (e.g. a whole season on the free plan)."""


def _get(params, key, opener=urlopen):
    req = Request(API + '?' + urlencode(params), headers={'x-apisports-key': key, 'User-Agent': 'football-lab'})
    with opener(req, timeout=30) as r:
        body = json.loads(r.read())
    errors = body.get('errors') or {}
    if errors:
        if isinstance(errors, dict) and 'plan' in errors:
            raise PlanLimit(errors['plan'])
        raise RuntimeError(f'API-Football: {errors}')
    return body.get('response') or []


def fetch_finished(key, today, leagues=LEAGUES, get=_get):
    """[(league_id, fixture)] of finished games, and the mode used."""
    by_id = {IDS[lg]: lg for lg in leagues if lg in IDS}
    year = today.year if today.month >= 7 else today.year - 1
    out = []
    try:
        for api_id, lg in by_id.items():
            out += [(lg, f) for f in get(dict(league=api_id, season=year, status='FT-AET-PEN'), key)]
        return out, 'season'
    except PlanLimit:
        out = []
    for day in (today - dt.timedelta(days=1), today):
        for f in get(dict(date=day.isoformat(), timezone='UTC'), key):
            lg = by_id.get((f.get('league') or {}).get('id'))
            if lg and ((f.get('fixture') or {}).get('status') or {}).get('short') in FINISHED:
                out.append((lg, f))
    return out, 'dates'


def merge(matches, finished, today, min_overlap=10, min_agree=.95):
    """Fill missing scores in `matches` (in place). Returns {league_id: filled} and skipped leagues."""
    year = today.year if today.month >= 7 else today.year - 1
    season = f'{year}-{str(year + 1)[-2:]}'
    by_league = {}
    for lg, f in finished:
        by_league.setdefault(lg, []).append(f)
    filled, skipped = {}, {}
    for lg, fixtures in by_league.items():
        ours = [m for m in matches if m['league_id'] == lg and m['season'] == season]
        schedule = [(m['date'], m['home'], m['away']) for m in ours]
        index = {(m['date'], m['home'], m['away']): m for m in ours}
        pairs = []
        for f in fixtures:
            g = f.get('goals') or {}
            if g.get('home') is None or g.get('away') is None:
                continue
            key = _pair((f['fixture'].get('date') or '')[:10], f['teams']['home']['name'], f['teams']['away']['name'], schedule)
            if key:
                pairs.append((index[key], [int(g['home']), int(g['away'])]))
        both = [(m, s) for m, s in pairs if m['goals'] is not None]
        agree = sum(list(m['goals']) == s for m, s in both)
        if len(both) >= min_overlap and agree < min_agree * len(both):
            skipped[lg] = f'disagrees on {len(both) - agree} of {len(both)} shared scores'
            continue
        n = 0
        for m, score in pairs:
            if m['goals'] is None:
                m['goals'] = score
                m['score_source'] = 'api-football'
                n += 1
        if n:
            filled[lg] = n
    return filled, skipped


def fill(matches, today=None, key=None, get=_get):
    """Fetch and merge; returns a summary for the refresh log."""
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return dict(skipped='no API_FOOTBALL_KEY')
    today = today or dt.date.today()
    finished, mode = fetch_finished(key, today, get=get)
    filled, skipped = merge(matches, finished, today)
    return dict(mode=mode, finished_seen=len(finished), filled=filled, skipped=skipped)
