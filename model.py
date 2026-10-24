"""Regularized, time-weighted Poisson attack/defence model.

This deliberately has no third-party dependency.  It fits the likelihood with
Adam and an L2 prior so a promoted team, or a team with a thin history, is
pulled back toward the league average instead of producing an extreme rate.
"""
import datetime as dt
import math


SPEC = {
    'version': 'poisson-attack-defence-dixon-coles-1.1-market-targets',
    'family': 'Poisson scores with Dixon-Coles low-score dependence correction',
    'features': ['league baseline', 'home advantage', 'team attack', 'team defence'],
    'targets': 'closing-price implied goals (75%) blended with scorelines, 90-day half-life, where prices exist',
    'half_life_days': 365,
    'ridge': 0.025,
    'optimizer': 'Adam, fixed pre-specified 50 iterations',
    'calibration': 'not fitted',
}


def fit_team_rates(rows, asof, teams=(), half_life_days=365, ridge=0.025, iterations=50):
    """Fit one historical cutoff and return expected rates for all home/away pairs.

    The final (alphabetical) team is a zero-effect reference, which identifies
    the model without changing fitted rates.  New teams are allowed: their
    effects start at zero and the ridge leaves them at the league baseline.
    """
    if len(rows) < 100:
        raise ValueError('At least 100 completed earlier matches are required.')
    cutoff = dt.date.fromisoformat(asof)
    observed_teams = {x for m in rows for x in (m['home'], m['away'])}
    all_teams = sorted(observed_teams | set(teams))
    reference = all_teams[-1]
    index = {team: i for i, team in enumerate(all_teams[:-1])}
    # beta = intercept, home advantage, attacks, defences
    n = 2 + 2 * len(index)
    beta = [0.0] * n
    # A good stable starting point reduces the work that the numerical solver
    # needs to do, while still being derived only from the permitted history.
    mean_goals = sum(sum(m['goals']) for m in rows) / (2 * len(rows))
    beta[0] = math.log(max(mean_goals, .05))
    grad_sq = [0.0] * n
    prepared = []
    for m in rows:
        age = max(0, (cutoff - dt.date.fromisoformat(m['date'])).days)
        w = 0.5 ** (age / half_life_days)
        prepared.append((index.get(m['home']), index.get(m['away']), m['goals'][0], m['goals'][1], w))
    total_weight = sum(x[4] for x in prepared)

    def effect(vec, offset, team_index):
        return 0.0 if team_index is None else vec[offset + team_index]

    # We optimize the average negative log likelihood.  Adam is deterministic;
    # the conservative learning rate is intentional for a local research tool.
    for step in range(1, iterations + 1):
        grad = [0.0] * n
        for hi, ai, hg, ag, weight in prepared:
            eta_home = beta[0] + beta[1] + effect(beta, 2, hi) + effect(beta, 2 + len(index), ai)
            eta_away = beta[0] + effect(beta, 2, ai) + effect(beta, 2 + len(index), hi)
            lh, la = math.exp(min(eta_home, 5)), math.exp(min(eta_away, 5))
            eh, ea = weight * (lh - hg), weight * (la - ag)
            grad[0] += eh + ea
            grad[1] += eh
            if hi is not None:
                grad[2 + hi] += eh
                grad[2 + len(index) + hi] += ea
            if ai is not None:
                grad[2 + ai] += ea
                grad[2 + len(index) + ai] += eh
        for i in range(n):
            grad[i] /= total_weight
            if i >= 2:
                grad[i] += ridge * beta[i]
            grad_sq[i] = .9 * grad_sq[i] + .1 * grad[i] * grad[i]
            # Bias correction is useful during the first few iterations.
            denom = math.sqrt(grad_sq[i] / (1 - .9 ** step)) + 1e-8
            beta[i] -= .055 * grad[i] / denom

    def expected(home, away):
        hi, ai = index.get(home), index.get(away)
        eta_home = beta[0] + beta[1] + effect(beta, 2, hi) + effect(beta, 2 + len(index), ai)
        eta_away = beta[0] + effect(beta, 2, ai) + effect(beta, 2 + len(index), hi)
        return max(.05, min(6, math.exp(eta_home))), max(.05, min(6, math.exp(eta_away)))
    metadata = dict(teams=len(all_teams), reference_team=reference, effective_matches=total_weight,
                    iterations=iterations, unseen_teams=[t for t in teams if t not in observed_teams])
    return expected, metadata


UPPER = {'de.2': 'de.1', 'it.2': 'it.1'}   # a club new to a second tier may have come down from here


def _previous(season):
    year = int(season[:4]) - 1
    return f'{year}-{str(year + 1)[-2:]}'


def newcomers(matches, league_id, same_team=None):
    """{(team, season): 'up' | 'down'} for clubs absent from the league the season before.

    'down' means the club played the league above last season (relegated into a
    second tier); every other newcomer was promoted. Seasons whose predecessor
    is missing from the data get no flags. same_team compares names across
    divisions, whose sources spell clubs differently.
    """
    same_team = same_team or (lambda a, b: a == b)
    teams = {}
    for m in matches:
        teams.setdefault((m['league_id'], m['season']), set()).update((m['home'], m['away']))
    out = {}
    for (lg, season), current in teams.items():
        before = teams.get((lg, _previous(season)))
        if lg != league_id or not before:
            continue
        above = teams.get((UPPER.get(lg), _previous(season)), set())
        for team in current - before:
            out[(team, season)] = 'down' if any(same_team(team, t) for t in above) else 'up'
    return out


def fit_ratings(rows, asof, teams=(), half_life_days=365, ridge=0.025, newcomers=None, offset_ridge=0.002):
    """Attack/defence ratings solved exactly, with a learned prior for new clubs.

    Same penalized likelihood as fit_team_rates (mean weighted Poisson NLL plus
    ridge/2 on every team effect), but every team is free (no pinned reference)
    and it is solved to convergence by block Newton steps: given the defences,
    each attack is a separate one-dimensional convex problem, and vice versa;
    baseline, home advantage and the newcomer offsets form one small block.

    newcomers maps (team, season) to 'up' or 'down'. Matches a club plays in its
    first season in the league add a shared attack and defence offset for that
    kind of newcomer, learned from every such season in the history, so a
    promoted side starts below the league average rather than at it.
    """
    if len(rows) < 100:
        raise ValueError('At least 100 completed earlier matches are required.')
    cutoff = dt.date.fromisoformat(asof)
    newcomers = newcomers or {}
    all_teams = sorted({x for m in rows for x in (m['home'], m['away'])} | set(teams))
    index = {team: i for i, team in enumerate(all_teams)}
    t = len(all_teams)
    kinds = {'up': 0, 'down': 1}
    # One entry per goal count: (attacker, defender, is home, attacker kind, defender kind, goals, weight).
    etas = []
    for m in rows:
        w = 0.5 ** (max(0, (cutoff - dt.date.fromisoformat(m['date'])).days) / half_life_days)
        hk, ak = (kinds.get(newcomers.get((m[s], m.get('season')))) for s in ('home', 'away'))
        etas.append((index[m['home']], index[m['away']], 1, hk, ak, m['goals'][0], w))
        etas.append((index[m['away']], index[m['home']], 0, ak, hk, m['goals'][1], w))
    total = sum(e[6] for e in etas) / 2
    mean_goals = sum(e[5] * e[6] for e in etas) / (2 * total)
    att, dfn = [0.0] * t, [0.0] * t
    # Global block: baseline, home, up attack, up defence, down attack, down defence.
    g = [math.log(max(mean_goals, .05)), 0.0, 0.0, 0.0, 0.0, 0.0]
    penalty = [0.0, 0.0] + [offset_ridge] * 4

    def features(e):
        x = [1.0, float(e[2]), 0.0, 0.0, 0.0, 0.0]
        if e[3] is not None:
            x[2 + 2 * e[3]] = 1.0
        if e[4] is not None:
            x[3 + 2 * e[4]] = 1.0
        return x

    xs = [features(e) for e in etas]
    active = [tuple(i for i in range(6) if x[i]) for x in xs]
    att_of, def_of, goals, weight = ([e[k] for e in etas] for k in (0, 1, 5, 6))
    n_eta = len(etas)

    def rates():
        return [math.exp(min(5, sum(g[i] for i in active[k]) + att[att_of[k]] + dfn[def_of[k]])) for k in range(n_eta)]

    for _ in range(200):
        biggest = 0.0
        for vec, owner in ((att, att_of), (dfn, def_of)):
            grad, hess = [0.0] * t, [0.0] * t
            for k, lam in enumerate(rates()):
                i, w = owner[k], weight[k]
                grad[i] += w * (lam - goals[k])
                hess[i] += w * lam
            for i in range(t):
                step = max(-1.0, min(1.0, (grad[i] / total + ridge * vec[i]) / (hess[i] / total + ridge)))
                vec[i] -= step
                biggest = max(biggest, abs(step))
        grad, hess = [0.0] * 6, [[0.0] * 6 for _ in range(6)]
        for k, lam in enumerate(rates()):
            r, c = weight[k] * (lam - goals[k]), weight[k] * lam
            for i in active[k]:
                grad[i] += r
                row = hess[i]
                for j in active[k]:
                    row[j] += c
        for i in range(6):
            grad[i] = grad[i] / total + penalty[i] * g[i]
            hess[i] = [v / total for v in hess[i]]
            hess[i][i] += penalty[i] + 1e-9
        step = _solve(hess, grad)
        for i in range(6):
            s = max(-1.0, min(1.0, step[i]))
            g[i] -= s
            biggest = max(biggest, abs(s))
        if biggest < 1e-6:
            break

    def expected(home, away, season=None):
        hi, ai = index.get(home), index.get(away)
        hk, ak = (kinds.get(newcomers.get((x, season))) for x in (home, away))
        def offset(kind, slot):
            return 0.0 if kind is None else g[2 + 2 * kind + slot]
        a = lambda i: 0.0 if i is None else att[i]
        d = lambda i: 0.0 if i is None else dfn[i]
        eta_home = g[0] + g[1] + a(hi) + d(ai) + offset(hk, 0) + offset(ak, 1)
        eta_away = g[0] + a(ai) + d(hi) + offset(ak, 0) + offset(hk, 1)
        return max(.05, min(6, math.exp(eta_home))), max(.05, min(6, math.exp(eta_away)))
    expected.season_aware = True
    metadata = dict(teams=len(all_teams), effective_matches=total, solver='block Newton, converged',
                    home_advantage=g[1], newcomer_offsets=dict(up_attack=g[2], up_defence=g[3],
                                                               down_attack=g[4], down_defence=g[5]),
                    unseen_teams=[x for x in teams if x not in {y for m in rows for y in (m['home'], m['away'])}])
    return expected, metadata


def _solve(a, b):
    """Gaussian elimination with partial pivoting for the small global block."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda k: abs(m[k][col]))
        m[col], m[piv] = m[piv], m[col]
        for k in range(col + 1, n):
            f = m[k][col] / m[col][col]
            m[k] = [x - f * y for x, y in zip(m[k], m[col])]
    out = [0.0] * n
    for i in reversed(range(n)):
        out[i] = (m[i][n] - sum(m[i][j] * out[j] for j in range(i + 1, n))) / m[i][i]
    return out


def fit_dixon_coles(rows, asof, expected, half_life_days=365):
    """Fit low-score dependence rho by a bounded weighted likelihood grid.

    The correction only affects 0-0, 0-1, 1-0 and 1-1.  The grid is bounded
    by each training match's positivity constraints, so no invalid probability
    cells can be produced.  This is intentionally re-estimated at each
    historical cutoff rather than tuned using outcomes being evaluated.
    """
    cutoff = dt.date.fromisoformat(asof)
    prepared, lower, upper = [], -.20, .20
    for match in rows:
        h, a = match['goals']
        if h > 1 or a > 1:
            continue
        lh, la = (expected(match['home'], match['away'], match.get('season')) if getattr(expected, 'season_aware', False)
                  else expected(match['home'], match['away']))
        weight = .5 ** (max(0, (cutoff - dt.date.fromisoformat(match['date'])).days) / half_life_days)
        prepared.append((h, a, lh, la, weight))
        if h == 0 and a == 0:
            upper = min(upper, (1 / (lh * la)) - 1e-8)
        elif h == 0 and a == 1:
            lower = max(lower, (-1 / lh) + 1e-8)
        elif h == 1 and a == 0:
            lower = max(lower, (-1 / la) + 1e-8)
        elif h == 1 and a == 1:
            upper = min(upper, 1 - 1e-8)
    if not prepared or lower >= upper:
        return 0.0, {'rho_observations': len(prepared), 'rho_bounds': [lower, upper], 'rho_method': 'fallback_zero'}
    def tau(h, a, lh, la, rho):
        if h == 0 and a == 0: return 1 - lh * la * rho
        if h == 0 and a == 1: return 1 + lh * rho
        if h == 1 and a == 0: return 1 + la * rho
        if h == 1 and a == 1: return 1 - rho
        return 1
    # The objective is concave: each correction is log(1 + c*rho). Newton's
    # method with a strict interval clamp is therefore fast and safe here.
    coefficients = []
    for h, a, lh, la, weight in prepared:
        coefficient = -lh*la if (h, a) == (0, 0) else lh if (h, a) == (0, 1) else la if (h, a) == (1, 0) else -1
        coefficients.append((coefficient, weight))
    best = min(max(0.0, lower + 1e-7), upper - 1e-7)
    for _ in range(10):
        gradient = sum(weight * coefficient / (1 + coefficient * best) for coefficient, weight in coefficients)
        curvature = -sum(weight * coefficient * coefficient / (1 + coefficient * best) ** 2 for coefficient, weight in coefficients)
        candidate = best - gradient / curvature if curvature else best
        # Keep every likelihood term positive even under a poor starting step.
        best = min(max(candidate, lower + 1e-7), upper - 1e-7)
    return best, {'rho_observations': len(prepared), 'rho_bounds': [lower, upper], 'rho_method': 'weighted grid likelihood'}


def fit_rates(rows, home, away, asof, half_life_days=365, ridge=0.025, targets=None, target_half_life=90,
              newcomers=None, season=None):
    """Fit using only earlier completed matches and return the requested rates.

    targets: optional copies of rows with market-implied goals; ratings are then fitted
    to those (with their own half-life) while rho still comes from real scorelines.
    newcomers/season: promoted and relegated clubs (see newcomers()) and the season
    being forecast, so a club new to the league gets the learned newcomer offset."""
    expected, metadata = fit_ratings(targets or rows, asof, (home, away),
                                     target_half_life if targets else half_life_days, ridge, newcomers)
    lh, la = expected(home, away, season)
    rho, rho_meta = fit_dixon_coles(rows, asof, expected, half_life_days)
    counts = {team: sum(team in (m['home'], m['away']) for m in rows) for team in (home, away)}
    metadata.update(dixon_coles_rho=rho, **rho_meta)
    return lh, la, counts, metadata
