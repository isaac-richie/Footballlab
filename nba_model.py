"""NBA points model: one joint distribution of both teams' scores, every market read from it.

Ratings. Each team's regulation points (quarters 1-4) are modelled as
    league level + home edge/2 + own offence - opponent defence + rest effects
and fitted by time-weighted ridge least squares on earlier games only.
Overtime points are left out of the fit; they follow from the tie mass below.

Distribution. Regulation scores are a discretised bivariate normal around those
expectations; the residual spread and the correlation between the two teams'
scores (fast games lift both) were measured walk-forward (`tools/nba_lab.py`).
A regulation tie goes to overtime, played as five-minute periods with their own
measured scoring, repeated while still level. Moneyline, spread, totals, team
totals, margins and combos all come from the same final-score grid, so combined
markets keep the dependence between margin and total.

Pricing. Where a bookmaker line exists, its margin-free spread and total
probabilities set the two expectations (the line is sharper than any rating in
testing); the model's own view is kept alongside for comparison.
"""
import datetime as dt
import math
from statistics import NormalDist

N = NormalDist()

# Fixed settings, chosen on 2023-24 and 2024-25 with earlier games only and checked
# once on 2025-26 (tools/nba_lab.py; summary in reports/nba_lab.json).
#   market  share of each past game's target taken from its closing line (the regulation
#           points the spread and total implied) instead of the score. Lines already
#           hold injuries and rest, and are far less noisy than one result, so ratings
#           fitted to them follow a team's real strength faster. Games with no stored
#           line use the score alone.
#   gap     days taken off the age of games played before the summer break, so last
#           season still counts in October; `carry` then scales those games.
# Chosen on 2023-25: margin RMS error 14.24 -> 14.06 and total 18.44 -> 18.20; on the
# 2025-26 hold-out 14.61 -> 14.43 and 18.94 -> 18.88 (closing line: 14.07 and 18.23).
SETTINGS = dict(half_life=15, ridge=0.5, carry=0.5, gap=115, market=0.7, window=400, b2b=True)
# Width of the regulation score distribution, in margin/total terms:
#   margin  sd of the home-minus-away margin around its expectation
#   total   sd of the combined score
#   link    correlation between the favourite's margin and the total (a favourite
#           running away with it tends to come with more or fewer points)
#   slope   change in margin sd per point of expected margin beyond 6 (blowouts
#           and close games are not equally predictable)
# Model ratings miss by more than a closing line does, so each source has its own
# width; both are tuned on the log loss of every priced market (tools/nba_calib.py).
MODEL_WIDTH = dict(margin=14.7, total=18.0, link=0.0, slope=0.0, stretch=1.0)
# LINE_WIDTH tuned on 2023-25 (tools/nba_calib.py). Margin 12.0 and 12.5 tied there; the wider one
# is kept because 2025-26 showed 12.0 slightly overconfident on spreads and moneyline.
LINE_WIDTH = dict(margin=12.5, total=17.6, link=0.1, slope=-0.1)
SD, RHO = 11.6, 0.20      # equal-variance summary of MODEL_WIDTH, kept for reports
OT = dict(mean=11.0, sd=3.8, rho=0.07)   # points per team per overtime period (2023-25: 140 periods)
PERIOD_RATIO = 5 / 48
# End-game shape of the regulation margin. Trailing teams foul and play for the tie,
# so level scores after 48 minutes are about twice as common as a smooth curve says
# and one-point margins rarer. Multipliers measured walk-forward (observed / predicted
# by margin, tools/nba_lab.py); the grid is renormalised after applying them.
MARGIN_SHAPE = {0: 2.0, 1: .7, -1: .7}


def regulation(game):
    """(home, away) regulation points, or None when quarter scores are missing."""
    p = game.get('periods')
    if p and len(p[0]) >= 4 and len(p[1]) >= 4:
        return sum(p[0][:4]), sum(p[1][:4])
    if game.get('score') and not p:
        return None
    return None


def target(game, market=0.0):
    """(home, away) regulation points a past game teaches the ratings: the score,
    blended with what its closing line expected when one is stored."""
    reg = regulation(game)
    close = (game.get('line') or {}).get('close') or {}
    if not market or close.get('spread') is None or close.get('total') is None:
        return reg
    imp = implied(close, reg)
    if not imp:
        return reg
    return market * imp[0] + (1 - market) * reg[0], market * imp[1] + (1 - market) * reg[1]


def back_to_back(games):
    """{(game id, side): 1 if that team also played the previous day}."""
    last, out = {}, {}
    for g in sorted(games, key=lambda g: (g['date'], g['id'])):
        day = dt.date.fromisoformat(g['date'])
        for side, team in ((0, g['home']), (1, g['away'])):
            prev = last.get(team)
            out[(g['id'], side)] = int(prev is not None and (day - prev).days == 1)
            last[team] = day
    return out


def _solve(a, b):
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        piv = m[c][c]
        if abs(piv) < 1e-12:
            continue
        for r in range(c + 1, n):
            f = m[r][c] / piv
            if f:
                row, top = m[r], m[c]
                for k in range(c, n + 1):
                    row[k] -= f * top[k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))
        x[r] = s / m[r][r] if abs(m[r][r]) > 1e-12 else 0.0
    return x


def fit(games, asof, rest=None, settings=None):
    """Ratings from final games strictly before `asof` (ISO date)."""
    s = dict(SETTINGS, **(settings or {}))
    day = dt.date.fromisoformat(asof)
    lo = (day - dt.timedelta(days=s['window'])).isoformat()
    rows = [g for g in games if g['status'] == 'final' and lo <= g['date'] < asof and regulation(g)]
    if len(rows) < 100:
        raise ValueError('Too few earlier NBA games to fit ratings.')
    season_now = max(g['season'] for g in rows)
    summer = dt.date(day.year if day.month >= 8 else day.year - 1, 8, 1).isoformat()
    teams = sorted({t for g in rows for t in (g['home'], g['away'])})
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    n = 2 + 2 * T + 2                     # level, home edge, offence, defence, b2b for, b2b against
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    rest = rest if rest is not None else back_to_back(games)
    wsum = 0.0
    for g in rows:
        age = (day - dt.date.fromisoformat(g['date'])).days
        earlier = g['date'] < summer          # played before this season's summer break
        if earlier:
            age = max(0, age - s.get('gap', 0))
        w = 0.5 ** (age / s['half_life']) * (s['carry'] if earlier or g['season'] < season_now else 1.0)
        h, a = target(g, s.get('market', 0))
        home_edge = 0 if g['neutral'] else 0.5
        for side, pts in ((0, h), (1, a)):
            me, opp = (g['home'], g['away']) if side == 0 else (g['away'], g['home'])
            x = {0: 1.0, 1: home_edge if side == 0 else -home_edge, 2 + idx[me]: 1.0, 2 + T + idx[opp]: -1.0}
            bf, ba = (rest.get((g['id'], side), 0), rest.get((g['id'], 1 - side), 0)) if s['b2b'] else (0, 0)
            if bf:
                x[2 + 2 * T] = 1.0
            if ba:
                x[3 + 2 * T] = 1.0
            items = [(k, v) for k, v in x.items() if v]
            for i, vi in items:
                b[i] += w * vi * pts
                row = A[i]
                for j, vj in items:
                    row[j] += w * vi * vj
            wsum += w
    for k in range(2, 2 + 2 * T):
        A[k][k] += s['ridge']
    for k in (2 + 2 * T, 3 + 2 * T):
        A[k][k] += 1.0
    x = _solve(A, b)
    return dict(asof=asof, level=x[0], home=x[1], offence={t: x[2 + i] for t, i in idx.items()},
                defence={t: x[2 + T + i] for t, i in idx.items()}, b2b_for=x[2 + 2 * T], b2b_against=x[3 + 2 * T],
                games=len(rows), effective_weight=wsum / 2, settings=s)


def expected(r, home, away, neutral=False, b2b=(0, 0)):
    """Expected regulation points (home, away); unknown teams sit at league average."""
    he = 0 if neutral else r['home'] / 2
    o, d = r['offence'], r['defence']
    h = r['level'] + he + o.get(home, 0) - d.get(away, 0) + b2b[0] * r['b2b_for'] + b2b[1] * r['b2b_against']
    a = r['level'] - he + o.get(away, 0) - d.get(home, 0) + b2b[1] * r['b2b_for'] + b2b[0] * r['b2b_against']
    return h, a


def _bvn(mh, ma, sd, rho, lo_h, hi_h, lo_a, hi_a):
    """Discretised bivariate normal on integer cells, normalised to 1.

    Along each row the density ratio between neighbours changes by a constant
    factor, so a row costs two multiplications per cell instead of an exp.
    """
    k = 1 / (2 * (1 - rho * rho))
    d = 1 / sd
    step2 = math.exp(-2 * k * d * d)
    out, total = {}, 0.0
    for x in range(lo_h, hi_h + 1):
        u = (x - mh) * d
        v = (lo_a - ma) * d
        p = math.exp(-k * (u * u - 2 * rho * u * v + v * v))
        r = math.exp(-k * (2 * v * d + d * d) + 2 * k * rho * u * d)
        for y in range(lo_a, hi_a + 1):
            if p > 1e-11:
                out[(x, y)] = p
                total += p
            p *= r
            r *= step2
    return {c: p / total for c, p in out.items()}


def stretch(means, k):
    """Scale the expected margin by k, keeping the total. Ridge ratings pull every team
    toward average, so their margins come out too small; `stretch` in MODEL_WIDTH undoes it."""
    c, e = (means[0] + means[1]) / 2, (means[0] - means[1]) / 2 * k
    return c + e, c - e


def team_params(mh, ma, width):
    """(sd_home, sd_away, rho) of the regulation scores for a given width."""
    em = mh - ma
    sm = max(6.0, width['margin'] + width.get('slope', 0.0) * (abs(em) - 6))
    st = width['total']
    c = width.get('link', 0.0) * (1 if em > 0 else -1 if em < 0 else 0)
    vh = (st * st + sm * sm + 2 * c * st * sm) / 4
    va = (st * st + sm * sm - 2 * c * st * sm) / 4
    cov = (st * st - sm * sm) / 4
    return math.sqrt(vh), math.sqrt(va), cov / math.sqrt(vh * va)


def distribution(mh, ma, width=None, ot=OT, shape=MARGIN_SHAPE):
    """Final-score grid {(home, away): p} including overtime, plus regulation summary."""
    sh, sa, rho = team_params(mh, ma, width or MODEL_WIDTH)
    # Regulation grid in one pass: row recurrence for the bivariate normal (see _bvn),
    # end-game reshape near a level score, ties set aside for overtime.
    wh, wa = int(4.3 * sh), int(4.3 * sa)
    lo_h, hi_h, lo_a, hi_a = max(0, round(mh) - wh), round(mh) + wh, max(0, round(ma) - wa), round(ma) + wa
    k = 1 / (2 * (1 - rho * rho))
    dh, d = 1 / sh, 1 / sa
    step2 = math.exp(-2 * k * d * d)
    shape = shape or {}
    final, ties, z, reg_home = {}, {}, 0.0, 0.0
    for x in range(lo_h, hi_h + 1):
        u = (x - mh) * dh
        v = (lo_a - ma) * d
        p = math.exp(-k * (u * u - 2 * rho * u * v + v * v))
        r = math.exp(-k * (2 * v * d + d * d) + 2 * k * rho * u * d)
        for y in range(lo_a, hi_a + 1):
            if p > 1e-11:
                q = p * shape[x - y] if x - y in shape else p
                z += q
                if x == y:
                    ties[x] = q
                else:
                    final[(x, y)] = q
                    if x > y:
                        reg_home += q
            p *= r
            r *= step2
    final = {c: q / z for c, q in final.items()}
    ties = {t: q / z for t, q in ties.items()}
    reg_home /= z
    reg_tie = sum(ties.values())
    level = (mh + ma) / 2 or 1
    # One overtime period, scaled to the two sides' scoring rates.
    om_h, om_a = ot['mean'] * mh / level, ot['mean'] * ma / level
    period = _bvn(om_h, om_a, ot['sd'], ot['rho'], 0, int(om_h + 5 * ot['sd']), 0, int(om_a + 5 * ot['sd']))
    period = [(i, j, q) for (i, j), q in period.items() if q > 1e-7]
    p_ot = reg_tie
    for n in range(4):
        nxt = {}
        for t, p in ties.items():
            if p < 1e-9:
                continue
            for i, j, q in period:
                if i == j:
                    nxt[t + i] = nxt.get(t + i, 0) + p * q
                else:
                    c = (t + i, t + j)
                    final[c] = final.get(c, 0) + p * q
        ties = nxt
        if not ties:
            break
    for t, p in ties.items():          # vanishing mass after four overtimes: split evenly
        final[(t + 1, t)] = final.get((t + 1, t), 0) + p / 2
        final[(t, t + 1)] = final.get((t, t + 1), 0) + p / 2
    return dict(grid=final, regulation=[reg_home, reg_tie, 1 - reg_home - reg_tie], overtime=p_ot)


def _half(x):
    return math.floor(x) + .5


def markets(dist, main_spread=None, main_total=None):
    """Every market from one final-score grid. Lines are home-perspective spreads."""
    g = dist['grid']
    margin, total, team_h, team_a = {}, {}, {}, {}
    for (x, y), p in g.items():
        margin[x - y] = margin.get(x - y, 0) + p
        total[x + y] = total.get(x + y, 0) + p
        team_h[x] = team_h.get(x, 0) + p
        team_a[y] = team_a.get(y, 0) + p
    mean = lambda d: sum(k * p for k, p in d.items())
    eh, ea, em, et = mean(team_h), mean(team_a), mean(margin), mean(total)
    over = lambda d, line: sum(p for k, p in d.items() if k > line)
    under = lambda d, line: sum(p for k, p in d.items() if k < line)
    p_home = over(margin, 0)
    spread0 = main_spread if main_spread is not None else -_half(em) if abs(em) >= .5 else -.5
    total0 = main_total if main_total is not None else _half(et)

    def cover(line):                 # home with `line` points: wins, push, loses
        return [over(margin, -line), margin.get(-line, 0) if float(line).is_integer() else 0.0, under(margin, -line)]

    def ou(line, d=total):
        return [over(d, line), d.get(line, 0) if float(line).is_integer() else 0.0, under(d, line)]

    base = round(spread0 * 2) / 2
    spreads = {str(l): cover(l) for l in [base + k for k in (-6, -4.5, -3, -2, -1.5, -1, -.5, 0, .5, 1, 1.5, 2, 3, 4.5, 6)]}
    tb = math.floor(total0) + .5
    totals = {str(l): ou(l) for l in [tb + k for k in range(-15, 16, 1)]}

    def team_lines(d, m):
        b0 = math.floor(m) + .5
        return {str(b0 + k): over(d, b0 + k) for k in range(-8, 9, 2)}

    bands = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 999)]
    win_margin = dict(home={f'{a}-{b}' if b < 999 else f'{a}+': sum(margin.get(k, 0) for k in range(a, b + 1)) for a, b in bands},
                      away={f'{a}-{b}' if b < 999 else f'{a}+': sum(margin.get(-k, 0) for k in range(a, b + 1)) for a, b in bands})
    # Combos at the main spread and total, from the joint grid (one pass).
    T0, S0 = total0, spread0
    mlt, stt = [0.0] * 4, [0.0] * 4          # home_over, home_under, away_over, away_under
    for (x, y), p in g.items():
        t = x + y
        if t == T0:
            continue
        o = 0 if t > T0 else 1
        mlt[o if x > y else 2 + o] += p
        c = x - y + S0
        if c:
            stt[o if c > 0 else 2 + o] += p
    names = ('home_over', 'home_under', 'away_over', 'away_under')
    combos = dict(total_line=T0, spread_line=S0, moneyline_total=dict(zip(names, mlt)), spread_total=dict(zip(names, stt)))
    tops = sorted(g.items(), key=lambda kv: -kv[1])[:6]
    lo_t, hi_t = int(et - 45), int(et + 45)
    total_bands = {}
    for a in range(5 * (lo_t // 5), hi_t, 5):
        p = sum(total.get(k, 0) for k in range(a, a + 5))
        if p > .002:
            total_bands[f'{a}-{a + 4}'] = p
    return dict(
        expected_points=[eh, ea], expected_total=et, expected_margin=em,
        moneyline=[p_home, 1 - p_home], regulation=dist['regulation'], overtime=dist['overtime'],
        main_spread=S0, main_total=T0, spread=cover(S0), total=ou(T0),
        spreads=spreads, totals=totals, total_bands=total_bands,
        team_totals=dict(home=team_lines(team_h, eh), away=team_lines(team_a, ea)),
        winning_margin=win_margin, odd_even=dict(odd=sum(p for k, p in total.items() if k % 2), even=sum(p for k, p in total.items() if not k % 2)),
        combos=combos, likely_scores=[dict(score=f'{x}-{y}', probability=p) for (x, y), p in tops],
        total_sd=math.sqrt(max(0, sum(k * k * p for k, p in total.items()) - et * et)),
        margin_sd=math.sqrt(max(0, sum(k * k * p for k, p in margin.items()) - em * em)))


# ---------- Bookmaker lines ----------

def fair_pair(prices):
    """Margin-free probabilities from a two-way decimal price pair (power method)."""
    a, b = prices
    if not a or not b or a <= 1 or b <= 1:
        return None
    lo, hi = .5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = (1 / a) ** k + (1 / b) ** k
        lo, hi = (k, hi) if s > 1 else (lo, k)
    k = (lo + hi) / 2
    return [(1 / a) ** k, (1 / b) ** k]


def _widths(mh, ma, width):
    sm = max(6.0, width['margin'] + width.get('slope', 0.0) * (abs(mh - ma) - 6))
    return sm, width['total']


def _ot_points(mh, ma, width=None):
    """Expected overtime points added to the total (both teams), approximately."""
    sm, _ = _widths(mh, ma, width or MODEL_WIDTH)
    p_tie = MARGIN_SHAPE.get(0, 1) * N.pdf((mh - ma) / sm) / sm
    return p_tie * 2 * OT['mean'] * 1.09        # 1.09: 9% of overtime games need a second period


def implied(line, model_means, width=None):
    """Regulation expectations implied by a line (spread, total and their prices).

    Returns (home, away) or None. Spread and total solve separately through the
    normal margin and total of the regulation grid; overtime points are added back
    for the total. A missing spread falls back to the moneyline.
    """
    if not line:
        return None
    width = width or LINE_WIDTH
    mh0, ma0 = model_means
    margin = total = None
    p_spread = fair_pair(line.get('spread_prices') or [None, None]) or [.5, .5] if line.get('spread') is not None else None
    p_ml = fair_pair(line['moneyline']) if all(line.get('moneyline') or [None]) else None
    p_total = fair_pair(line.get('total_prices') or [None, None]) or [.5, .5] if line.get('total') is not None else None
    # The margin sd can depend on the margin itself (slope), so solve by fixed point.
    guess = -line['spread'] if line.get('spread') is not None else mh0 - ma0
    for _ in range(4):
        sm, st = _widths(guess / 2, -guess / 2, width)
        if p_spread:
            margin = -line['spread'] + sm * N.inv_cdf(min(.99, max(.01, p_spread[0])))
        elif p_ml:
            margin = sm * N.inv_cdf(min(.99, max(.01, p_ml[0])))
        if margin is None:
            break
        guess = margin
    if p_total:
        total = line['total'] + st * N.inv_cdf(min(.99, max(.01, p_total[0]))) if margin is not None else \
            line['total'] + _widths(mh0, ma0, width)[1] * N.inv_cdf(min(.99, max(.01, p_total[0])))
    if margin is None and total is None:
        return None
    if margin is None:
        margin = mh0 - ma0
    if total is None:
        total = mh0 + ma0
    else:
        total -= _ot_points((total + margin) / 2, (total - margin) / 2, width)
    return (total + margin) / 2, (total - margin) / 2
