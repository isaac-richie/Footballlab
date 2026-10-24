"""Bookmaker odds and match statistics from football-data.co.uk.

Kept in its own file (market_data.json) so the CC0/ODbL results dataset keeps
clean provenance.  Reuse terms for these CSVs are not verified: this data is
for private research only and must not be redistributed.

Team names differ between sources, so each football-data name is mapped to the
results dataset by voting over fixtures that agree on date (within a day) and
full-time score.  Unmapped names are reported, never guessed.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
MARKET = ROOT / 'market_data.json'
BASE = 'https://football-data.co.uk/mmz4281/'
FIXTURES_URL = 'https://football-data.co.uk/fixtures.csv'
CODES = {'en.1': 'E0', 'es.1': 'SP1', 'it.1': 'I1', 'de.1': 'D1', 'fr.1': 'F1', 'it.2': 'I2', 'de.2': 'D2'}
LICENSE = 'football-data.co.uk; reuse terms unverified; private research only, do not redistribute'

# (output key, columns). Every group is all-or-nothing so a partial set never
# masquerades as a complete market.
ODDS = {
    'pin_open': ('PSH', 'PSD', 'PSA'), 'pin_close': ('PSCH', 'PSCD', 'PSCA'),
    'avg_open': ('AvgH', 'AvgD', 'AvgA'), 'avg_close': ('AvgCH', 'AvgCD', 'AvgCA'),
    'max_open': ('MaxH', 'MaxD', 'MaxA'), 'max_close': ('MaxCH', 'MaxCD', 'MaxCA'),
    'b365_open': ('B365H', 'B365D', 'B365A'), 'b365_close': ('B365CH', 'B365CD', 'B365CA'),
    'ou25_avg_open': ('Avg>2.5', 'Avg<2.5'), 'ou25_avg_close': ('AvgC>2.5', 'AvgC<2.5'),
    'ou25_pin_open': ('P>2.5', 'P<2.5'), 'ou25_pin_close': ('PC>2.5', 'PC<2.5'),
    'ou25_max_open': ('Max>2.5', 'Max<2.5'), 'ou25_max_close': ('MaxC>2.5', 'MaxC<2.5'),
    'ah_avg_open': ('AvgAHH', 'AvgAHA'), 'ah_avg_close': ('AvgCAHH', 'AvgCAHA'),
    'ah_pin_open': ('PAHH', 'PAHA'), 'ah_pin_close': ('PCAHH', 'PCAHA'),
}
STATS = {'shots': ('HS', 'AS'), 'shots_on_target': ('HST', 'AST'), 'corners': ('HC', 'AC'),
         'fouls': ('HF', 'AF'), 'yellow_cards': ('HY', 'AY'), 'red_cards': ('HR', 'AR')}


def _number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _count(value):
    x = _number(value)
    return int(x) if x is not None and x >= 0 and x == int(x) else None


def _date(value):
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            pass
    return None


def parse_csv(raw, league_id, season, upcoming=False):
    text = raw.decode('utf-8-sig', errors='replace')
    rows = []
    code = CODES[league_id]
    for item in csv.DictReader(io.StringIO(text)):
        if upcoming and item.get('Div') != code:
            continue
        date, home, away = _date(item.get('Date', '')), (item.get('HomeTeam') or '').strip(), (item.get('AwayTeam') or '').strip()
        if not date or not home or not away or home == away:
            continue
        goals = [_count(item.get('FTHG')), _count(item.get('FTAG'))]
        goals = goals if None not in goals else None
        ht = [_count(item.get('HTHG')), _count(item.get('HTAG'))]
        ht = ht if None not in ht and goals and ht[0] <= goals[0] and ht[1] <= goals[1] else None
        odds = {}
        for key, cols in ODDS.items():
            values = [_number(item.get(c)) for c in cols]
            if all(v is not None and v > 1 for v in values):
                odds[key] = values
        for key, col in (('ah_line_open', 'AHh'), ('ah_line_close', 'AHCh')):
            line = _number(item.get(col))
            if line is not None and abs(line * 4 - round(line * 4)) < 1e-9 and abs(line) <= 6:
                odds[key] = line
        stats = {}
        for key, cols in STATS.items():
            values = [_count(item.get(c)) for c in cols]
            if None not in values:
                stats[key] = values
        rows.append(dict(league_id=league_id, season=season, date=date, fd_home=home, fd_away=away,
                         goals=goals, ht=ht, odds=odds, stats=stats, time=(item.get('Time') or None)))
    return rows


def _download(url):
    error = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'football-lab research'}), timeout=30) as response:
                return response.read()
        except Exception as exc:  # retried; the final error is surfaced
            error = exc
            time.sleep(attempt + 1)
    raise error


def _snapshot(raw):
    digest = hashlib.sha256(raw).hexdigest()
    path = ROOT / 'snapshots' / (digest + '.csv')
    if not path.exists():
        atomic_write(path, raw.decode('utf-8-sig', errors='replace'))
    return digest


def name_map(records, matches):
    """Map football-data team names to results-dataset names by fixture agreement."""
    index = defaultdict(list)
    for m in matches:
        if m['goals'] is not None:
            index[(m['league_id'], m['date'], tuple(m['goals']))].append(m)
    votes = defaultdict(Counter)
    for r in records:
        if r['goals'] is None:
            continue
        day = dt.date.fromisoformat(r['date'])
        for shift in (0, -1, 1):
            hits = index.get((r['league_id'], (day + dt.timedelta(days=shift)).isoformat(), tuple(r['goals'])), [])
            for m in hits:
                votes[(r['league_id'], r['fd_home'])][m['home']] += 1
                votes[(r['league_id'], r['fd_away'])][m['away']] += 1
    mapping, unresolved = {}, []
    for key, counter in votes.items():
        (best, n), total = counter.most_common(1)[0], sum(counter.values())
        if n >= 3 and n / total >= .5:
            mapping[key] = best
        else:
            unresolved.append(dict(league_id=key[0], name=key[1], candidates=counter.most_common(3)))
    # Two source names must never collapse onto one dataset team in a league.
    seen = defaultdict(list)
    for key, value in mapping.items():
        seen[(key[0], value)].append(key)
    for (league_id, value), keys in seen.items():
        if len(keys) > 1:
            strongest = max(keys, key=lambda k: votes[k][value])
            for k in keys:
                if k != strongest:
                    unresolved.append(dict(league_id=league_id, name=k[1], candidates=votes[k].most_common(3)))
                    del mapping[k]
    return mapping, unresolved


def fetch(matches, first_year=2021):
    """Download every league-season plus upcoming fixtures; keep failures visible."""
    records, sources, failures = [], [], []
    last = dt.date.today().year if dt.date.today().month >= 7 else dt.date.today().year - 1
    for year in range(first_year, last + 1):
        code_season = f'{str(year)[-2:]}{str(year + 1)[-2:]}'
        season = f'{year}-{str(year + 1)[-2:]}'
        for league_id, code in CODES.items():
            url = f'{BASE}{code_season}/{code}.csv'
            try:
                raw = _download(url)
                parsed = parse_csv(raw, league_id, season)
                if not parsed:
                    raise ValueError('No parsable rows')
                records += parsed
                sources.append(dict(url=url, league_id=league_id, season=season, rows=len(parsed),
                                    sha256=_snapshot(raw), checked_at=dt.datetime.now(dt.timezone.utc).isoformat()))
            except Exception as exc:
                failures.append(dict(url=url, league_id=league_id, error=str(exc)))
    try:
        raw = _download(FIXTURES_URL)
        digest = _snapshot(raw)
        for league_id in CODES:
            upcoming = parse_csv(raw, league_id, None, upcoming=True)
            for r in upcoming:
                r['upcoming'] = True
            records += upcoming
        sources.append(dict(url=FIXTURES_URL, league_id='all', rows=sum(r.get('upcoming', False) for r in records),
                            sha256=digest, checked_at=dt.datetime.now(dt.timezone.utc).isoformat()))
    except Exception as exc:
        failures.append(dict(url=FIXTURES_URL, league_id='all', error=str(exc)))
    if not sources:
        raise RuntimeError('No football-data source succeeded; existing market data kept.')
    mapping, unresolved = name_map(records, matches)
    linked = 0
    for r in records:
        h, a = mapping.get((r['league_id'], r['fd_home'])), mapping.get((r['league_id'], r['fd_away']))
        r['home'], r['away'] = h, a
        linked += bool(h and a)
    payload = dict(fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(), license=LICENSE, sources=sources,
                   failures=failures, unresolved_names=unresolved,
                   name_map={f'{k[0]}|{k[1]}': v for k, v in sorted(mapping.items())}, records=records)
    atomic_write(MARKET, json.dumps(payload))
    return dict(records=len(records), linked=linked, sources=len(sources), failures=failures,
                unresolved=len(unresolved))


def load():
    market = json.loads(MARKET.read_text()) if MARKET.exists() else dict(records=[], sources=[], license=LICENSE)
    own_names(market)
    return market


def own_names(market):
    """Keep football-data's own name for a club the results dataset never has.

    A name with no fixture votes at all (Serie B 2021-24 clubs, before the open
    feed starts) cannot be mapped, but it is still one stable identity inside
    football-data. Names that had votes but stayed ambiguous remain unlinked,
    and a fallback never takes a name another source name already maps to.
    """
    unresolved = {(u['league_id'], u['name']) for u in market.get('unresolved_names', [])}
    taken = {(k.split('|', 1)[0], v) for k, v in market.get('name_map', {}).items()}
    for r in market.get('records', []):
        for side in ('home', 'away'):
            name = r.get('fd_' + side)
            if r.get(side) or not name or (r['league_id'], name) in unresolved:
                continue
            if f"{r['league_id']}|{name}" not in market.get('name_map', {}) and (r['league_id'], name) not in taken:
                r[side] = name


def index(market, matches=None):
    """Key linked records by (league, date, home, away) of the results dataset.

    football-data dates can differ from the results source by a day, so when
    the results matches are supplied each record is re-keyed to the date of
    the same pairing within one day.
    """
    by_pair = defaultdict(list)
    for m in matches or []:
        by_pair[(m['league_id'], m['home'], m['away'])].append(m['date'])
    out = {}
    for r in market['records']:
        if not (r.get('home') and r.get('away')):
            continue
        date = r['date']
        dates = by_pair.get((r['league_id'], r['home'], r['away']))
        if dates:
            day = dt.date.fromisoformat(date)
            near = [d for d in dates if abs((dt.date.fromisoformat(d) - day).days) <= 1]
            if near:
                date = near[0]
        key = (r['league_id'], date, r['home'], r['away'])
        # Completed records win over the weekly fixtures file for the same match.
        if key not in out or not r.get('upcoming'):
            out[key] = r
    return out


def no_vig(odds):
    """Proportional margin removal; returns fair probabilities."""
    implied = [1 / o for o in odds]
    total = sum(implied)
    return [p / total for p in implied]


def _bisect(f, lo, hi):
    """Root of an increasing function on [lo, hi]."""
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def fair(odds, method='power'):
    """Margin-free probabilities. Bookmakers shade longshots more than favourites,
    which proportional removal ignores; Shin's model (an insider-trading share z)
    and the power method (q ** k) both take more margin off longshots.

    Power is the default: on 7,800 matches in 2023-27 it beat proportional removal
    on opening and closing prices, average and Pinnacle alike, by about 0.001 log
    loss (tools/accuracy_lab.py). Additive tied it but can go negative on a longshot."""
    q = [1 / o for o in odds]
    total = sum(q)
    if method == 'proportional' or total <= 1:
        return [p / total for p in q]
    if method == 'shin':
        def shin(z):
            return [(math.sqrt(z * z + 4 * (1 - z) * p * p / total) - z) / (2 * (1 - z)) for p in q]
        z = _bisect(lambda z: 1 - sum(shin(z)), 0.0, 0.4)
        p = shin(z)
    elif method == 'power':
        k = _bisect(lambda k: 1 - sum(x ** k for x in q), 1.0, 3.0)
        p = [x ** k for x in q]
    elif method == 'odds_ratio':
        c = _bisect(lambda c: 1 - sum(x / (c + x - c * x) for x in q), 1.0, 3.0)
        p = [x / (c + x - c * x) for x in q]
    elif method == 'additive':
        p = [max(1e-6, x - (total - 1) / len(q)) for x in q]
    else:
        raise ValueError(f'Unknown margin method {method}.')
    s = sum(p)
    return [x / s for x in p]
