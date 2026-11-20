"""Corner forecasts for the match page, and the daily update of corner statistics.

Model (chosen walk-forward, tools/corners_lab.py, reports/corners_lab.json): each team's corners
won and conceded over the past year, weighted towards recent games (half-life 240 days), shrunk
towards the league (20 games' worth) and blended 30% with the team's shots ratings. Total corners
follow a negative binomial with the league's dispersion over the same year. On seasons the
settings never saw it beat the league's plain frequency (log loss 0.649 vs 0.653 in 2025-26,
0.652 vs 0.662 in 2026-27). Under 11.5 at 70%+ and Under 10.5 at 65%+ were on target; over-corner
picks were over-confident, so they are shown as forecasts only, never as picks.

Data: API-Football match statistics (corners and shots only), stored compactly in CORNERS_FILE
and refreshed by the daily job (`python3 corners.py`), for showing our own forecasts.
"""
import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
CORNERS_FILE = ROOT / 'corners_data.json'
LINES = (8.5, 9.5, 10.5, 11.5)
SETTINGS = dict(half_life=240, shrink=20, shots=0.3, window=365)
# (side, line, floor) that matched their stated chance on unseen seasons
VALIDATED = (('under', 11.5, .70), ('under', 10.5, .65))
_cache = {}


def load():
    try:
        stamp = CORNERS_FILE.stat().st_mtime
    except OSError:
        return []
    if _cache.get('stamp') != stamp:
        _cache.clear()
        _cache['stamp'] = stamp
        _cache['rows'] = json.loads(CORNERS_FILE.read_text())['matches']
    return _cache['rows']


def nb_tail(mu, r, line):
    """P(total > line) for a negative binomial with mean mu and size r."""
    k_max = int(line)
    if r > 1e6:
        term, cdf = pow(2.718281828459045, -mu), 0.0
        for k in range(k_max + 1):
            cdf += term
            term *= mu / (k + 1)
        return min(1 - 1e-9, max(1e-9, 1 - cdf))
    p = r / (r + mu)
    term, cdf = p ** r, 0.0
    for k in range(k_max + 1):
        cdf += term
        term *= (k + r) / (k + 1) * (1 - p)
    return min(1 - 1e-9, max(1e-9, 1 - cdf))


def name_map(rows, matches):
    """API-Football team names -> ours, by fixtures that agree on date (within a day) and score."""
    index = defaultdict(list)
    for m in matches:
        if m.get('goals') is not None:
            index[(m['league_id'], m['date'], tuple(m['goals']))].append(m)
    votes = defaultdict(Counter)
    for r in rows:
        if None in (r['goals'] or [None]):
            continue
        d = dt.date.fromisoformat(r['date'])
        for shift in (0, -1, 1):
            for m in index.get((r['league_id'], (d + dt.timedelta(days=shift)).isoformat(), tuple(r['goals'])), []):
                votes[(r['league_id'], r['home'])][m['home']] += 1
                votes[(r['league_id'], r['away'])][m['away']] += 1
    out = {}
    for key, c in votes.items():
        best, n = c.most_common(1)[0]
        if n >= 3 and n / sum(c.values()) >= .5:
            out[key] = best
    return out


def _ratings(rows, league_id, date):
    key = ('rt', league_id, date, _cache.get('stamp'))
    if key in _cache:
        return _cache[key]
    s = SETTINGS
    d0 = dt.date.fromisoformat(date)
    start = (d0 - dt.timedelta(days=s['window'])).isoformat()
    hist = [r for r in rows if r['league_id'] == league_id and start <= r['date'] < date]
    if len(hist) < 120:
        _cache[key] = None
        return None
    acc = defaultdict(lambda: [0.0] * 5)
    lg = [0.0] * 6
    totals = []
    for r in hist:
        w = 0.5 ** ((d0 - dt.date.fromisoformat(r['date'])).days / s['half_life'])
        (h, a), (sh, sa) = r['corners'], r['shots']
        totals.append(h + a)
        lg[0] += w; lg[1] += w * h; lg[2] += w * a
        if sh is not None and sa is not None:
            lg[3] += w * sh; lg[4] += w * sa; lg[5] += w
        for team, cf, ca, sf, sg, home in ((r['home'], h, a, sh, sa, True), (r['away'], a, h, sa, sh, False)):
            x = acc[team]
            x[0] += w; x[1] += w * cf / (1.1 if home else .9); x[2] += w * ca / (.9 if home else 1.1)
            if sf is not None and sg is not None:
                x[3] += w * sf; x[4] += w * sg
    mh, ma = lg[1] / lg[0], lg[2] / lg[0]
    mean, ms, k = (mh + ma) / 2, ((lg[3] + lg[4]) / (2 * lg[5]) if lg[5] else None), s['shrink']
    teams = {}
    for team, (w, cf, ca, sf, sg) in acc.items():
        att, dfn = (cf + k * mean) / ((w + k) * mean), (ca + k * mean) / ((w + k) * mean)
        if ms:
            att = (1 - s['shots']) * att + s['shots'] * (sf + k * ms) / ((w + k) * ms)
            dfn = (1 - s['shots']) * dfn + s['shots'] * (sg + k * ms) / ((w + k) * ms)
        teams[team] = (att, dfn, w)
    m = sum(totals) / len(totals)
    v = sum((t - m) ** 2 for t in totals) / (len(totals) - 1)
    out = dict(home=mh, away=ma, teams=teams, r=(m * m / (v - m)) if v > m else 1e9, games=len(hist),
               league_freq={L: sum(t > L for t in totals) / len(totals) for L in LINES})
    _cache[key] = out
    return out


def forecast(matches, league_id, home, away, date):
    """Projected corners and over/under chances for one match, or a reason it is unavailable."""
    rows = load()
    if not rows:
        return dict(status='unavailable', reason='No corner statistics loaded yet.')
    mkey = ('map', _cache.get('stamp'), len(matches))
    if mkey not in _cache:
        _cache[mkey] = name_map(rows, matches)
    ours = _cache[mkey]
    theirs = {(lg, our): api for (lg, api), our in ours.items()}
    h_api, a_api = theirs.get((league_id, home)), theirs.get((league_id, away))
    rt = _ratings(rows, league_id, date)
    if not rt:
        return dict(status='unavailable', reason='Not enough corner history for this league yet.')
    if h_api not in rt['teams'] or a_api not in rt['teams']:
        return dict(status='unavailable', reason='No corner history for one of these teams yet.')
    ah, dh, wh = rt['teams'][h_api]
    aa, da, wa = rt['teams'][a_api]
    mu_h, mu_a = rt['home'] * ah * da, rt['away'] * aa * dh
    lines = []
    for L in LINES:
        over = nb_tail(mu_h + mu_a, rt['r'], L)
        pick = next((dict(side=side, probability=1 - over if side == 'under' else over)
                     for side, line, floor in VALIDATED if line == L and (1 - over if side == 'under' else over) >= floor), None)
        lines.append(dict(line=L, over=over, under=1 - over, league_over=rt['league_freq'][L], pick=pick))
    recent = lambda team: [r for r in rows if r['league_id'] == league_id and team in (r['home'], r['away']) and r['date'] < date][-6:]
    def form(team):
        out = []
        for r in reversed(recent(team)):
            i = 0 if r['home'] == team else 1
            out.append(dict(date=r['date'], won=r['corners'][i], conceded=r['corners'][1 - i]))
        return out
    return dict(status='ok', expected=[mu_h, mu_a], expected_total=mu_h + mu_a, lines=lines,
                league_average=rt['home'] + rt['away'], games=rt['games'], form=[form(h_api), form(a_api)],
                note='Corners forecast from each side\'s corners and shots over the past year. Under 11.5 at 70%+ and '
                     'Under 10.5 at 65%+ matched their stated chance on seasons the model never saw; over-corner chances '
                     'ran a little high there, so treat them as rough guides.')


# ---------- Daily update ----------

API = 'https://v3.football.api-sports.io/'


def _get(path, params, key):
    req = Request(API + path + '?' + urlencode(params), headers={'x-apisports-key': key, 'User-Agent': 'football-lab'})
    with urlopen(req, timeout=40) as r:
        body = json.loads(r.read())
    if body.get('errors'):
        raise RuntimeError(f"API-Football: {body['errors']}")
    return body.get('response') or []


def compact(store):
    """The research cache -> the small file the site reads (corners and shots only)."""
    out = []
    for g in store.values():
        s = g['stats']
        if s[0].get('corners') is None or s[1].get('corners') is None:
            continue
        out.append(dict(league_id=g['league_id'], date=g['date'], home=g['home'], away=g['away'], goals=g['goals'],
                        corners=[int(s[0]['corners']), int(s[1]['corners'])], shots=[s[0].get('shots'), s[1].get('shots')]))
    return sorted(out, key=lambda r: (r['date'], r['league_id'], r['home']))


def update(days=4, key=None, today=None):
    """Add the last few days' finished games to CORNERS_FILE (a handful of requests)."""
    from football_live import IDS
    key = key or os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return dict(skipped='no API_FOOTBALL_KEY')
    today = today or dt.date.today()
    try:
        data = json.loads(CORNERS_FILE.read_text())
    except (OSError, ValueError):
        data = dict(matches=[])
    have = {(r['league_id'], r['date'], r['home'], r['away']) for r in data['matches']}
    by_id = {v: k for k, v in IDS.items()}
    season = today.year if today.month >= 7 else today.year - 1
    ids = []
    for league_id in ('en.1', 'es.1', 'it.1', 'de.1', 'fr.1', 'it.2', 'de.2', 'nl.1', 'pt.1'):
        for f in _get('fixtures', {'league': IDS[league_id], 'season': season, 'status': 'FT-AET-PEN',
                                   'from': (today - dt.timedelta(days=days)).isoformat(), 'to': today.isoformat()}, key):
            if (league_id, f['fixture']['date'][:10], f['teams']['home']['name'], f['teams']['away']['name']) not in have:
                ids.append(f['fixture']['id'])
    added = 0
    for i in range(0, len(ids), 20):
        for f in _get('fixtures', {'ids': '-'.join(map(str, ids[i:i + 20]))}, key):
            stats = {t['team']['id']: {s['type']: s['value'] for s in t.get('statistics') or []} for t in f.get('statistics') or []}
            h, a = f['teams']['home'], f['teams']['away']
            sh, sa = stats.get(h['id'], {}), stats.get(a['id'], {})
            if sh.get('Corner Kicks') is None or sa.get('Corner Kicks') is None:
                continue
            data['matches'].append(dict(league_id=by_id.get(f['league']['id']), date=f['fixture']['date'][:10], home=h['name'], away=a['name'],
                                        goals=[f['goals']['home'], f['goals']['away']],
                                        corners=[int(sh['Corner Kicks']), int(sa['Corner Kicks'])],
                                        shots=[sh.get('Total Shots'), sa.get('Total Shots')]))
            added += 1
    data['matches'].sort(key=lambda r: (r['date'], r['league_id'], r['home']))
    data['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    data['source'] = 'API-Football match statistics (corners and shots), for showing our forecasts'
    atomic_write(CORNERS_FILE, json.dumps(data, separators=(',', ':')))
    return dict(added=added, matches=len(data['matches']))


if __name__ == '__main__':
    import config
    config.load_environment()
    print(json.dumps(dict(corners=update())))
