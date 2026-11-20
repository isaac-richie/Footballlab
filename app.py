"""Zero-dependency, local-only football probability research prototype."""
import argparse
import datetime as dt
import hashlib
import json
import logging
import math
import os
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from urllib.error import HTTPError
from quality import atomic_write, canonicalize, coverage, digest, normalize, normalize_openligadb
from model import SPEC as MODEL, calibrate_grid
from markets import extended_markets, fit_first_half_share
from implied import implied_rates, implied_rates_rho
from count_markets import count_markets
import odds_data
import live_odds
import schedule
import saudi
import market_ratings
import nba_vip
from stats import import_csv, load as load_stats, market_rates, own_count_rates, poisson_over
from decision import assess
from jev_reviewer import review as jev_review


ROOT = Path(__file__).resolve().parent
log = logging.getLogger('football_lab')
DATA = ROOT / 'data.json'
STATS = ROOT / 'stats.json'
SOURCE = 'https://raw.githubusercontent.com/openfootball/football.json/master/'
OPENLIGADB_SOURCE = 'https://api.openligadb.de/getmatchdata/bl2/'
LEAGUES = {
    'en.1': 'England — Premier League',
    'es.1': 'Spain — La Liga',
    'it.1': 'Italy — Serie A',
    'de.1': 'Germany — Bundesliga',
    'fr.1': 'France — Ligue 1',
    'it.2': 'Italy — Serie B',
    'de.2': 'Germany — 2. Bundesliga',
    'sa.1': 'Saudi Arabia — Saudi Pro League',     # TheSportsDB, private Lab only (saudi.py)
    'tr.1': 'Turkey — Süper Lig',            # current season from football-data (private Lab only)
    'sco.1': 'Scotland — Scottish Premiership',       # current season from football-data (private Lab only)
    'nl.1': 'Netherlands — Eredivisie',
    'pt.1': 'Portugal — Primeira Liga',
    'be.1': 'Belgium — Belgian Pro League',          # current season from football-data (private Lab only)
}
if not (ROOT / 'saudi_data.json').exists():
    del LEAGUES['sa.1']                          # not downloaded here (e.g. the hosted, open-data Lab)
if (ROOT / 'ucl_data.json').exists():           # TheSportsDB, private Lab only (ucl.py, ucl_model.py)
    LEAGUES['ucl'] = 'Europe — Champions League'
if not odds_data.MARKET.exists():                # no open current-season feed for these yet
    for _lg in ('tr.1', 'sco.1', 'be.1'):
        LEAGUES.pop(_lg, None)
OPEN_LEAGUES = [k for k in LEAGUES if k not in ('sa.1', 'ucl')]     # leagues with an open results feed
# Installable-app files served from pwa/: URL -> (file, content type, cache header).
PWA_FILES = {
    '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json', 'max-age=3600'),
    '/sw.js': ('sw.js', 'text/javascript; charset=utf-8', 'no-cache'),
    '/icons/icon-192.png': ('icons/icon-192.png', 'image/png', 'max-age=604800'),
    '/icons/icon-512.png': ('icons/icon-512.png', 'image/png', 'max-age=604800'),
    '/apple-touch-icon.png': ('icons/apple-touch-icon.png', 'image/png', 'max-age=604800'),
}


def refresh():
    # Replace complete league-season partitions only after validation.
    existing = json.loads(DATA.read_text()) if DATA.exists() else {'matches': [], 'sources': []}
    matches, sources, failures = list(existing['matches']), list(existing['sources']), []
    sources = {s['url']: s for s in sources if s.get('league_id') != 'de.2'}
    successes = 0
    for year in range(2021, dt.date.today().year + 1):
        season = f'{year}-{str(year + 1)[-2:]}'
        for league_id, league_name in ((k, LEAGUES[k]) for k in OPEN_LEAGUES):
            # OpenLigaDB covers the missing 2. Bundesliga partitions and publishes
            # its match database under ODbL; keep this provenance per source.
            url = (f'{OPENLIGADB_SOURCE}{year}' if league_id == 'de.2'
                   else f'{SOURCE}{season}/{league_id}.json')
            try:
                raw = None
                error = None
                for attempt in range(3):
                    try:
                        with urlopen(url, timeout=25) as response:
                            raw = response.read()
                        break
                    except HTTPError as exc:
                        if exc.code == 404:
                            raise
                        error = exc
                        time.sleep(attempt + 1)
                    except Exception as exc:
                        error = exc
                        time.sleep(attempt + 1)
                if raw is None:
                    raise error
                replacement = (normalize_openligadb(raw, league_id, league_name, season)
                               if league_id == 'de.2'
                               else normalize(raw, league_id, league_name, season))
                prior = [m for m in matches if m.get('league_id') == league_id and m['season'] == season]
                if prior and len(replacement) < .9 * len(prior):
                    raise ValueError('Source shrank by over 10%; prior partition retained for review')
                matches = [m for m in matches if not (m.get('league_id') == league_id and m['season'] == season)] + replacement
                raw_hash = hashlib.sha256(raw).hexdigest()
                raw_path = ROOT / 'snapshots' / (raw_hash + '.json')
                if not raw_path.exists():
                    atomic_write(raw_path, raw.decode())
                source_record = dict(url=url, league_id=league_id, matches=len(replacement),
                                    sha256=raw_hash, checked_at=dt.datetime.now(dt.timezone.utc).isoformat())
                if league_id == 'de.2':
                    source_record.update(license='ODbL-1.0', license_url='https://opendatacommons.org/licenses/odbl/1-0/')
                else:
                    source_record.update(license='CC0-1.0')
                sources[url] = source_record
                successes += 1
            except Exception as exc:
                failures.append(dict(url=url, league_id=league_id, error=str(exc)))
    if not successes:
        raise RuntimeError('No source succeeded; existing data has not been replaced.')
    for league_id, (shortcut, trusted) in OPENLIGADB_PATCH.items():
        try:
            patched = patch_openligadb(matches, sources, league_id, shortcut, trusted)
            print(json.dumps({f'{league_id}_patched_from_openligadb': patched}))
        except Exception as exc:
            failures.append(dict(url=f'https://api.openligadb.de/getmatchdata/{shortcut}', league_id=league_id, error=str(exc)))
    # The open feeds stalled in Sept 2026 for five leagues; API-Football fills the missing scores
    # (never overwriting one). Whole seasons on a paid plan, yesterday and today on the free one.
    try:
        import apifootball_results
        print(json.dumps(dict(api_football_seasons=apifootball_results.load_seasons(matches))))
        summary = apifootball_results.fill(matches)
        print(json.dumps(dict(api_football=summary)))
        if summary.get('filled'):
            sources['https://v3.football.api-sports.io/fixtures'] = dict(
                url='https://v3.football.api-sports.io/fixtures', league_id='multi', matches=sum(summary['filled'].values()),
                checked_at=dt.datetime.now(dt.timezone.utc).isoformat(), license='API-Football terms of service',
                note='Fills scores the open feeds have not published yet.')
    except Exception as exc:
        failures.append(dict(url='https://v3.football.api-sports.io/fixtures', league_id='multi', error=str(exc)))
    unique = {(m['league_id'], m['date'], m['home'], m['away']): m for m in matches}
    payload = dict(fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   license='per-source', sources=list(sources.values()), failures=failures,
                   matches=sorted(unique.values(), key=lambda m: m['date']))
    atomic_write(DATA, json.dumps(payload, indent=2))
    print(json.dumps(dict(matches=len(unique), sources=len(sources), failures=failures)))


def current_teams(data, league_id):
    """This season's clubs only, so relegated sides don't clutter the team picker."""
    rows = [m for m in data['matches'] if m['league_id'] == league_id]
    if not rows:
        return []
    season = max(m['season'] for m in rows)
    return sorted({t for m in rows if m['season'] == season for t in (m['home'], m['away'])})


# Leagues whose open OpenLigaDB (ODbL) feed corrects OpenFootball's lagging schedule and fills its
# missing scores. bl1 is OpenLigaDB's own; pl and la1 are community-maintained, so scores are only
# filled where the feed agrees with OpenFootball on games both have scored (see patch_openligadb).
OPENLIGADB_PATCH = {'de.1': ('bl1', True), 'en.1': ('pl', False), 'es.1': ('la1', False)}   # (feed, trusted)


def patch_openligadb(matches, sources, league_id, shortcut, trusted=False, raw=None, today=None, min_overlap=20, min_agree=.95):
    """Correct this season's dates/kickoffs and fill missing scores for one league from OpenLigaDB.

    Games are matched by their home/away pairing, which happens once a season, after pairing
    the two sources' team names by similarity; every team must pair up or nothing is changed.
    Existing scores are never overwritten. Missing scores are filled only when the feed agrees
    with OpenFootball on at least min_agree of at least min_overlap games scored by both, unless
    the feed is trusted (OpenLigaDB's own Bundesliga data).
    A later refresh rebuilds the season from OpenFootball first, so its scores win when it updates.
    """
    from live_odds import similarity
    today = today or dt.date.today()
    year = today.year if today.month >= 7 else today.year - 1
    season = f'{year}-{str(year + 1)[-2:]}'
    url = f'https://api.openligadb.de/getmatchdata/{shortcut}/{year}'
    if raw is None:
        with urlopen(url, timeout=25) as response:
            raw = response.read()
    fresh = normalize_openligadb(raw, league_id, LEAGUES.get(league_id, league_id), season)
    ours = [m for m in matches if m['league_id'] == league_id and m['season'] == season]
    our_teams = sorted({t for m in ours for t in (m['home'], m['away'])})
    their_teams = sorted({t for m in fresh for t in (m['home'], m['away'])})
    names = {}
    for t in their_teams:
        best = max(our_teams, key=lambda o: similarity(t, o), default=None)
        if best and similarity(t, best) >= 0.6 and best not in names.values():
            names[t] = best
    if len(names) != len(their_teams) or len(their_teams) != len(our_teams):
        raise ValueError(f'{shortcut}: only {len(names)} of {len(their_teams)} teams pair up; nothing changed')
    by_pair = {(m['home'], m['away']): m for m in ours}
    pairs = [(by_pair.get((names[f['home']], names[f['away']])), f) for f in fresh]
    both = [(m, f) for m, f in pairs if m and m['goals'] is not None and f['goals'] is not None]
    agree = sum(list(m['goals']) == list(f['goals']) for m, f in both)
    fill_scores = trusted or (len(both) >= min_overlap and agree >= min_agree * len(both))
    dates = scores = 0
    for m, f in pairs:
        if not m or m['goals'] is not None:
            continue
        if m['date'] != f['date']:
            m['date'] = f['date']; dates += 1
        if f.get('kickoff'):
            m['kickoff'] = f['kickoff']
        if fill_scores and f['goals'] is not None:
            m['goals'], m['ht'], m['goals_source'] = f['goals'], f['ht'], 'openligadb'; scores += 1
    sources[url] = dict(url=url, league_id=league_id, matches=len(fresh), sha256=hashlib.sha256(raw).hexdigest(),
                        checked_at=dt.datetime.now(dt.timezone.utc).isoformat(), license='ODbL-1.0',
                        license_url='https://opendatacommons.org/licenses/odbl/1-0/',
                        role='corrects dates and kickoffs' + (', fills missing results' if fill_scores else ''),
                        agreement=dict(both_scored=len(both), agree=agree))
    return dict(dates=dates, scores=scores, overlap=len(both), agree=agree, scores_trusted=fill_scores)


def backfill_halftime():
    """Attach half-time scores from the exact raw snapshots behind current partitions."""
    # Fresh, unfilled copy: this writes data.json, which must hold open-licence results only.
    data = json.loads(DATA.read_text())
    canonicalize(data['matches'])
    halves = {}
    for source in data['sources']:
        path = ROOT / 'snapshots' / (source.get('sha256', '') + '.json')
        if not path.exists():
            continue
        league_id = source['league_id']
        raw = path.read_bytes()
        if league_id == 'de.2':
            season_year = int(source['url'].rstrip('/').rsplit('/', 1)[-1])
            rows = normalize_openligadb(raw, league_id, LEAGUES[league_id], f'{season_year}-{str(season_year + 1)[-2:]}')
        else:
            rows = normalize(raw, league_id, LEAGUES[league_id], source['url'].split('/')[-2])
        for row in rows:
            halves[(league_id, row['date'], row['home'], row['away'])] = (row['goals'], row['ht'])
    attached = 0
    for match in data['matches']:
        found = halves.get((match['league_id'], match['date'], match['home'], match['away']))
        # Only trust a half-time score whose snapshot agrees on the full-time score.
        match['ht'] = found[1] if found and found[0] == match['goals'] else None
        attached += match['ht'] is not None
    atomic_write(DATA, json.dumps(data, indent=2))
    print(json.dumps(dict(matches=len(data['matches']), with_halftime=attached)))


def load(fill_gaps=True):
    """Load results. With fill_gaps, past fixtures the open feed hasn't scored yet are filled
    in memory from football-data.co.uk (private use only, never saved or published)."""
    if not DATA.exists():
        raise ValueError('Run python3 app.py refresh first.')
    # Parsing and gap-filling take seconds, so reuse the result until either file changes.
    # Callers treat the returned data as read-only.
    stamp = (DATA.stat().st_mtime_ns, odds_data.MARKET.stat().st_mtime_ns if odds_data.MARKET.exists() else 0, fill_gaps)
    hit = _load_cache.get(fill_gaps)
    if hit and hit[0] == stamp:
        return hit[1]
    data = json.loads(DATA.read_text())
    canonicalize(data['matches'])
    if fill_gaps:
        fill_missing_results(data)
        saudi.merge(data)
        if 'ucl' in LEAGUES:
            merge_ucl(data)
        if odds_data.MARKET.exists():
            schedule.reconcile(data, odds_data.load(), live_cache=live_odds.load_cache())
    _load_cache[fill_gaps] = (stamp, data)
    return data


_load_cache = {}


def merge_ucl(data):
    """Champions League games with club names matched to the domestic data (private Lab only)."""
    import ucl
    stored = ucl.load()
    rows = ucl.resolve([m for m in stored.get('matches', []) if not m.get('postponed')], data)
    data['matches'] = [m for m in data['matches'] if m['league_id'] != 'ucl'] + rows
    for season in sorted({m['season'] for m in rows}):
        data.setdefault('sources', []).append(dict(url=f'thesportsdb:4480/{season}/', league_id='ucl',
                                                   checked_at=stored.get('fetched_at'), license=stored.get('license')))
    return len(rows)


_ucl_forecaster = {}


def ucl_forecaster(data):
    """One cross-league forecaster per loaded dataset (offsets cached per day on disk)."""
    import ucl_model
    key = id(data['matches'])
    if key not in _ucl_forecaster:
        _ucl_forecaster.clear()
        _ucl_forecaster[key] = ucl_model.Forecaster(data, [m for m in data['matches'] if m['league_id'] == 'ucl'],
                                                    market_ratings.fit, ROOT / 'reports' / 'ucl_params.json')
    return _ucl_forecaster[key]


def fill_missing_results(data):
    today = dt.date.today().isoformat()
    gaps = [m for m in data['matches'] if m['goals'] is None and m['date'] < today]
    if not gaps or not odds_data.MARKET.exists():
        return 0
    found = odds_data.index(odds_data.load(), data['matches'])
    filled = 0
    for m in gaps:
        r = found.get((m['league_id'], m['date'], m['home'], m['away']))
        if r and r.get('goals') and not r.get('upcoming'):
            m['goals'], m['ht'], m['goals_source'] = list(r['goals']), r.get('ht'), 'football-data'
            filled += 1
    data['filled_from_football_data'] = filled
    data['seasons_from_football_data'] = fill_missing_seasons(data)
    return filled


def fill_missing_seasons(data):
    """Whole league-seasons the open feed lacks (Serie B 2021-24), from football-data, in memory only."""
    have = {(m['league_id'], m['season']) for m in data['matches']}
    added = {}
    for r in odds_data.load()['records']:
        key = (r['league_id'], r.get('season'))
        if key in have or r.get('upcoming') or not r.get('goals') or not (r.get('home') and r.get('away')):
            continue
        data['matches'].append(dict(date=r['date'], home=r['home'], away=r['away'], goals=list(r['goals']), ht=r.get('ht'),
                                    league_id=r['league_id'], league=LEAGUES[r['league_id']], season=r['season'],
                                    goals_source='football-data'))
        added[f'{key[0]} {key[1]}'] = added.get(f'{key[0]} {key[1]}', 0) + 1
    return added


def history(data, asof, league_id):
    # Date-granularity cutoff deliberately excludes every match on the prediction day.
    return [m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None and m['date'] < asof]


def rates(rows, home, away, asof):
    if len(rows) < 100:
        raise ValueError('At least 100 completed earlier matches are required.')
    cutoff = dt.date.fromisoformat(asof)
    weighted = [(m, 0.5 ** ((cutoff - dt.date.fromisoformat(m['date'])).days / 365)) for m in rows]
    weight = sum(w for _, w in weighted)
    hg = sum(m['goals'][0] * w for m, w in weighted) / weight
    ag = sum(m['goals'][1] * w for m, w in weighted) / weight
    def team_rate(team, position, goal_index, prior):
        selected = [(m, w) for m, w in weighted if m['home' if position == 0 else 'away'] == team]
        # Eight equivalent games of shrinkage towards league average.
        return (sum(m['goals'][goal_index] * w for m, w in selected) + 8 * prior) / (sum(w for _, w in selected) + 8)
    lh = team_rate(home, 0, 0, hg) * team_rate(away, 1, 0, hg) / max(hg, 0.01)
    la = team_rate(away, 1, 1, ag) * team_rate(home, 0, 1, ag) / max(ag, 0.01)
    counts = {t: sum(t in (m['home'], m['away']) for m in rows) for t in (home, away)}
    return max(.05, min(6, lh)), max(.05, min(6, la)), counts


def distribution(lh, la, rho=0.0, calibration=None):
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and 0 < x <= 6 for x in (lh, la)):
        raise ValueError('Goal rates must be finite and between 0 and 6.')
    def poisson(lam):
        p = [math.exp(-lam)]
        for k in range(1, 26):
            p.append(p[-1] * lam / k)
        return p
    if not isinstance(rho, (int, float)) or not math.isfinite(rho):
        raise ValueError('Dixon-Coles rho must be finite.')
    def tau(h, a):
        if h == 0 and a == 0: return 1 - lh * la * rho
        if h == 0 and a == 1: return 1 + lh * rho
        if h == 1 and a == 0: return 1 + la * rho
        if h == 1 and a == 1: return 1 - rho
        return 1
    cells = [(h, a, ph * pa * tau(h, a)) for h, ph in enumerate(poisson(lh)) for a, pa in enumerate(poisson(la))]
    if any(p <= 0 or not math.isfinite(p) for _, _, p in cells):
        raise ValueError('Dixon-Coles rho creates an invalid score probability.')
    mass = sum(p for _, _, p in cells)
    if calibration:
        grid = calibrate_grid({(h, a): p / mass for h, a, p in cells}, calibration)
        cells, mass = [(h, a, grid[(h, a)]) for h, a, _ in cells], 1.0
    probs = [sum(p for h, a, p in cells if (h > a, h == a, h < a)[i]) / mass for i in range(3)]
    def chance(predicate):
        return sum(p for h, a, p in cells if predicate(h, a)) / mass
    total_lines = {str(line): chance(lambda h, a, line=line: h + a > line)
                   for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)}
    team_goals = {
        'home': {str(line): chance(lambda h, a, line=line: h > line) for line in (0.5, 1.5, 2.5, 3.5)},
        'away': {str(line): chance(lambda h, a, line=line: a > line) for line in (0.5, 1.5, 2.5, 3.5)},
    }
    handicaps = {str(line): chance(lambda h, a, line=line: h + line > a)
                 for line in (-1.5, -0.5, 0.5, 1.5)}
    home_win, draw, away_win = probs
    no_goal = chance(lambda h, a: h == 0 and a == 0)
    first_goal_mass = 1 - no_goal
    first_goal = {
        'home': lh / (lh + la) * first_goal_mass,
        'away': la / (lh + la) * first_goal_mass,
        'no_goal': no_goal,
    }
    return dict(probabilities=probs,
                over25=sum(p for h, a, p in cells if h + a > 2) / mass,
                btts=sum(p for h, a, p in cells if h > 0 and a > 0) / mass,
                total_goal_overs=total_lines, team_goal_overs=team_goals,
                home_handicap_covers=handicaps,
                double_chance={'home_or_draw': home_win + draw,
                               'draw_or_away': draw + away_win,
                               'home_or_away': home_win + away_win},
                draw_no_bet={'home_win_if_settled': home_win / (home_win + away_win),
                             'away_win_if_settled': away_win / (home_win + away_win),
                             'draw_push': draw},
                first_goal=first_goal,
                clean_sheets={'home': chance(lambda h, a: a == 0), 'away': chance(lambda h, a: h == 0)},
                win_to_nil={'home': chance(lambda h, a: h > a and a == 0),
                            'away': chance(lambda h, a: a > h and h == 0)},
                scorelines=[dict(score=f'{h}–{a}', probability=p / mass) for h, a, p in sorted(cells, key=lambda x: -x[2])[:5]])


def market_comparison(probs, odds):
    if len(odds) != 3 or any(not math.isfinite(o) or o <= 1 for o in odds):
        raise ValueError('Enter three finite decimal odds greater than 1.')
    implied = [1 / o for o in odds]
    total = sum(implied)
    fair = [p / total for p in implied]
    return dict(overround=total - 1, market_probabilities=fair,
                gap=[p - q for p, q in zip(probs, fair)],
                expected_return=[p * o - 1 for p, o in zip(probs, odds)])


def supplemental_markets(stats, league_id, home, away, asof):
    records = [r for r in stats['records'] if r['league_id'] == league_id]
    shots = market_rates(records, home, away, asof, 'home_shots', 'away_shots')
    cards = own_count_rates(records, home, away, asof, 'home_red_cards', 'away_red_cards', minimum=300)
    result = dict(records_before_date=sum(r['date'] < asof for r in records), sources=sorted({r['source'] for r in records}))
    if shots:
        h, a, counts, n = shots
        result['shots'] = dict(expected=[h, a], sample_matches=n, team_samples=counts,
                               total_overs={str(line): poisson_over(h + a, line) for line in (15.5, 19.5, 23.5, 27.5)},
                               team_overs={'home': {str(line): poisson_over(h, line) for line in (7.5, 9.5, 11.5)},
                                           'away': {str(line): poisson_over(a, line) for line in (7.5, 9.5, 11.5)}})
    if cards:
        h, a, counts, n = cards
        result['red_cards'] = dict(expected=[h, a], sample_matches=n, team_samples=counts,
                                   total_overs={str(line): poisson_over(h + a, line) for line in (.5, 1.5)})
    if not shots or not cards:
        result['withheld'] = 'Supplemental markets require ≥200 validated shot records and ≥300 validated red-card records before the analysis date.'
    return result


_market_cache = {}


def market_lookup(data):
    """football-data.co.uk prices keyed to dataset fixtures, reloaded on change."""
    try:
        stamp = odds_data.MARKET.stat().st_mtime
    except OSError:
        return {}
    key = (stamp, data.get('fetched_at'), id(data['matches']), len(data['matches']))
    if _market_cache.get('stamp') != key:
        index = odds_data.index(odds_data.load(), data['matches'])
        for m in data['matches']:
            k = (m['league_id'], m['date'], m['home'], m['away'])
            if m.get('_fd') and k not in index:
                index[k] = m['_fd']
        _market_cache.update(stamp=key, index=index)
    return _market_cache['index']


def fixture_date_for(data, league_id, home, away, asof, requested=None):
    if requested:
        dt.date.fromisoformat(requested)
        return requested
    upcoming = sorted(m['date'] for m in data['matches'] if m['league_id'] == league_id and
                      m['home'] == home and m['away'] == away and m['date'] >= asof and
                      (dt.date.fromisoformat(m['date']) - dt.date.fromisoformat(asof)).days <= 21)
    return upcoming[0] if upcoming else None


def _check_odds(values, n):
    odds = [float(o) for o in values]
    if len(odds) != n or any(not math.isfinite(o) or o <= 1 for o in odds):
        raise ValueError(f'Enter {n} finite decimal odds greater than 1.')
    return odds


def market_prices(data, request, league_id, home, away, asof, fixture_date):
    """Sharpest available pre-match prices: typed, live, then football-data."""
    if request.get('odds'):
        ou = request.get('ou_odds')
        return dict(source='entered', label='Odds you entered', h2h=_check_odds(request['odds'], 3),
                    ou25=_check_odds(ou, 2) if ou else None)
    if not fixture_date:
        return None
    if fixture_date >= dt.date.today().isoformat():
        live = live_odds.lookup(live_odds.load_cache(), league_id, fixture_date, home, away)
        if live and live.get('h2h'):
            line = live['totals'].get('2.5') or {}
            ou = [line['over']['median'], line['under']['median']] if line.get('over') and line.get('under') else None
            return dict(source='live', label=f"Typical price across {len(live['books'])} bookies, live",
                        h2h=[live['h2h'][k]['median'] for k in ('home', 'draw', 'away')], ou25=ou,
                        fetched_at=live['fetched_at'], best={k: live['h2h'][k] for k in ('home', 'draw', 'away')},
                        books=live['all_h2h'], totals=live['totals'])
    record = market_lookup(data).get((league_id, fixture_date, home, away))
    if record and 'avg_open' in record['odds']:
        odds = record['odds']
        return dict(source='football-data', label='Average bookie price (football-data.co.uk)',
                    h2h=odds['avg_open'], ou25=odds.get('ou25_avg_open'),
                    best=dict(zip(('home', 'draw', 'away'), ({'best': x} for x in odds['max_open']))) if 'max_open' in odds else None,
                    asian=dict(line=odds.get('ah_line_open'), prices=odds.get('ah_avg_open')) if 'ah_avg_open' in odds else None,
                    closing=odds.get('avg_close') if fixture_date < dt.date.today().isoformat() else None)
    return None


def predict(data, request, stats=None):
    if not isinstance(request, dict):
        raise ValueError('Request must be an object.')
    home, away, league_id = request['home'], request['away'], request['league_id']
    if not all(isinstance(t, str) for t in (home, away, league_id)):
        raise ValueError('League and teams must be strings.')
    asof = request.get('date') or dt.date.today().isoformat()
    if not isinstance(asof, str):
        raise ValueError('Date must be an ISO date string.')
    dt.date.fromisoformat(asof)
    if asof > dt.date.today().isoformat():
        raise ValueError('Use today or a past analysis date; future results must not enter a forecast.')
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    teams = {m[k] for m in data['matches'] if m['league_id'] == league_id for k in ('home', 'away')}
    if home == away or home not in teams or away not in teams:
        raise ValueError('Choose two different teams from the data.')
    rows = history(data, asof, league_id)
    if league_id == 'ucl':
        (lh, la), clubs_from = ucl_forecaster(data).rates(home, away, asof)
        rho, fit = 0.0, dict(calibration=None, method='cross-league: domestic ratings with league-strength offsets',
                             leagues=list(clubs_from))
    else:
        expected, rho, fit = market_ratings.fit(rows, asof, (home, away))
        lh, la = expected(home, away)
    counts = {t: sum(t in (m['home'], m['away']) for m in rows) for t in (home, away)}
    model_view = distribution(lh, la, rho, fit['calibration'])
    fixture_date = fixture_date_for(data, league_id, home, away, asof, request.get('fixture_date'))
    prices = market_prices(data, request, league_id, home, away, asof, fixture_date)
    pricing = dict(source='model', label='Our model only (no bookie prices for this match yet)', fixture_date=fixture_date)
    rates, calibration = (lh, la), fit['calibration']
    if prices:
        mh, ma, mrho, error = market_fit(prices, rho, (lh, la))
        if error < .03:
            rates, rho, calibration = (mh, ma), mrho, None
            pricing = dict(prices, fixture_date=fixture_date, fit_error=error,
                           note='Every number on this page is worked out from the bookies\' prices, with their cut removed.')
        else:
            pricing['note'] = f'Bookmaker prices found but could not be matched by a goal model (error {error:.3f}); using the model.'
    result = distribution(*rates, rho, calibration)
    share = fit_first_half_share(rows, asof)
    result['markets'] = extended_markets(*rates, rho, share, calibration)
    if fixture_date:
        pricing['movement'] = live_odds.movement(league_id, '|'.join((fixture_date, home, away)))
    result['pricing'] = pricing
    result['model_view'] = dict(probabilities=model_view['probabilities'], expected_goals=[lh, la],
                                over25=model_view['over25'], btts=model_view['btts'])
    if share is None:
        result['markets']['halftime_withheld'] = 'Half-time markets need at least 200 earlier matches with half-time scores.'
    readiness = coverage(data, league_id, asof)
    recent_counts = {t: sum(t in (m['home'], m['away']) and
                           (dt.date.fromisoformat(asof) - dt.date.fromisoformat(m['date'])).days <= 365
                           for m in rows) for t in (home, away)}
    if min(recent_counts.values()) < 10 and league_id != 'ucl':   # cup sides play few games in the competition
        readiness['issues'].append('At least one team has fewer than 10 league matches in the past year')
        readiness['status'] = 'review_required'
    result.update(model=MODEL, fit=fit, readiness=readiness, recent_team_samples=recent_counts)
    result.update(expected_goals=list(rates), sample_matches=len(rows), team_samples=counts,
                  league=LEAGUES[league_id], latest_result=max(m['date'] for m in rows), analysis_date=asof,
                  warnings=['Bookmaker prices drive these probabilities.' if pricing['source'] != 'model' else 'Research model: regularized score-history inputs only; no injury, lineup, shot or card inputs.'])
    if min(counts.values()) < 20:
        result['warnings'].append('Limited team history: estimates rely heavily on league averages.')
    if (dt.date.fromisoformat(asof) - dt.date.fromisoformat(result['latest_result'])).days > 30:
        result['warnings'].append('Latest available completed result is over 30 days before the analysis date.')
    if prices:
        result['market'] = market_comparison(model_view['probabilities'], prices['h2h'])
        if prices.get('best'):
            fair = result['probabilities']
            result['market']['best_price_value'] = [
                dict(outcome=k, best=prices['best'][k]['best'], book=prices['best'][k].get('best_book'),
                     fair_odds=1 / fair[i], edge=fair[i] * prices['best'][k]['best'] - 1)
                for i, k in enumerate(('home', 'draw', 'away'))]
    result['supplemental_markets'] = supplemental_markets(stats or {'records': []}, league_id, home, away, asof)
    result['count_markets'] = count_markets(rows, market_lookup(data), league_id, home, away, asof)
    try:
        import corners
        result['corners'] = corners.forecast(data['matches'], league_id, home, away, asof)
    except Exception as exc:                          # corners are an extra: never break the forecast
        result['corners'] = dict(status='unavailable', reason=str(exc)[:160])
    result['decision'] = assess(result)
    from analysis import briefing
    result['analysis'] = briefing(rows, home, away, result)
    result['jev_review'] = (jev_review(result) if request.get('review', True)
                            else {'status': 'skipped', 'reason': 'Independent review skipped for batch runs to protect quota.'})
    return result


_slate_cache = {}
_season_cache = {}


def _cache_key(data, league_id, today):
    live_stamp = live_odds.load_cache().get('leagues', {}).get(league_id, {}).get('fetched_at')
    market_lookup(data)
    return (league_id, today, data.get('fetched_at'), live_stamp, _market_cache.get('stamp'))


def market_fit(prices, rho, start):
    """Goal rates (and low-score dependence) reproducing margin-free bookmaker prices.

    With 1X2 and over/under 2.5 prices there are three numbers to match, so the
    dependence term is solved too and the 1X2 shown equals the market exactly.
    """
    p = odds_data.fair(prices['h2h'])
    if prices.get('ou25'):
        return implied_rates_rho(p, odds_data.fair(prices['ou25'])[0], rho, start)
    mh, ma, error = implied_rates(p, None, rho, start)
    return mh, ma, rho, error


def fixture_rates(data, league_id, fixtures, today):
    """One model fit at today's cutoff; bookmaker-implied rates wherever prices exist."""
    rows = history(data, today, league_id)
    if league_id == 'ucl':                       # cross-league: domestic ratings on one scale
        f = ucl_forecaster(data)
        return rows, 0.0, [({**m, '_cal': None}, r, r, 'model', None) for m in fixtures for r in [f.rates(m['home'], m['away'], today)[0]]]
    teams = {t for m in fixtures for t in (m['home'], m['away'])}
    expected, rho, fit = market_ratings.fit(rows, today, sorted(teams))
    priced = []
    for m in fixtures:
        m = {**m, '_cal': fit['calibration']}       # applies to the model's own numbers only
        model_rates = expected(m['home'], m['away'])
        source, rates, prices = 'model', model_rates, None
        if m['date'] >= today:
            prices = market_prices(data, {}, league_id, m['home'], m['away'], today, m['date'])
        if prices:
            mh, ma, mrho, error = market_fit(prices, rho, model_rates)
            if error < .03:
                source, rates = prices['source'], (mh, ma)
                m = {**m, '_rho': mrho}
        priced.append((m, model_rates, rates, source, prices))
    return rows, rho, priced


RECENT_DAYS = 0         # played-but-unscored games stay listed only on the day they were played


def last_five(data, league_id, today, n=5):
    """Each team's last n league results before today, oldest first, as 'W' / 'D' / 'L'."""
    out = {}
    played = sorted((m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None and m['date'] < today),
                    key=lambda m: (m['date'], m.get('kickoff') or ''))
    for m in played:
        h, a = m['goals']
        out.setdefault(m['home'], []).append('W' if h > a else 'D' if h == a else 'L')
        out.setdefault(m['away'], []).append('W' if a > h else 'D' if h == a else 'L')
    return {team: results[-n:] for team, results in out.items()}


def slate(data, league_id, limit=40):
    """Forecast every upcoming fixture in a league from one fit at today's cutoff."""
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    today = dt.date.today().isoformat()
    key = _cache_key(data, league_id, today)
    if key in _slate_cache:
        result = _slate_cache[key]
        for f in result['fixtures']:                      # cached for the day; status moves with the clock
            f['status'] = schedule.status(dict(goals=None, date=f['date'], kickoff=f.get('kickoff')))
        return result
    # Upcoming means not yet kicked off or still in play. Games that should be over but whose
    # score has not arrived stay listed for the rest of their day (RECENT_DAYS), marked
    # 'awaiting_result', so tonight's games don't vanish at the final whistle; older ones drop off. Today's games without a known kickoff
    # time (the hosted, open-data Lab) stay listed as 'today' until their result arrives.
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=RECENT_DAYS)).isoformat()
    fixtures = sorted((m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is None and not m.get('unconfirmed')
                       and (m['date'] >= today and schedule.status(m) in ('scheduled', 'live')
                            or m['date'] >= recent and schedule.status(m) == 'awaiting_result')),
                      key=lambda m: (m['date'], m.get('kickoff') or ''))[:limit]
    rows, rho, priced = fixture_rates(data, league_id, fixtures, today)
    recent = {t: sum(t in (m['home'], m['away']) and
                     (dt.date.fromisoformat(today) - dt.date.fromisoformat(m['date'])).days <= 365 for m in rows)
              for f in fixtures for t in (f['home'], f['away'])}
    movement = live_odds.movement_summary(league_id)
    form5 = last_five(data, league_id, today)
    items = []
    for m, model_rates, rates, source, prices in priced:
        model = distribution(*model_rates, rho, m['_cal'])
        d = distribution(*rates, m.get('_rho', rho)) if source != 'model' else model
        items.append(dict(date=m['date'], home=m['home'], away=m['away'], probabilities=d['probabilities'],
                          expected_goals=list(rates), over25=d['over25'], over15=d['total_goal_overs']['1.5'],
                          btts=d['btts'], top_score=d['scorelines'][0], source=source,
                          model_probabilities=model['probabilities'],
                          best=prices.get('best') if prices and source != 'model' else None,
                          movement=movement.get('|'.join((m['date'], m['home'], m['away']))),
                          thin_history=league_id != 'ucl' and min(recent[m['home']], recent[m['away']]) < 10,
                          kickoff=m.get('kickoff'), status=schedule.status(m),
                          last5=[form5.get(m['home'], []), form5.get(m['away'], [])]))
    age = results_age(data, league_id)
    result = dict(league_id=league_id, league=LEAGUES[league_id], analysis_date=today, model=MODEL['version'],
                  results_age_days=age, fresh=age is not None and age <= SEASON_FRESH_DAYS,
                  dixon_coles_rho=rho, quality=coverage(data, league_id, today), fixtures=items,
                  priced=sum(i['source'] != 'model' for i in items),
                  note='Upcoming fixtures, plus games from the last two days whose score is not in yet. Bookmaker-priced where odds exist, otherwise the model.')
    if len(_slate_cache) > 16:
        _slate_cache.clear()
    _slate_cache[key] = result
    return result


SEASON_FRESH_DAYS = 16


def results_age(data, league_id, today=None):
    """Days since the league's latest result, or None when it has none."""
    today = today or dt.date.today()
    played = [m['date'] for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None and m['date'] <= today.isoformat()]
    return (today - dt.date.fromisoformat(max(played))).days if played else None


def league_fresh(data, league_id, today=None):
    """A league's forecasts rest on current results: its latest one is within SEASON_FRESH_DAYS
    (an international break). Stale leagues stay out of Games to watch and the VIP slip."""
    age = results_age(data, league_id, today)
    return age is not None and age <= SEASON_FRESH_DAYS


def season(data, league_id):
    """Simulate the rest of the current season."""
    from simulate import simulate
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    today = dt.date.today().isoformat()
    key = _cache_key(data, league_id, today)
    if key in _season_cache:
        return _season_cache[key]
    if league_id == 'ucl':
        raise ValueError('Season projections are for league tables; they are not available for cup competitions.')
    current = coverage(data, league_id, today)['season']
    matches = [m for m in data['matches'] if m['league_id'] == league_id and m['season'] == current]
    played = [(m['home'], m['away'], *m['goals']) for m in matches if m['goals'] is not None]
    remaining = [m for m in matches if m['goals'] is None]
    added = complete_fixtures(matches, league_id)
    remaining += added
    if not remaining:
        raise ValueError(f'No remaining {current} fixtures in the source for this league.')
    _, _, priced = fixture_rates(data, league_id, remaining, today)
    rates = {(m['home'], m['away']): rates for m, _, rates, _, _ in priced}
    result = simulate(played, [(m['home'], m['away']) for m in remaining], rates, league_id)
    result.update(league_id=league_id, league=LEAGUES[league_id], season=current, analysis_date=today,
                  priced_fixtures=sum(source != 'model' for *_, source, _ in priced),
                  stale_results=coverage(data, league_id, today)['latest_result'], unscheduled_added=len(added))
    # Projections from a table that is weeks behind mislead, so the page only shows fresh ones.
    # 16 days covers an international break with no games.
    latest = result['stale_results']
    result['results_age_days'] = (dt.date.fromisoformat(today) - dt.date.fromisoformat(latest)).days if latest else None
    result['fresh'] = result['results_age_days'] is not None and result['results_age_days'] <= SEASON_FRESH_DAYS
    if added:
        result['method'] += (f' The full fixture list is not published yet, so {len(added)} unscheduled games were added '
                             'from the league format' + (' (33-game regular season; the post-split games are not modelled).'
                                                         if league_id == 'sco.1' else '.'))
    if len(_season_cache) > 8:
        _season_cache.clear()
    _season_cache[key] = result
    return result


# Meetings per pair in a regular season (Scotland: three meetings before the split).
MEETINGS = {'sco.1': 3}


def complete_fixtures(matches, league_id):
    """Games still to come that the source has not scheduled yet, derived from the league format.

    Double round robin by default: every ordered pair once. Scotland: each pair three
    times in the regular season, home advantage alternating. Undated (placed after the
    season), so they only feed the season simulation.
    """
    teams = sorted({t for m in matches for t in (m['home'], m['away'])})
    if len(teams) < 4:
        return []
    meet = MEETINGS.get(league_id, 2)
    count = {}
    for m in matches:
        count[(m['home'], m['away'])] = count.get((m['home'], m['away']), 0) + 1
    end = f"{int(max(m['season'] for m in matches)[:4]) + 1}-06-30"
    stub = lambda h, a: dict(league_id=league_id, season=matches[0]['season'], date=end, home=h, away=a, goals=None, ht=None, unscheduled=True)
    out = []
    for i, h in enumerate(teams):
        for a in teams[i + 1:]:
            have = count.get((h, a), 0) + count.get((a, h), 0)
            for k in range(have, meet):
                # alternate venues: whoever has hosted fewer of these meetings hosts the next
                home_first = count.get((h, a), 0) <= count.get((a, h), 0)
                pair = (h, a) if home_first else (a, h)
                count[pair] = count.get(pair, 0) + 1
                out.append(stub(*pair))
    return out


def parlay_candidates(data, leagues, days=7, include_today=False):
    """Every candidate leg for upcoming fixtures in the chosen leagues.

    include_today adds today's games that have not kicked off (known kickoff only)."""
    from parlay import legs_for
    today = dt.date.today().isoformat()
    until = (dt.date.today() + dt.timedelta(days=days)).isoformat()
    out = []
    for league_id in leagues:
        fixtures = [m for m in data['matches'] if m['league_id'] == league_id and m['date'] <= until and m['goals'] is None
                    and not m.get('unconfirmed') and (today < m['date'] or include_today and m['date'] == today
                                                      and m.get('kickoff') and schedule.status(m) == 'scheduled')]
        if not fixtures:
            continue
        try:
            _, rho, priced = fixture_rates(data, league_id, fixtures, today)
        except ValueError:
            continue
        for m, _, rates, source, _ in priced:
            out += legs_for(m, distribution(*rates, m.get('_rho', rho), m['_cal'] if source == 'model' else None), source)
    return out


def build_record(data):
    """Replay-and-grade the recent past, freeze upcoming forecasts, save reports/record.json."""
    import record
    from parlay import legs_for
    report = record.build(data, list(LEAGUES), fixture_rates, distribution, legs_for)
    report['live'] = record.freeze_and_grade(data, list(LEAGUES), slate, vip_slip, MODEL['version'])
    saved = json.loads(record.FILE.read_text()); saved['live'] = report['live']
    atomic_write(record.FILE, json.dumps(saved))
    return report


def update_live_record(data):
    """Freeze today's VIP slip and upcoming forecasts, grade finished ones (no replay; quick)."""
    import record
    live = record.freeze_and_grade(data, list(LEAGUES), slate, vip_slip, MODEL['version'])
    try:
        saved = json.loads(record.FILE.read_text())
    except (OSError, ValueError):
        saved = {}
    if saved:
        saved['live'] = live
        atomic_write(record.FILE, json.dumps(saved))
    return dict(live=live, vip=record.vip_ledger()['summary'])


# Leagues whose final scores reach the hosted Lab automatically (OpenFootball + OpenLigaDB).
# VIP picks come only from these, so every pick on the public record gets graded.
# The 2. Bundesliga also has a results feed but is left out: over three seasons of
# walk-forward slips its picks won 80.4% against a stated 84.1% (470 picks), while the
# other three won at or above their stated chance. No model setting closed that gap.
# Goal picks checked per league on 2025-26 and 2026-27 (tools/goal_lines_check.py): these won at
# least about what they said. Ligue 1 (said 77.0%, won 73.2%) and Serie B are left out. A league
# only joins a slip while its results are current (league_fresh), so every pick can be graded.
VIP_LEAGUES = ('en.1', 'es.1', 'de.1', 'it.1', 'nl.1', 'pt.1', 'de.2')


def vip_slip(data, n=17, days=3, per_league=6):
    """The day's VIP slip: the surest pick from each of the most predictable games.

    Only VIP_LEAGUES are used: a pick we cannot grade would sit on the record as pending forever.
    Goals first: each game's pick follows record.VIP_PRIORITY (Over 2.5, then Over 1.5, then Under 3.5),
    plus up to two strong favourites to win (record.vip_favourites) from other games;
    a game that reaches neither floor is left off, so the slip can be shorter than n.

    One leg per game, most likely selections first, at most per_league legs from any
    league, and nothing below min_p or above max_p (near-certain legs pay nothing).
    """
    import hashlib
    import record
    pool = parlay_candidates(data, [l for l in VIP_LEAGUES if l in LEAGUES and league_fresh(data, l)], days=days, include_today=True)
    by_fixture = {}
    for c in pool:
        by_fixture.setdefault(c['fixture'], []).append(c)
    ranked = [p for p in map(record.vip_pick, by_fixture.values()) if p]
    legs, per = [], {}
    for leg in sorted(ranked, key=lambda c: (record.tier(c), -c['probability'])):
        if per.get(leg['league_id'], 0) >= per_league:
            continue
        per[leg['league_id']] = per.get(leg['league_id'], 0) + 1
        legs.append(leg)
        if len(legs) == n:
            break
    legs += record.vip_favourites(by_fixture, set())          # on top of the goal picks, same games allowed
    legs.sort(key=lambda c: (c['date'], c['league_id']))
    kick = {(m['league_id'], m['date'], m['home'], m['away']): m.get('kickoff') for m in data['matches'] if m['goals'] is None}
    form5 = {}
    for leg in legs:
        leg['league'] = LEAGUES[leg['league_id']].split(' — ')[-1]
        leg['kickoff'] = kick.get((leg['league_id'], leg['date'], leg['home'], leg['away']))
        if leg['league_id'] not in form5:
            form5[leg['league_id']] = last_five(data, leg['league_id'], dt.date.today().isoformat())
        leg['last5'] = [form5[leg['league_id']].get(leg['home'], []), form5[leg['league_id']].get(leg['away'], [])]
    combined = math.prod(c['probability'] for c in legs) if legs else 0
    fingerprint = hashlib.sha1('|'.join(c['id'] for c in legs).encode()).hexdigest()[:4].upper()
    today = dt.date.today()
    return dict(code=f"FL-VIP-{today.strftime('%y%m%d')}-{fingerprint}", generated_for=today.isoformat(), legs=legs,
                combined_probability=combined, combined_fair_odds=(1 / combined) if combined else None,
                note='Fair odds are what each pick is worth by our numbers; your bookie will offer slightly less.')


def vip_export_rows(ledger):
    """Every saved VIP pick, oldest first, for a spreadsheet."""
    rows = [['slip_date', 'match_date', 'kickoff_utc', 'league', 'home', 'away', 'pick', 'our_chance', 'fair_odds',
             'final_score', 'result', 'counted_in_totals', 'saved_at']]
    for day in sorted(ledger['days'], key=lambda d: d['date']):
        for p in sorted(day['picks'], key=lambda p: (p['date'], p.get('kickoff') or '')):
            g = p.get('goals')
            rows.append([day['date'], p['date'], p.get('kickoff') or '', LEAGUES.get(p['league_id'], p['league_id']).split(' — ')[-1],
                         p['home'], p['away'], p['selection'], f"{p['probability']:.3f}", f"{1 / p['probability']:.2f}",
                         f'{g[0]}-{g[1]}' if g else '', p['status'], 'yes' if p.get('counted', True) else 'no (already on an earlier slip)',
                         day.get('frozen_at') or ''])
    return rows


def nba_export_rows(results):
    """Every saved NBA pick (winners and over/under), oldest first."""
    rows = [['date', 'tipoff_utc', 'away', 'home', 'pick', 'our_chance', 'final_score_away_home', 'result', 'rebuilt']]
    for day in sorted(results['days'], key=lambda d: d['date']):
        for x in day['picks']:
            sc = x.get('score')
            for k in ('total', 'winner'):
                pk = x.get(k)
                if not pk:
                    continue
                label = (f"{'Over' if pk['side'] == 'over' else 'Under'} {pk['line']} points") if k == 'total' else f"{pk['team']} to win"
                res = 'won' if pk.get('won') is True else 'lost' if pk.get('won') is False else x['status'] if x['status'] == 'void' else 'pending'
                rows.append([x['date'], x.get('tipoff') or '', x['away'], x['home'], label, f"{pk['probability']:.3f}",
                             f'{sc[1]}-{sc[0]}' if sc else '', res, 'yes' if x.get('rebuilt') else ''])
    return rows


def football_schedule(data, days=2):
    """{league_id: [(date, home, away)]} around today, for matching live scores to our fixtures."""
    near = {(dt.date.today() + dt.timedelta(days=d)).isoformat() for d in range(-days, days + 1)}
    schedule = {}
    for m in data['matches']:
        if m['date'] in near:
            schedule.setdefault(m['league_id'], []).append((m['date'], m['home'], m['away']))
    return schedule


def _nba_ticket_legs(today):
    """Today's saved NBA VIP picks with live state. The local Lab saves and grades them on demand;
    the hosted site only reads what the morning job saved (its disk is read-only)."""
    try:
        import nba_app
        public = nba_app.public()
        if not public:
            nba_vip.run(public=False)
        try:
            import nba_live
            live = nba_live.live().get('games', {})
        except Exception:
            live = {}
        return nba_vip.ticket_legs(public, today, live, totals=[])
    except Exception as exc:                                # NBA is an extra: never break the football ticket
        log.warning('NBA VIP picks unavailable: %s', exc)
        return [], False


def nba_vip_ticket(nba_app, n=0):
    """The basketball VIP page: today's saved NBA VIP slip with live state, plus its record.
    n > 0 keeps only the n surest picks (an accumulator)."""
    today = dt.date.today().isoformat()
    public = nba_app.public()
    if not public:
        nba_vip.run(public=False)
    try:
        import nba_live
        live = nba_live.live().get('games', {})
    except Exception:
        live = {}
    store = nba_vip.load(public)
    day = today if today in store['days'] else max((d for d in store['days'] if d <= today), default=None)
    saved = day is not None
    if saved:
        rows, _ = nba_vip.ticket_legs(public, day, live)
    else:
        p = nba_app.picks()
        rows = [dict(r, provisional=False) for r in nba_vip.ticket_legs(public, today, live, totals=p.get('totals') or [])[0]]
    if n > 0:
        rows = sorted(rows, key=lambda r: -r['probability'])[:n]
    rows = sorted(rows, key=lambda r: (r['kickoff'] or r['date']))
    count = lambda s: sum(r['status'] == s for r in rows)
    combined = math.prod(r['probability'] for r in rows) if rows else 0
    return dict(date=day or today, saved=saved, frozen_at=store['days'].get(day, {}).get('frozen_at') if day else None, legs=rows,
                summary=dict(picks=len(rows), won=count('won'), lost=count('lost'), live=count('live'),
                             scheduled=count('scheduled'), void=count('void')),
                combined_probability=combined, combined_fair_odds=(1 / combined) if combined else None,
                record=nba_vip.ledger(public))


def vip_ticket(data, n=17, live_scores=None, nba_legs=None):
    """Today's VIP slip as a live ticket: the picks as saved before kickoff, each with its state.

    States: scheduled, live (score and minute), won or lost (final score; provisional until the
    result feed grades it), void. Uses the slip frozen this morning (record.freeze_and_grade), so
    finished games stay on the ticket; before today's slip is saved, the fresh slip is shown
    and `saved` is false.
    """
    import record
    today = dt.date.today().isoformat()
    day = next((d for d in record.vip_ledger(max_days=3)['days'] if d['date'] == today), None)
    if day:
        picks = day['picks'] if n >= 17 else sorted(day['picks'], key=lambda p: -p['probability'])[:n]   # 'All' is every saved pick
        saved = dict(saved=True, frozen_at=day.get('frozen_at'))
    else:
        picks = [dict(l, status='pending') for l in vip_slip(data, n)['legs']]
        saved = dict(saved=False, frozen_at=None)
    if live_scores is None:
        try:
            import football_live
            live_scores = football_live.live(football_schedule(data)).get('games', {})
        except Exception:                                  # live scores are a nice-to-have
            live_scores = {}
    form = {}
    rows = []
    try:
        import football_odds
        odds = football_odds.load()['prices']
    except Exception:
        odds = {}
    for p in sorted(picks, key=lambda p: (p['date'], p.get('kickoff') or '', p['league_id'])):
        if p['league_id'] not in form:
            form[p['league_id']] = last_five(data, p['league_id'], today)
        row = dict(league_id=p['league_id'], league=LEAGUES.get(p['league_id'], p['league_id']).split(' — ')[-1],
                   date=p['date'], kickoff=p.get('kickoff'), home=p['home'], away=p['away'], market=p['market'],
                   selection=p['selection'], probability=p['probability'], fair_odds=1 / p['probability'],
                   source=p.get('source'), last5=[form[p['league_id']].get(p['home'], []), form[p['league_id']].get(p['away'], [])],
                   status=p['status'], score=p.get('goals'), clock='FT' if p['status'] in ('won', 'lost') else None, provisional=False,
                   best_odds=(odds.get('|'.join((p['date'], p['home'], p['away'], p['selection']))) or {}).get('latest'))
        if p['status'] == 'pending':
            lv = live_scores.get('|'.join((p['date'], p['home'], p['away'])))
            if lv and lv['status'] == 'live':
                row.update(status='live', score=lv['score'], clock=lv['clock'])
                nba_vip.settle_in_play(row, lv['score'])     # an Over 1.5 is won at the second goal
            elif lv and lv['status'] == 'final':
                row.update(status='won' if record.leg_won(p, lv['score']) else 'lost', score=lv['score'], clock='FT', provisional=True)
            else:
                row['status'] = 'scheduled'
        rows.append(dict(row, sport='football'))
    # Football only: the NBA picks have their own page (Picks, with its own VIP slip and record).
    # NBA legs join only when a caller passes them in explicitly.
    nba_saved = nba_legs is not None
    rows = rows + (nba_legs or [])
    if n < 17:       # a ready-made accumulator: the n surest picks
        rows = sorted(rows, key=lambda r: -r['probability'])[:n]
    rows = sorted(rows, key=lambda r: (r['date'], r.get('kickoff') or ''))
    count = lambda s: sum(r['status'] == s for r in rows)
    combined = math.prod(r['probability'] for r in rows) if rows else 0
    return dict(date=today, **saved, nba_saved=nba_saved, legs=rows,
                summary=dict(picks=len(rows), won=count('won'), lost=count('lost'), live=count('live'),
                             scheduled=count('scheduled'), void=count('void')),
                combined_probability=combined, combined_fair_odds=(1 / combined) if combined else None,
                note='Picks as saved before kickoff. Live scores refresh every few minutes; a result is final once the result feed confirms it.')


def backtest(data, league_id):
    from evaluation import evaluate
    from evaluation_cache import cached_evaluate
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    if os.environ.get('VERCEL'):              # read-only disk: use the daily job's copy (tools/save_backtests.py)
        try:
            return json.loads((ROOT / 'reports' / 'backtest' / f'{league_id}.json').read_text())
        except (OSError, ValueError):
            pass
    return cached_evaluate(data, league_id, evaluate)


def setup_logging():
    from logging.handlers import RotatingFileHandler
    if os.environ.get('VERCEL'):                 # read-only disk: Vercel keeps stdout logs instead
        logging.basicConfig(level=logging.INFO); return
    (ROOT / 'reports' / 'logs').mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(ROOT / 'reports' / 'logs' / 'app.log', maxBytes=2_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class Handler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        # Any unexpected failure becomes a logged 500, never a dropped connection.
        try:
            super().handle_one_request()
        except Exception:
            log.exception('Unhandled error for %s %s', getattr(self, 'command', '?'), getattr(self, 'path', '?'))
            try:
                self.send_json(dict(error='Internal error; details are in reports/logs/app.log'), 500)
            except Exception:
                pass

    def log_message(self, format, *args):
        log.info('%s %s', self.address_string(), format % args)

    def send_csv(self, rows, filename):
        import csv
        import io
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        raw = ('\ufeff' + buf.getvalue()).encode()          # BOM so Excel reads accents correctly
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Cache-Control', 'public, max-age=300')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, value, code=200, cache=None):
        raw = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        if cache:
            self.send_header('Cache-Control', cache)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            raw = (ROOT / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(raw)
        elif path in PWA_FILES:
            # Installable app: manifest, service worker and home-screen icons (pwa/).
            name, ctype, cache = PWA_FILES[path]
            raw = (ROOT / 'pwa' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', cache)
            self.end_headers()
            self.wfile.write(raw)
        elif path in ('/logo-mark.svg', '/favicon.svg'):
            raw = (ROOT / 'community' / 'web' / 'logo-mark.svg').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Cache-Control', 'max-age=3600')
            self.end_headers()
            self.wfile.write(raw)
        elif path == '/api/badges':
            import badges
            self.send_json(badges.urls())
        elif path.startswith('/badge/'):
            import badges, re as _re
            name = path.rsplit('/', 1)[-1]
            file = badges.DIR / name
            if not _re.fullmatch(r'[0-9a-f]{12}\.png', name) or not file.exists():
                return self.send_json(dict(error='Not found'), 404)
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'max-age=604800')
            self.end_headers()
            self.wfile.write(raw)
        elif path in ('/fx.js', '/motion.js'):
            raw = (ROOT / 'community' / 'web' / path.lstrip('/')).read_bytes()   # one shared copy for every page
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(raw)
        elif path == '/api/data':
            data = load()
            today = dt.date.today().isoformat()
            query = parse_qs(urlparse(self.path).query)
            league_id = query.get('league', ['en.1'])[0]
            if league_id not in LEAGUES:
                return self.send_json(dict(error='Choose a supported league.'), 400)
            self.send_json(dict(league_id=league_id, league=LEAGUES[league_id], leagues=LEAGUES,
                                teams=current_teams(data, league_id),
                                fixtures=[m for m in data['matches'] if m['league_id'] == league_id and m['date'] >= today and m['goals'] is None][:30],
                                recent=[dict(date=m['date'], home=m['home'], away=m['away'], goals=m['goals'])
                                        for m in sorted((m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None),
                                                        key=lambda m: m['date'])[-14:]][::-1],
                                fetched_at=data['fetched_at'], today=today,
                                results=len(history(data, today, league_id)),
                                supplemental_records=sum(r['league_id'] == league_id for r in load_stats(STATS)['records']),
                                quality=coverage(data, league_id, today),
                                failures=[f for f in data['failures'] if f.get('league_id') == league_id or f'/{league_id}.json' in f['url']]))
        elif path == '/api/slate':
            try:
                query = parse_qs(urlparse(self.path).query)
                self.send_json(slate(load(), query.get('league', ['en.1'])[0]))
            except ValueError as exc:
                self.send_json(dict(error=str(exc)), 400)
        elif path == '/api/nba/slate':
            import nba_app
            self.send_json(nba_app.slate())
        elif path == '/api/football/live':
            import football_live
            near = {(dt.date.today() + dt.timedelta(days=d)).isoformat() for d in (-2, -1, 0, 1, 2)}
            schedule = {}
            for m in load()['matches']:
                if m['date'] in near:
                    schedule.setdefault(m['league_id'], []).append((m['date'], m['home'], m['away']))
            value = football_live.live(schedule)
            self.send_json(value, cache=f"public, max-age=60, s-maxage={value.get('ttl', 600)}, stale-while-revalidate=120")
        elif path == '/api/nba/live':
            import nba_live
            self.send_json(nba_live.live(), cache='public, max-age=20, s-maxage=45, stale-while-revalidate=30')
        elif path == '/api/nba/picks':
            import nba_app
            self.send_json(nba_app.picks())
        elif path == '/api/nba/predict':
            import nba_app
            try:
                self.send_json(nba_app.predict({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}))
            except ValueError as exc:
                self.send_json(dict(error=str(exc)), 400)
        elif path == '/api/benchmark':
            path_ = ROOT / 'reports' / 'benchmark.json'
            self.send_json(json.loads(path_.read_text()) if path_.exists() else dict(error='No benchmark yet'))
        elif path == '/api/odds-status':
            cache = live_odds.load_cache()
            market = odds_data.load()
            self.send_json(dict(live_configured=bool(os.environ.get('ODDS_API_KEY', '').strip()),
                                live={k: {x: v[x] for x in ('fetched_at', 'events', 'matched', 'requests_remaining')}
                                      for k, v in cache.get('leagues', {}).items()},
                                football_data=dict(fetched_at=market.get('fetched_at'), records=len(market['records']),
                                                   license=market.get('license'))))
        elif path == '/api/setup':
            from lineups import match_setup
            query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            if query.get('league') not in LEAGUES or not all(query.get(k) for k in ('date', 'home', 'away')):
                return self.send_json(dict(error='league, date, home and away are required'), 400)
            try:
                dt.date.fromisoformat(query['date'])
            except ValueError:
                return self.send_json(dict(error='Invalid date'), 400)
            self.send_json(match_setup(query['league'], query['date'], query['home'], query['away']))
        elif path == '/api/nba/vip':
            import nba_app
            q = parse_qs(urlparse(self.path).query)
            try:
                n = int(q.get('n', ['0'])[0])
            except ValueError:
                n = 0
            self.send_json(nba_vip_ticket(nba_app, n), cache='public, max-age=30, s-maxage=60, stale-while-revalidate=60')
        elif path == '/api/health':
            import model_health
            self.send_json(model_health.load() or dict(error='No health report yet: it is written by the daily job.'))
        elif path == '/api/vip/export.csv':
            import record
            self.send_csv(vip_export_rows(record.vip_ledger(max_days=100000)), f'vip-record-{dt.date.today().isoformat()}.csv')
        elif path == '/api/nba/export.csv':
            import nba_app
            import nba_picks_ledger
            data, _ = nba_app._data()
            self.send_csv(nba_export_rows(nba_picks_ledger.results((data or {}).get('games', []))), f'nba-picks-{dt.date.today().isoformat()}.csv')
        elif path == '/api/record':
            import record
            saved = record.load()
            if saved:
                saved['league_names'] = LEAGUES
            self.send_json(saved or dict(error='No record yet. Run: python3 app.py record'), 200 if saved else 404)
        elif path == '/api/vip/ticket':
            q = parse_qs(urlparse(self.path).query)
            try:
                n = max(5, min(17, int(q.get('n', ['17'])[0])))
            except ValueError:
                n = 17
            self.send_json(vip_ticket(load(), n), cache='public, max-age=30, s-maxage=60, stale-while-revalidate=60')
        elif path == '/api/vip':
            q = parse_qs(urlparse(self.path).query)
            try:
                n = max(5, min(17, int(q.get('n', ['17'])[0])))
            except ValueError:
                n = 17
            self.send_json(vip_slip(load(), n))
        elif path == '/api/featured':
            from featured import featured
            period = parse_qs(urlparse(self.path).query).get('period', ['week'])[0]
            data = load()
            fresh = {k: v for k, v in LEAGUES.items() if league_fresh(data, k)}
            self.send_json(featured(data, fresh, slate, history, 'day' if period == 'day' else 'week'))
        elif path == '/api/season':
            try:
                query = parse_qs(urlparse(self.path).query)
                self.send_json(season(load(), query.get('league', ['en.1'])[0]))
            except ValueError as exc:
                self.send_json(dict(error=str(exc)), 400)
        elif path == '/api/backtest':
            try:
                query = parse_qs(urlparse(self.path).query)
                self.send_json(backtest(load(), query.get('league', ['en.1'])[0]))
            except ValueError as exc:
                self.send_json(dict(error=str(exc)), 400)
        elif path == '/api/prospective':
            from prospective import grade
            result = grade(load())
            self.send_json({key: result[key] for key in ('registered', 'pending', 'missing_result', 'overall',
                                                         'eligible_registered', 'eligible_pending', 'eligible_overall',
                                                         'by_league', 'method')})
        else:
            self.send_json(dict(error='Not found'), 404)

    def do_POST(self):
        # Only this site's own pages may post. Behind a host such as Vercel the page is
        # https and the public name can arrive as X-Forwarded-Host.
        origin = self.headers.get('Origin')
        hosts = {h for h in (self.headers.get('Host'), self.headers.get('X-Forwarded-Host')) if h}
        if origin and urlparse(origin).netloc not in hosts:
            return self.send_json(dict(error='Cross-origin request rejected'), 403)
        if urlparse(self.path).path == '/api/parlay':
            from parlay import build, MARKETS
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 20000:
                    raise ValueError('Invalid request size.')
                q = json.loads(self.rfile.read(length))
                leagues = [l for l in q.get('leagues') or list(LEAGUES) if l in LEAGUES]
                n = int(q.get('legs', 3))
                if not 1 <= n <= 20:
                    raise ValueError('Choose between 1 and 20 legs.')
                markets = [m for m in q.get('markets') or [] if m in MARKETS]
                candidates = parlay_candidates(load(), leagues, int(q.get('days', 7)))
                result = build(candidates, n, float(q.get('min_p', 0)), float(q.get('max_p', 1)), markets,
                               q.get('locked') or [], q.get('exclude') or [], int(q.get('seed', 0)), q.get('mode', 'balanced'))
                result['fixtures_available'] = len({c['fixture'] for c in candidates})
                return self.send_json(result)
            except (ValueError, TypeError) as exc:
                return self.send_json(dict(error=str(exc)), 400)
        if urlparse(self.path).path == '/api/nba/refresh':
            import nba_app
            if os.environ.get('VERCEL'):
                return self.send_json(dict(error='Refresh runs on the private Lab only.'), 400)
            try:
                return self.send_json(nba_app.refresh())
            except Exception as exc:
                log.exception('NBA refresh failed')
                return self.send_json(dict(error=f'NBA refresh failed: {exc}'), 502)
        if urlparse(self.path).path == '/api/odds/refresh':
            league = parse_qs(urlparse(self.path).query).get('league', [None])[0]
            result = live_odds.refresh(load(), [league] if league in LEAGUES else None, force=True)
            _slate_cache.clear()
            return self.send_json(dict(status=result['status'], reason=result.get('reason'), errors=result.get('errors')))
        if self.path != '/api/predict':
            return self.send_json(dict(error='Not found'), 404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 10000:
                raise ValueError('Invalid request size.')
            request = json.loads(self.rfile.read(length))
            self.send_json(predict(load(), request, load_stats(STATS)))
        except (ValueError, KeyError, TypeError) as exc:
            self.send_json(dict(error=str(exc)), 400)


if __name__ == '__main__':
    from config import load_environment
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['refresh', 'serve', 'backtest', 'import-stats', 'backfill-halftime', 'refresh-odds', 'fetch-badges', 'fetch-saudi', 'fetch-ucl', 'fetch-nba', 'record', 'vip-record'])
    parser.add_argument('--lines', action='store_true', help='fetch-nba: back-fill lines for every stored game')
    parser.add_argument('path', nargs='?', help='CSV path for import-stats')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.command == 'refresh':
        refresh()
    elif args.command == 'record':
        print(json.dumps(build_record(load()), indent=1)[:2000])
    elif args.command == 'vip-record':
        print(json.dumps(update_live_record(load()), indent=1))
    elif args.command == 'fetch-ucl':
        import ucl
        print(json.dumps(ucl.fetch()))
    elif args.command == 'fetch-nba':
        import nba, badges
        print(json.dumps(nba.fetch(lines='all' if args.lines else 'recent')))
        print(json.dumps(dict(logos=badges.fetch_nba())))
        import nba_ledger
        print(json.dumps(dict(ledger=nba_ledger.run())))
        print(json.dumps(dict(vip=nba_vip.run())))        # save today's NBA VIP picks, grade earlier ones
    elif args.command == 'fetch-saudi':
        print(json.dumps(saudi.fetch()))
    elif args.command == 'fetch-badges':
        import badges
        data = load()                    # includes clubs only football-data lists (new Serie B season)
        seasons = {lg: max(m['season'] for m in data['matches'] if m['league_id'] == lg) for lg in LEAGUES
                   if any(m['league_id'] == lg for m in data['matches'])}
        teams = sorted({(m['league_id'], t) for m in data['matches'] if m['season'] == seasons.get(m['league_id'])
                        for t in (m['home'], m['away'])})
        index = badges.fetch(teams)
        print(json.dumps(dict(teams=len(teams), with_badge=sum(1 for v in index.values() if v.get('file')))))
        print(json.dumps(dict(nba=badges.fetch_nba())))
    elif args.command == 'refresh-odds':
        data = load()
        print(json.dumps(dict(football_data=odds_data.fetch(data['matches']))))
        live = live_odds.refresh(data, force=True)
        print(json.dumps(dict(live=live['status'], errors=live.get('errors'), reason=live.get('reason'))))
    elif args.command == 'backfill-halftime':
        backfill_halftime()
    elif args.command == 'backtest':
        print(json.dumps(backtest(load(), 'en.1'), indent=2))
    elif args.command == 'import-stats':
        if not args.path:
            parser.error('import-stats requires a CSV path')
        print(json.dumps(import_csv(args.path, STATS, load()['matches']), indent=2))
    else:
        load()
        setup_logging()
        import nba_app
        nba_app.warm()
        print(f'Fairline: http://127.0.0.1:{args.port}', flush=True)
        ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
