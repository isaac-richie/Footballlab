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


# Leagues whose open feed has stopped altogether (no fixtures, not just missing scores): their
# seasons are loaded whole from API-Football on a paid plan. OpenFootball stopped Serie B after
# March 2026 and has no 2026-27 file.
WHOLE_SEASONS = {'it.2': 'Italy — Serie B'}
ABOVE = {'it.2': 'it.1'}          # relegated clubs keep the name they had in the division above
DEAD = {'PST', 'CANC', 'ABD', 'AWD', 'WO'}


def _names(ours, theirs):
    """API-Football names -> ours, from games both list on the same day (within one) with the same score."""
    from collections import Counter, defaultdict
    index = defaultdict(list)
    for m in ours:
        if m['goals'] is not None:
            index[(m['date'], tuple(m['goals']))].append(m)
    votes = defaultdict(Counter)
    for f in theirs:
        g = f.get('goals') or {}
        if g.get('home') is None or g.get('away') is None:
            continue
        d = dt.date.fromisoformat(f['fixture']['date'][:10])
        for shift in (0, -1, 1):
            for m in index.get(((d + dt.timedelta(days=shift)).isoformat(), (int(g['home']), int(g['away']))), []):
                votes[f['teams']['home']['name']][m['home']] += 1
                votes[f['teams']['away']['name']][m['away']] += 1
    out = {}
    for name, c in votes.items():
        best, n = c.most_common(1)[0]
        if n >= 3 and n / sum(c.values()) >= .5:
            out[name] = best
    return out


def load_seasons(matches, today=None, key=None, get=_get, years=None):
    """Add whole seasons for WHOLE_SEASONS leagues (in place): fixtures, kick-offs and scores. An
    existing game (same season, home and away) is completed, never duplicated; scores we already
    have are kept."""
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return dict(skipped='no API_FOOTBALL_KEY')
    today = today or dt.date.today()
    current = today.year if today.month >= 7 else today.year - 1
    years = years or (current - 1, current)
    summary = {}
    for lg, name in WHOLE_SEASONS.items():
        ours_all = [m for m in matches if m['league_id'] == lg]
        added = filled = 0
        try:
            by_year = {year: get({'league': IDS[lg], 'season': year}, key) for year in years}
        except PlanLimit as exc:
            summary[lg] = f'plan limit: {exc}'
            continue
        # Names are matched on every season together, so a club keeps one name across seasons.
        names = _names(ours_all, [f for fs in by_year.values() for f in fs])
        if lg in ABOVE:
            from live_odds import similarity
            above = sorted({t for m in matches if m['league_id'] == ABOVE[lg] for t in (m['home'], m['away'])})
            for f in (f for fs in by_year.values() for f in fs):
                for side in ('home', 'away'):
                    n = f['teams'][side]['name']
                    if n not in names and above:
                        best = max(above, key=lambda t: similarity(n, t))
                        if similarity(n, best) >= .8:
                            names[n] = best
        for year, fixtures in by_year.items():
            season = f'{year}-{str(year + 1)[-2:]}'
            ours = [m for m in ours_all if m['season'] == season]
            by_pair = {(m['home'], m['away']): m for m in ours}
            for f in fixtures:
                st = (f['fixture'].get('status') or {}).get('short')
                if st in DEAD:
                    continue
                home = names.get(f['teams']['home']['name'], f['teams']['home']['name'])
                away = names.get(f['teams']['away']['name'], f['teams']['away']['name'])
                date, kick = f['fixture']['date'][:10], f['fixture']['date'].replace('+00:00', 'Z')
                g, ht = f.get('goals') or {}, (f.get('score') or {}).get('halftime') or {}
                score = [int(g['home']), int(g['away'])] if st in FINISHED and g.get('home') is not None else None
                half = [int(ht['home']), int(ht['away'])] if score and ht.get('home') is not None else None
                m = by_pair.get((home, away))
                if m:
                    if m['goals'] is None:
                        if score:
                            m.update(goals=score, ht=half, score_source='api-football')
                            filled += 1
                        if m['date'] != date or not m.get('kickoff'):
                            m.update(date=date, kickoff=kick)              # rescheduled, or no time listed yet
                    continue
                new = dict(date=date, home=home, away=away, goals=score, ht=half, league_id=lg, league=name,
                           season=season, kickoff=kick, score_source='api-football')
                matches.append(new)
                by_pair[(home, away)] = new
                added += 1
        summary.setdefault(lg, dict(added=added, filled=filled))
    return summary


def fill(matches, today=None, key=None, get=_get):
    """Fetch and merge; returns a summary for the refresh log."""
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return dict(skipped='no API_FOOTBALL_KEY')
    today = today or dt.date.today()
    finished, mode = fetch_finished(key, today, get=get)
    filled, skipped = merge(matches, finished, today)
    return dict(mode=mode, finished_seen=len(finished), filled=filled, skipped=skipped)
