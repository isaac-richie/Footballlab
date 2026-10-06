"""Market-implied goal expectancies.

Find home/away Poisson rates whose Dixon-Coles score grid reproduces the
bookmaker's margin-free 1X2 and over/under 2.5 prices.  Every derived market
(correct score, half-time, Asian lines, combinations) then inherits the
market's information instead of the score-history model's.
"""
import math

from markets import score_matrix


def _targets(lh, la, rho):
    grid = score_matrix(lh, la, rho)
    home = sum(p for (h, a), p in grid.items() if h > a)
    away = sum(p for (h, a), p in grid.items() if h < a)
    over = sum(p for (h, a), p in grid.items() if h + a > 2)
    return home, away, over


def implied_rates(probabilities, over25=None, rho=0.0, start=(1.4, 1.1)):
    """Least-squares fit of (log lh, log la) by damped Gauss-Newton.

    With only 1X2 prices the total-goals level is weakly identified, so a
    missing over/under price keeps the starting total as a soft anchor.
    """
    x = [math.log(start[0]), math.log(start[1])]
    anchor = math.log(start[0] * start[1])
    def residuals(v):
        lh, la = (min(6, max(.05, math.exp(t))) for t in v)
        h, a, o = _targets(lh, la, rho)
        r = [h - probabilities[0], a - probabilities[2]]
        r.append(o - over25 if over25 is not None else .05 * (v[0] + v[1] - anchor))
        return r
    for _ in range(40):
        r = residuals(x)
        jac = []
        for i in range(2):
            y = list(x)
            y[i] += 1e-5
            jac.append([(b - a) / 1e-5 for a, b in zip(r, residuals(y))])
        # Normal equations for the 2x2 system, lightly damped.
        a11 = sum(j * j for j in jac[0]) + 1e-9
        a22 = sum(j * j for j in jac[1]) + 1e-9
        a12 = sum(p * q for p, q in zip(jac[0], jac[1]))
        g1 = sum(j * v for j, v in zip(jac[0], r))
        g2 = sum(j * v for j, v in zip(jac[1], r))
        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-15:
            break
        step = [(a22 * g1 - a12 * g2) / det, (a11 * g2 - a12 * g1) / det]
        x = [x[0] - max(-.5, min(.5, step[0])), x[1] - max(-.5, min(.5, step[1]))]
        if max(abs(s) for s in step) < 1e-7:
            break
    lh, la = (min(6, max(.05, math.exp(t))) for t in x)
    error = max(abs(v) for v in residuals(x)[:3 if over25 is not None else 2])
    return lh, la, error
