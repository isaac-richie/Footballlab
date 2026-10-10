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


def implied_rates_rho(probabilities, over25, rho0=0.0, start=(1.4, 1.1), bounds=(-0.25, 0.25)):
    """Fit (log lh, log la, rho) so home, away and over 2.5 match the market exactly.

    Three prices, three unknowns: the low-score dependence is solved per match
    instead of borrowed from the league fit. Falls back to the two-parameter fit
    (with rho0) if the solution would leave valid probability bounds.
    """
    x = [math.log(start[0]), math.log(start[1]), rho0]
    def residuals(v):
        lh, la = (min(6, max(.05, math.exp(t))) for t in v[:2])
        rho = v[2]
        if not (bounds[0] <= rho <= bounds[1]) or 1 - lh * la * rho <= 0 or 1 + lh * rho <= 0 or 1 + la * rho <= 0:
            raise ValueError('rho out of range')
        h, a, o = _targets(lh, la, rho)
        return [h - probabilities[0], a - probabilities[2], o - over25]
    try:
        for _ in range(40):
            r = residuals(x)
            jac = []
            for i in range(3):
                y = list(x); y[i] += 1e-5
                jac.append([(b - a) / 1e-5 for a, b in zip(r, residuals(y))])
            # Solve J^T-indexed 3x3 system J * step = r (columns are parameters).
            m = [[jac[c][row] for c in range(3)] + [r[row]] for row in range(3)]
            for col in range(3):
                piv = max(range(col, 3), key=lambda k: abs(m[k][col]))
                if abs(m[piv][col]) < 1e-12:
                    raise ValueError('singular')
                m[col], m[piv] = m[piv], m[col]
                for k in range(3):
                    if k != col:
                        f = m[k][col] / m[col][col]
                        m[k] = [a - f * b for a, b in zip(m[k], m[col])]
            step = [m[i][3] / m[i][i] for i in range(3)]
            damp = 1.0
            while damp > 1e-3:
                cand = [x[0] - damp * max(-.5, min(.5, step[0])), x[1] - damp * max(-.5, min(.5, step[1])), x[2] - damp * max(-.05, min(.05, step[2]))]
                try:
                    residuals(cand); break
                except ValueError:
                    damp /= 2
            x = cand
            if max(abs(v) for v in step) < 1e-8:
                break
        error = max(abs(v) for v in residuals(x))
    except ValueError:
        lh, la, error = implied_rates(probabilities, over25, rho0, start)
        return lh, la, rho0, error
    lh, la = (min(6, max(.05, math.exp(t))) for t in x[:2])
    return lh, la, x[2], error
