"""Extended goal markets derived from the fitted score distribution.

Everything here is arithmetic on the same Dixon-Coles score matrix that
produces the 1X2 forecast, so no new parameters enter except the first-half
goal share, which is fitted from earlier half-time scores only.
"""
import datetime as dt
import math

MAX_GOALS = 25
HALF_MAX = 12
MIN_HALFTIME_MATCHES = 200


def poisson(lam, top=MAX_GOALS):
    p = [math.exp(-lam)]
    for k in range(1, top + 1):
        p.append(p[-1] * lam / k)
    return p


def score_matrix(lh, la, rho=0.0):
    """Normalized Dixon-Coles score grid as {(home, away): probability}."""
    def tau(h, a):
        if h == 0 and a == 0: return 1 - lh * la * rho
        if h == 0 and a == 1: return 1 + lh * rho
        if h == 1 and a == 0: return 1 + la * rho
        if h == 1 and a == 1: return 1 - rho
        return 1
    cells = {(h, a): ph * pa * tau(h, a)
             for h, ph in enumerate(poisson(lh)) for a, pa in enumerate(poisson(la))}
    if any(p <= 0 or not math.isfinite(p) for p in cells.values()):
        raise ValueError('Dixon-Coles rho creates an invalid score probability.')
    mass = sum(cells.values())
    return {k: v / mass for k, v in cells.items()}


def fair_odds(p):
    return 1 / p if p > 1e-9 else None


def _settle(value):
    """One stake at a single line: 1 win, 0 push, -1 loss."""
    return 1 if value > 1e-9 else -1 if value < -1e-9 else 0


def asian_line(grid, line, margin):
    """Settlement breakdown for an Asian line applied to margin(h, a).

    Quarter lines split the stake across the two neighbouring half lines.
    Fair odds solve expected profit = 0 given half wins/losses and pushes.
    """
    parts = [line - .25, line + .25] if abs((line * 4) % 2 - 1) < 1e-9 else [line]
    out = dict(win=0.0, half_win=0.0, push=0.0, half_loss=0.0, loss=0.0)
    won = lost = 0.0
    for (h, a), p in grid.items():
        results = [_settle(margin(h, a) + part) for part in parts]
        share = 1 / len(results)
        won += p * share * sum(r == 1 for r in results)
        lost += p * share * sum(r == -1 for r in results)
        score = sum(results) / len(results)
        key = ('win' if score == 1 else 'loss' if score == -1 else 'push' if score == 0 and all(r == 0 for r in results)
               else 'half_win' if score > 0 else 'half_loss')
        out[key] += p
    out['fair_odds'] = 1 + lost / won if won > 1e-9 else None
    out['line'] = line
    return out


def fit_first_half_share(rows, asof, half_life_days=365):
    """Time-weighted share of each side's goals scored before half-time."""
    cutoff = dt.date.fromisoformat(asof)
    totals = [0.0, 0.0, 0.0, 0.0]
    used = 0
    for m in rows:
        ht, ft = m.get('ht'), m.get('goals')
        if ht is None or ft is None or m['date'] >= asof:
            continue
        w = .5 ** (max(0, (cutoff - dt.date.fromisoformat(m['date'])).days) / half_life_days)
        totals[0] += w * ht[0]; totals[1] += w * ft[0]
        totals[2] += w * ht[1]; totals[3] += w * ft[1]
        used += 1
    if used < MIN_HALFTIME_MATCHES or not totals[1] or not totals[3]:
        return None
    return dict(home=totals[0] / totals[1], away=totals[2] / totals[3], matches=used)


def halftime_markets(lh, la, share):
    """Half markets assume independent Poisson halves (no low-score correction)."""
    h1, a1 = poisson(lh * share['home'], HALF_MAX), poisson(la * share['away'], HALF_MAX)
    h2, a2 = poisson(lh * (1 - share['home']), HALF_MAX), poisson(la * (1 - share['away']), HALF_MAX)
    first = {(h, a): h1[h] * a1[a] for h in range(HALF_MAX + 1) for a in range(HALF_MAX + 1)}
    second = {(h, a): h2[h] * a2[a] for h in range(HALF_MAX + 1) for a in range(HALF_MAX + 1)}
    m1, m2 = sum(first.values()), sum(second.values())
    first = {k: v / m1 for k, v in first.items()}
    second = {k: v / m2 for k, v in second.items()}
    sign = lambda h, a: 0 if h > a else 1 if h == a else 2
    ht_ft = [[0.0] * 3 for _ in range(3)]
    acc = dict(higher_first=0.0, higher_second=0.0, equal_halves=0.0,
               home_both_halves=0.0, away_both_halves=0.0,
               home_win_either=0.0, away_win_either=0.0,
               home_win_both=0.0, away_win_both=0.0,
               btts_first=0.0, btts_second=0.0, goal_both_halves=0.0)
    for (x1, y1), p1 in first.items():
        if p1 < 1e-12:
            continue
        for (x2, y2), p2 in second.items():
            p = p1 * p2
            if p < 1e-14:
                continue
            ht_ft[sign(x1, y1)][sign(x1 + x2, y1 + y2)] += p
            g1, g2 = x1 + y1, x2 + y2
            acc['higher_first' if g1 > g2 else 'higher_second' if g2 > g1 else 'equal_halves'] += p
            acc['home_both_halves'] += p * (x1 > 0 and x2 > 0)
            acc['away_both_halves'] += p * (y1 > 0 and y2 > 0)
            acc['home_win_either'] += p * (x1 > y1 or x2 > y2)
            acc['away_win_either'] += p * (y1 > x1 or y2 > x2)
            acc['home_win_both'] += p * (x1 > y1 and x2 > y2)
            acc['away_win_both'] += p * (y1 > x1 and y2 > x2)
            acc['btts_first'] += p * (x1 > 0 and y1 > 0)
            acc['btts_second'] += p * (x2 > 0 and y2 > 0)
            acc['goal_both_halves'] += p * (g1 > 0 and g2 > 0)
    def chance(grid, test):
        return sum(p for (h, a), p in grid.items() if test(h, a))
    labels = ('home', 'draw', 'away')
    return dict(
        first_half_share=share,
        expected_goals_first_half=[lh * share['home'], la * share['away']],
        result_first_half=[chance(first, lambda h, a: h > a), chance(first, lambda h, a: h == a), chance(first, lambda h, a: h < a)],
        result_second_half=[chance(second, lambda h, a: h > a), chance(second, lambda h, a: h == a), chance(second, lambda h, a: h < a)],
        first_half_overs={str(l): chance(first, lambda h, a, l=l: h + a > l) for l in (.5, 1.5, 2.5)},
        second_half_overs={str(l): chance(second, lambda h, a, l=l: h + a > l) for l in (.5, 1.5, 2.5)},
        ht_ft={f'{labels[i]}/{labels[j]}': ht_ft[i][j] for i in range(3) for j in range(3)},
        **acc,
        note='Halves are independent Poisson splits of the fitted goal rates; full-time totals here omit the low-score correction.')


def extended_markets(lh, la, rho=0.0, share=None):
    grid = score_matrix(lh, la, rho)
    def chance(test):
        return sum(p for (h, a), p in grid.items() if test(h, a))
    correct = [[grid[(h, a)] for a in range(6)] for h in range(6)]
    outside = [chance(lambda h, a: (h > 5 or a > 5) and h > a), chance(lambda h, a: (h > 5 or a > 5) and h == a),
               chance(lambda h, a: (h > 5 or a > 5) and h < a)]
    exact_total = {str(n): chance(lambda h, a, n=n: h + a == n) for n in range(7)}
    exact_total['7+'] = chance(lambda h, a: h + a >= 7)
    ranges = {'0-1': (0, 1), '1-2': (1, 2), '1-3': (1, 3), '2-3': (2, 3), '2-4': (2, 4),
              '3-4': (3, 4), '3-5': (3, 5), '4-6': (4, 6)}
    multigoals = {k: chance(lambda h, a, lo=lo, hi=hi: lo <= h + a <= hi) for k, (lo, hi) in ranges.items()}
    margin = {'home_by_3+': chance(lambda h, a: h - a >= 3), 'home_by_2': chance(lambda h, a: h - a == 2),
              'home_by_1': chance(lambda h, a: h - a == 1), 'score_draw': chance(lambda h, a: h == a > 0),
              'no_goal_draw': grid[(0, 0)], 'away_by_1': chance(lambda h, a: a - h == 1),
              'away_by_2': chance(lambda h, a: a - h == 2), 'away_by_3+': chance(lambda h, a: a - h >= 3)}
    results = (('home', lambda h, a: h > a), ('draw', lambda h, a: h == a), ('away', lambda h, a: h < a))
    result_btts = {f'{n}_{y}': chance(lambda h, a, r=r, b=b: r(h, a) and (h > 0 and a > 0) == b)
                   for n, r in results for y, b in (('yes', True), ('no', False))}
    result_total = {f'{n}_{s}_{line}': chance(lambda h, a, r=r, o=o, line=line: r(h, a) and (h + a > line) == o)
                    for line in (1.5, 2.5, 3.5) for n, r in results for s, o in (('over', True), ('under', False))}
    btts_total = {f'{y}_{s}': chance(lambda h, a, b=b, o=o: (h > 0 and a > 0) == b and (h + a > 2.5) == o)
                  for y, b in (('yes', True), ('no', False)) for s, o in (('over', True), ('under', False))}
    team_exact = {side: {str(n): chance(lambda h, a, n=n, i=i: (h, a)[i] == n) for n in range(3)}
                  for i, side in enumerate(('home', 'away'))}
    for i, side in enumerate(('home', 'away')):
        team_exact[side]['3+'] = chance(lambda h, a, i=i: (h, a)[i] >= 3)
    quarters = [x / 4 for x in range(-10, 11)]
    result = dict(
        correct_score=dict(grid=correct, max_goals=5, other_home=outside[0], other_draw=outside[1], other_away=outside[2]),
        exact_total=exact_total, multigoals=multigoals, winning_margin=margin,
        result_btts=result_btts, result_total=result_total, btts_total=btts_total,
        odd_even={'odd': chance(lambda h, a: (h + a) % 2 == 1), 'even': chance(lambda h, a: (h + a) % 2 == 0)},
        team_exact_goals=team_exact,
        asian_handicap=[dict(home=asian_line(grid, l, lambda h, a: h - a),
                             away=asian_line(grid, -l, lambda h, a: a - h)) for l in quarters],
        asian_total=[dict(over=asian_line(grid, -l, lambda h, a: h + a),
                          under=asian_line(grid, l, lambda h, a: -(h + a))) for l in [x / 4 for x in range(2, 23)]],
    )
    for row in result['asian_total']:
        row['line'] = -row['over']['line']
    for row in result['asian_handicap']:
        row['line'] = row['home']['line']
    result['halftime'] = halftime_markets(lh, la, share) if share else None
    # 0-10 goals per side covers all but a negligible tail; the bet builder
    # evaluates same-match combinations on this grid in the browser.
    result['grid'] = [[round(grid[(h, a)], 8) for a in range(11)] for h in range(11)]
    return result
