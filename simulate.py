"""Monte Carlo season simulator.

Plays out every remaining current-season fixture many times from the same
goal rates the app shows (bookmaker-implied where prices exist, otherwise the
model).  Fixed rates understate uncertainty over months, so each simulated
season also draws a random strength shift per team (normal, sd 0.10 on the
log-rate scale), which widens long-range outcomes.  Ties are broken by points,
goal difference, then goals scored; league-specific rules such as head-to-head
are not applied.
"""
import datetime as dt
import math
import random

STRENGTH_SD = 0.10
ZONES = {  # positions are 1-based; relegation counts from the bottom
    'en.1': dict(title=1, europe=4, playoff=None, relegation=3),
    'es.1': dict(title=1, europe=4, playoff=None, relegation=3),
    'it.1': dict(title=1, europe=4, playoff=None, relegation=3),
    'de.1': dict(title=1, europe=4, playoff=16, relegation=2),
    'fr.1': dict(title=1, europe=4, playoff=16, relegation=2),
    'it.2': dict(title=2, europe=None, playoff=None, relegation=3),
    'de.2': dict(title=2, europe=None, playoff=16, relegation=2),
}


def _poisson(rng, lam):
    # Knuth's method is exact and fast for football-sized rates.
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def table(results, teams):
    rows = {t: dict(team=t, played=0, won=0, drawn=0, lost=0, gf=0, ga=0, points=0) for t in teams}
    for home, away, h, a in results:
        for team, gf, ga in ((home, h, a), (away, a, h)):
            r = rows[team]
            r['played'] += 1
            r['gf'] += gf
            r['ga'] += ga
            if gf > ga:
                r['won'] += 1; r['points'] += 3
            elif gf == ga:
                r['drawn'] += 1; r['points'] += 1
            else:
                r['lost'] += 1
    order = sorted(rows.values(), key=lambda r: (-r['points'], -(r['gf'] - r['ga']), -r['gf'], r['team']))
    for i, r in enumerate(order, 1):
        r['position'] = i
        r['gd'] = r['gf'] - r['ga']
    return order


def simulate(played, remaining, rates, league_id, runs=5000, seed=20261006):
    """played: [(home, away, hg, ag)]; remaining: [(home, away)]; rates: {(home, away): (lh, la)}."""
    teams = sorted({t for m in played for t in m[:2]} | {t for m in remaining for t in m})
    if not teams or not remaining:
        raise ValueError('No remaining fixtures to simulate for this season.')
    rng = random.Random(seed)
    n = len(teams)
    base = table(played, teams)
    index = {t: i for i, t in enumerate(teams)}
    start_pts = [0] * n; start_gd = [0] * n; start_gf = [0] * n
    for r in base:
        i = index[r['team']]
        start_pts[i], start_gd[i], start_gf[i] = r['points'], r['gd'], r['gf']
    fixtures = [(index[h], index[a], *rates[(h, a)]) for h, a in remaining]
    positions = [[0] * n for _ in range(n)]
    points_sum = [0.0] * n
    points_samples = [[] for _ in range(n)]
    for _ in range(runs):
        shift = [rng.gauss(0, STRENGTH_SD) for _ in range(n)]
        pts, gd, gf = start_pts[:], start_gd[:], start_gf[:]
        for hi, ai, lh, la in fixtures:
            d = shift[hi] - shift[ai]
            h = _poisson(rng, lh * math.exp(d))
            a = _poisson(rng, la * math.exp(-d))
            gf[hi] += h; gf[ai] += a; gd[hi] += h - a; gd[ai] += a - h
            if h > a: pts[hi] += 3
            elif h == a: pts[hi] += 1; pts[ai] += 1
            else: pts[ai] += 3
        order = sorted(range(n), key=lambda i: (-pts[i], -gd[i], -gf[i], rng.random()))
        for pos, i in enumerate(order):
            positions[i][pos] += 1
        for i in range(n):
            points_sum[i] += pts[i]
            points_samples[i].append(pts[i])
    zones = ZONES.get(league_id, dict(title=1, europe=4, playoff=None, relegation=3))
    out = []
    current = {r['team']: r for r in base}
    for t in teams:
        i = index[t]
        dist = [c / runs for c in positions[i]]
        samples = sorted(points_samples[i])
        out.append(dict(
            current=current[t], expected_points=points_sum[i] / runs,
            points_range=[samples[int(.1 * runs)], samples[int(.9 * runs) - 1]],
            expected_position=sum((p + 1) * x for p, x in enumerate(dist)),
            positions=dist, title=sum(dist[:zones['title']]),
            europe=sum(dist[:zones['europe']]) if zones['europe'] else None,
            playoff=dist[zones['playoff'] - 1] if zones['playoff'] else None,
            relegation=sum(dist[n - zones['relegation']:])))
    out.sort(key=lambda r: (-r['expected_points'], r['current']['team']))
    return dict(teams=out, runs=runs, remaining=len(remaining), played=len(played), zones=zones,
                strength_sd=STRENGTH_SD,
                method=f'{runs:,} simulated seasons. Each fixture uses the goal rates shown elsewhere in the app; '
                       f'each run also shifts every team\'s strength at random (sd {STRENGTH_SD}) to reflect '
                       'uncertainty over the season. Ties: points, goal difference, goals scored.')
