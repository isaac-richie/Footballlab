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
        lh, la = expected(match['home'], match['away'])
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


def fit_rates(rows, home, away, asof, half_life_days=365, ridge=0.025, iterations=50, targets=None, target_half_life=90):
    """Fit using only earlier completed matches and return the requested rates.

    targets: optional copies of rows with market-implied goals; ratings are then fitted
    to those (with their own half-life) while rho still comes from real scorelines."""
    expected, metadata = fit_team_rates(targets or rows, asof, (home, away),
                                        target_half_life if targets else half_life_days, ridge, iterations)
    lh, la = expected(home, away)
    rho, rho_meta = fit_dixon_coles(rows, asof, expected, half_life_days)
    counts = {team: sum(team in (m['home'], m['away']) for m in rows) for team in (home, away)}
    metadata.update(dixon_coles_rho=rho, **rho_meta)
    return lh, la, counts, metadata
