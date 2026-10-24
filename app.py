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
from model import SPEC as MODEL, fit_rates, fit_team_rates, fit_dixon_coles
from markets import extended_markets, fit_first_half_share
from implied import implied_rates, implied_rates_rho
from count_markets import count_markets
import odds_data
import live_odds
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
}


def refresh():
    # Replace complete league-season partitions only after validation.
    existing = json.loads(DATA.read_text()) if DATA.exists() else {'matches': [], 'sources': []}
    matches, sources, failures = list(existing['matches']), list(existing['sources']), []
    sources = {s['url']: s for s in sources if s.get('league_id') != 'de.2'}
    successes = 0
    for year in range(2021, dt.date.today().year + 1):
        season = f'{year}-{str(year + 1)[-2:]}'
        for league_id, league_name in LEAGUES.items():
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
    unique = {(m['league_id'], m['date'], m['home'], m['away']): m for m in matches}
    payload = dict(fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   license='per-source', sources=list(sources.values()), failures=failures,
                   matches=sorted(unique.values(), key=lambda m: m['date']))
    atomic_write(DATA, json.dumps(payload, indent=2))
    print(json.dumps(dict(matches=len(unique), sources=len(sources), failures=failures)))


def backfill_halftime():
    """Attach half-time scores from the exact raw snapshots behind current partitions."""
    data = load()
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
    data = json.loads(DATA.read_text())
    canonicalize(data['matches'])
    if fill_gaps:
        fill_missing_results(data)
    return data


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
    return filled


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


def distribution(lh, la, rho=0.0):
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
        _market_cache.update(stamp=key,
                             index=odds_data.index(odds_data.load(), data['matches']))
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
    lh, la, counts, fit = fit_rates(rows, home, away, asof)
    rho = fit['dixon_coles_rho']
    model_view = distribution(lh, la, rho)
    fixture_date = fixture_date_for(data, league_id, home, away, asof, request.get('fixture_date'))
    prices = market_prices(data, request, league_id, home, away, asof, fixture_date)
    pricing = dict(source='model', label='Our model only (no bookie prices for this match yet)', fixture_date=fixture_date)
    rates = (lh, la)
    if prices:
        mh, ma, mrho, error = market_fit(prices, rho, (lh, la))
        if error < .03:
            rates, rho = (mh, ma), mrho
            pricing = dict(prices, fixture_date=fixture_date, fit_error=error,
                           note='Every number on this page is worked out from the bookies\' prices, with their cut removed.')
        else:
            pricing['note'] = f'Bookmaker prices found but could not be matched by a goal model (error {error:.3f}); using the model.'
    result = distribution(*rates, rho)
    share = fit_first_half_share(rows, asof)
    result['markets'] = extended_markets(*rates, rho, share)
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
    if min(recent_counts.values()) < 10:
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
    p = odds_data.no_vig(prices['h2h'])
    if prices.get('ou25'):
        return implied_rates_rho(p, odds_data.no_vig(prices['ou25'])[0], rho, start)
    mh, ma, error = implied_rates(p, None, rho, start)
    return mh, ma, rho, error


def fixture_rates(data, league_id, fixtures, today):
    """One model fit at today's cutoff; bookmaker-implied rates wherever prices exist."""
    rows = history(data, today, league_id)
    teams = {t for m in fixtures for t in (m['home'], m['away'])}
    expected, _ = fit_team_rates(rows, today, sorted(teams))
    rho, _ = fit_dixon_coles(rows, today, expected)
    priced = []
    for m in fixtures:
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


def slate(data, league_id, limit=40):
    """Forecast every upcoming fixture in a league from one fit at today's cutoff."""
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    today = dt.date.today().isoformat()
    key = _cache_key(data, league_id, today)
    if key in _slate_cache:
        return _slate_cache[key]
    fixtures = [m for m in data['matches'] if m['league_id'] == league_id and m['date'] > today and m['goals'] is None][:limit]
    rows, rho, priced = fixture_rates(data, league_id, fixtures, today)
    recent = {t: sum(t in (m['home'], m['away']) and
                     (dt.date.fromisoformat(today) - dt.date.fromisoformat(m['date'])).days <= 365 for m in rows)
              for f in fixtures for t in (f['home'], f['away'])}
    movement = live_odds.movement_summary(league_id)
    items = []
    for m, model_rates, rates, source, prices in priced:
        model = distribution(*model_rates, rho)
        d = distribution(*rates, m.get('_rho', rho)) if source != 'model' else model
        items.append(dict(date=m['date'], home=m['home'], away=m['away'], probabilities=d['probabilities'],
                          expected_goals=list(rates), over25=d['over25'], over15=d['total_goal_overs']['1.5'],
                          btts=d['btts'], top_score=d['scorelines'][0], source=source,
                          model_probabilities=model['probabilities'],
                          best=prices.get('best') if prices and source != 'model' else None,
                          movement=movement.get('|'.join((m['date'], m['home'], m['away']))),
                          thin_history=min(recent[m['home']], recent[m['away']]) < 10))
    result = dict(league_id=league_id, league=LEAGUES[league_id], analysis_date=today, model=MODEL['version'],
                  dixon_coles_rho=rho, quality=coverage(data, league_id, today), fixtures=items,
                  priced=sum(i['source'] != 'model' for i in items),
                  note='Fixtures after today only. Bookmaker-priced where odds exist, otherwise the model.')
    if len(_slate_cache) > 16:
        _slate_cache.clear()
    _slate_cache[key] = result
    return result


def season(data, league_id):
    """Simulate the rest of the current season."""
    from simulate import simulate
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    today = dt.date.today().isoformat()
    key = _cache_key(data, league_id, today)
    if key in _season_cache:
        return _season_cache[key]
    current = coverage(data, league_id, today)['season']
    matches = [m for m in data['matches'] if m['league_id'] == league_id and m['season'] == current]
    played = [(m['home'], m['away'], *m['goals']) for m in matches if m['goals'] is not None]
    remaining = [m for m in matches if m['goals'] is None]
    if not remaining:
        raise ValueError(f'No remaining {current} fixtures in the source for this league.')
    _, _, priced = fixture_rates(data, league_id, remaining, today)
    rates = {(m['home'], m['away']): rates for m, _, rates, _, _ in priced}
    result = simulate(played, [(m['home'], m['away']) for m in remaining], rates, league_id)
    result.update(league_id=league_id, league=LEAGUES[league_id], season=current, analysis_date=today,
                  priced_fixtures=sum(source != 'model' for *_, source, _ in priced),
                  stale_results=coverage(data, league_id, today)['latest_result'])
    if len(_season_cache) > 8:
        _season_cache.clear()
    _season_cache[key] = result
    return result


def parlay_candidates(data, leagues, days=7):
    """Every candidate leg for upcoming fixtures in the chosen leagues."""
    from parlay import legs_for
    today = dt.date.today().isoformat()
    until = (dt.date.today() + dt.timedelta(days=days)).isoformat()
    out = []
    for league_id in leagues:
        fixtures = [m for m in data['matches'] if m['league_id'] == league_id and today < m['date'] <= until and m['goals'] is None]
        if not fixtures:
            continue
        try:
            _, rho, priced = fixture_rates(data, league_id, fixtures, today)
        except ValueError:
            continue
        for m, _, rates, source, _ in priced:
            out += legs_for(m, distribution(*rates, m.get('_rho', rho)), source)
    return out


def backtest(data, league_id):
    from evaluation import evaluate
    from evaluation_cache import cached_evaluate
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    return cached_evaluate(data, league_id, evaluate)


def setup_logging():
    from logging.handlers import RotatingFileHandler
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

    def send_json(self, value, code=200):
        raw = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
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
        elif path in ('/logo-mark.svg', '/favicon.svg'):
            raw = (ROOT / 'community' / 'web' / 'logo-mark.svg').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Cache-Control', 'max-age=3600')
            self.end_headers()
            self.wfile.write(raw)
        elif path == '/fx.js':
            raw = (ROOT / 'community' / 'web' / 'fx.js').read_bytes()   # one shared copy for every page
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
                                teams=sorted({m[k] for m in data['matches'] if m['league_id'] == league_id for k in ('home', 'away')}),
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
        elif path == '/api/featured':
            from featured import featured
            period = parse_qs(urlparse(self.path).query).get('period', ['week'])[0]
            self.send_json(featured(load(), LEAGUES, slate, history, 'day' if period == 'day' else 'week'))
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
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
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
    parser.add_argument('command', choices=['refresh', 'serve', 'backtest', 'import-stats', 'backfill-halftime', 'refresh-odds'])
    parser.add_argument('path', nargs='?', help='CSV path for import-stats')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.command == 'refresh':
        refresh()
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
        print(f'Football Lab: http://127.0.0.1:{args.port}', flush=True)
        ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
