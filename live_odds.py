"""Live bookmaker odds from The Odds API (https://the-odds-api.com).

Optional: needs ODDS_API_KEY in .env.  One refresh costs one credit per
league per market per region (2 markets x 1 region x 7 leagues = 14), so
responses are cached on disk and refreshed at most every CACHE_MINUTES.
Event names are matched to dataset fixtures by date (within a day) and name
similarity; anything ambiguous is left unmatched rather than guessed.
"""
import datetime as dt
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'reports' / 'live_odds.json'
HISTORY = ROOT / 'reports' / 'odds_history'
SHARP_MOVE = .03  # margin-free probability change treated as a notable move
CACHE_MINUTES = 60
API = 'https://api.the-odds-api.com/v4/sports/{sport}/odds'
SPORTS = {'en.1': 'soccer_epl', 'es.1': 'soccer_spain_la_liga', 'it.1': 'soccer_italy_serie_a',
          'de.1': 'soccer_germany_bundesliga', 'fr.1': 'soccer_france_ligue_one',
          'it.2': 'soccer_italy_serie_b', 'de.2': 'soccer_germany_bundesliga2'}
NOISE = {'fc', 'cf', 'ac', 'afc', 'sc', 'ssc', 'as', 'us', 'rc', 'sv', 'vfl', 'vfb', 'tsg', 'fsv', 'club', 'de', 'calcio',
         'football', 'futbol', '1', '1899', '1900', '1901', '1907', '1909', '1913', '04', '05', '96', '1846', 'cfc'}


def _key(name):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    tokens = [t for t in re.split(r'[^a-z0-9]+', text) if t and t not in NOISE]
    return ' '.join(tokens) or text


def similarity(a, b):
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return 1.0
    ratio = difflib.SequenceMatcher(None, ka, kb).ratio()
    # Containment handles "Athletic" vs "Athletic Club"-style names; a single
    # shared word such as "Real" must not.
    ta, tb = set(ka.split()), set(kb.split())
    if ta <= tb or tb <= ta:
        ratio = max(ratio, .8)
    return ratio


def summarize_event(event):
    """Best and median prices per outcome across bookmakers."""
    h2h, totals = {'home': [], 'draw': [], 'away': []}, {}
    books = []
    for book in event.get('bookmakers', []):
        books.append(book.get('title') or book.get('key'))
        for market in book.get('markets', []):
            if market.get('key') == 'h2h':
                for o in market.get('outcomes', []):
                    side = 'home' if o['name'] == event['home_team'] else 'away' if o['name'] == event['away_team'] else 'draw'
                    if isinstance(o.get('price'), (int, float)) and o['price'] > 1:
                        h2h[side].append(dict(book=book.get('title'), price=float(o['price'])))
            elif market.get('key') == 'totals':
                for o in market.get('outcomes', []):
                    if not isinstance(o.get('price'), (int, float)) or o['price'] <= 1 or o.get('point') is None:
                        continue
                    line = totals.setdefault(str(float(o['point'])), {'over': [], 'under': []})
                    line['over' if o['name'].lower() == 'over' else 'under'].append(dict(book=book.get('title'), price=float(o['price'])))
    def stats(prices):
        if not prices:
            return None
        values = sorted(p['price'] for p in prices)
        best = max(prices, key=lambda p: p['price'])
        return dict(best=best['price'], best_book=best['book'], median=values[len(values) // 2], books=len(values))
    out = dict(books=books, h2h={k: stats(v) for k, v in h2h.items()},
               totals={line: {k: stats(v) for k, v in sides.items()} for line, sides in totals.items()},
               all_h2h={k: sorted(v, key=lambda p: -p['price']) for k, v in h2h.items()})
    if not all(out['h2h'].values()):
        out['h2h'] = None
    return out


def match_events(events, fixtures):
    """Pair API events with dataset fixtures; returns {(date, home, away): event}."""
    matched = {}
    for event in events:
        start = dt.datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00')).date()
        candidates = [f for f in fixtures if abs((dt.date.fromisoformat(f['date']) - start).days) <= 1]
        scored = sorted(((min(similarity(event['home_team'], f['home']), similarity(event['away_team'], f['away'])), f)
                         for f in candidates), key=lambda x: -x[0])
        if not scored or scored[0][0] < .6 or (len(scored) > 1 and scored[1][0] > scored[0][0] - .05):
            continue
        f = scored[0][1]
        matched[(f['date'], f['home'], f['away'])] = dict(event_id=event.get('id'), commence_time=event['commence_time'],
                                                          api_home=event['home_team'], api_away=event['away_team'],
                                                          **summarize_event(event))
    return matched


def _fetch(sport, key):
    query = urlencode(dict(apiKey=key, regions='eu,uk', markets='h2h,totals', oddsFormat='decimal'))
    with urlopen(Request(API.format(sport=sport) + '?' + query, headers={'User-Agent': 'football-lab'}), timeout=20) as r:
        remaining = r.headers.get('x-requests-remaining')
        return json.loads(r.read()), remaining


def load_cache():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return dict(leagues={})


def refresh(data, leagues=None, force=False):
    """Refresh stale leagues; never raises for a missing key, only reports it."""
    key = os.environ.get('ODDS_API_KEY', '').strip()
    cache = load_cache()
    if not key:
        return dict(status='unconfigured', reason='Add ODDS_API_KEY to .env for live odds.', cache=cache)
    now = dt.datetime.now(dt.timezone.utc)
    errors = {}
    for league_id in leagues or SPORTS:
        entry = cache['leagues'].get(league_id)
        if entry and not force and (now - dt.datetime.fromisoformat(entry['fetched_at'])).total_seconds() < CACHE_MINUTES * 60:
            continue
        try:
            events, remaining = _fetch(SPORTS[league_id], key)
        except Exception as exc:
            errors[league_id] = str(exc).replace(key, '***')
            continue
        fixtures = [m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is None]
        matched = match_events(events, fixtures)
        record_history(league_id, now.isoformat(), matched)
        cache['leagues'][league_id] = dict(fetched_at=now.isoformat(), events=len(events), matched=len(matched),
                                           requests_remaining=remaining,
                                           odds={'|'.join(k): v for k, v in matched.items()})
    atomic_write(CACHE, json.dumps(cache))
    return dict(status='ok' if not errors else 'partial', errors=errors, cache=cache)


def lookup(cache, league_id, date, home, away):
    entry = cache.get('leagues', {}).get(league_id)
    if not entry:
        return None
    found = entry['odds'].get('|'.join((date, home, away)))
    if found:
        found = dict(found, fetched_at=entry['fetched_at'])
    return found


def _fair(odds):
    implied = [1 / o for o in odds]
    total = sum(implied)
    return [p / total for p in implied]


def record_history(league_id, fetched_at, matched, directory=None):
    """Append one snapshot of median 1X2 prices per fixture (JSON lines)."""
    directory = Path(directory or HISTORY)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = {'|'.join(k): [v['h2h'][s]['median'] for s in ('home', 'draw', 'away')]
                for k, v in matched.items() if v.get('h2h')}
    with open(directory / f'{league_id}.jsonl', 'a') as handle:
        handle.write(json.dumps(dict(t=fetched_at, odds=snapshot)) + '\n')


def history(league_id, directory=None):
    path = Path(directory or HISTORY) / f'{league_id}.jsonl'
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def movement(league_id, key, directory=None):
    """Price path for one fixture: [{t, odds, fair}] oldest first."""
    return [dict(t=s['t'], odds=s['odds'][key], fair=_fair(s['odds'][key]))
            for s in history(league_id, directory) if key in s['odds']]


def movement_summary(league_id, directory=None):
    """First-to-latest change in margin-free probability for every tracked fixture."""
    first, last = {}, {}
    for snap in history(league_id, directory):
        for key, odds in snap['odds'].items():
            first.setdefault(key, (snap['t'], odds))
            last[key] = (snap['t'], odds)
    out = {}
    for key in last:
        if first[key][0] == last[key][0]:
            continue
        a, b = _fair(first[key][1]), _fair(last[key][1])
        change = [y - x for x, y in zip(a, b)]
        out[key] = dict(since=first[key][0], change=change, sharp=max(abs(c) for c in change) >= SHARP_MOVE)
    return out
