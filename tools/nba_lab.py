"""Walk-forward accuracy lab for the NBA points model.

Every game day of the evaluated seasons is predicted from a fit on earlier games only.
Settings are searched on 2023-24 and 2024-25; 2025-26 is scored once with the
chosen settings, against ESPN BET's opening and closing lines where stored.
Summary goes to reports/nba_lab.json; per-game records (they hold bookmaker
lines) stay in reports/nba_lab.records.json, which is git-ignored.

    python3 tools/nba_lab.py            # search, then hold-out report
    python3 tools/nba_lab.py --quick    # current settings only
"""
import datetime as dt
import itertools
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nba  # noqa: E402
import nba_model as M  # noqa: E402
from quality import atomic_write  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TUNE, HOLD = (2024, 2025), (2026,)


def weeks(games, season):
    days = sorted({g['date'] for g in games if g['season'] == season and g['status'] == 'final'})
    if not days:
        return []
    start = dt.date.fromisoformat(days[0])
    start -= dt.timedelta(days=start.weekday())
    end = dt.date.fromisoformat(days[-1])
    out = []
    while start <= end:                  # one fit per game day, as the app does
        out.append((start.isoformat(), (start + dt.timedelta(days=1)).isoformat()))
        start += dt.timedelta(days=1)
    return out


def predict_seasons(games, seasons, settings, rest):
    recs = []
    for season in seasons:
        for lo, hi in weeks(games, season):
            todo = [g for g in games if g['season'] == season and g['status'] == 'final' and lo <= g['date'] < hi]
            if not todo:
                continue
            try:
                r = M.fit(games, lo, rest, settings)
            except ValueError:
                continue
            for g in todo:
                b2b = (rest.get((g['id'], 0), 0), rest.get((g['id'], 1), 0))
                mh, ma = M.expected(r, g['home'], g['away'], g['neutral'], b2b)
                recs.append(dict(id=g['id'], season=season, date=g['date'], kind=g['kind'], home=g['home'], away=g['away'],
                                 model=[mh, ma], reg=M.regulation(g), final=g['score'], line=g.get('line')))
    return recs


def rmse(xs):
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else None


def point_scores(recs):
    """RMSE of final margin and total for model and lines (same games for each comparison)."""
    out = {}
    m_err = [r['final'][0] - r['final'][1] - (r['model'][0] - r['model'][1]) for r in recs]
    t_err = [sum(r['final']) - (sum(r['model']) + M._ot_points(*r['model'])) for r in recs]
    out['model'] = dict(margin_rmse=rmse(m_err), total_rmse=rmse(t_err), games=len(recs))
    for stage in ('open', 'close'):
        sub = [r for r in recs if ((r['line'] or {}).get(stage) or {}).get('spread') is not None and r['line'][stage].get('total') is not None]
        if not sub:
            continue
        out[stage] = dict(
            games=len(sub),
            line_margin_rmse=rmse([r['final'][0] - r['final'][1] + r['line'][stage]['spread'] for r in sub]),
            line_total_rmse=rmse([sum(r['final']) - r['line'][stage]['total'] for r in sub]),
            model_margin_rmse=rmse([r['final'][0] - r['final'][1] - (r['model'][0] - r['model'][1]) for r in sub]),
            model_total_rmse=rmse([sum(r['final']) - (sum(r['model']) + M._ot_points(*r['model'])) for r in sub]))
    return out


def residuals(recs):
    xs = [(r['reg'][0] - r['model'][0], r['reg'][1] - r['model'][1]) for r in recs if r['reg']]
    n = len(xs)
    mh = sum(a for a, _ in xs) / n
    ma = sum(b for _, b in xs) / n
    vh = sum((a - mh) ** 2 for a, _ in xs) / n
    va = sum((b - ma) ** 2 for _, b in xs) / n
    cov = sum((a - mh) * (b - ma) for a, b in xs) / n
    return dict(sd=math.sqrt((vh + va) / 2), rho=cov / math.sqrt(vh * va), bias=[mh, ma], games=n)


def line_constants(recs):
    """Per-team SD and correlation implied by the closing line's margin and total errors.

    Margin variance is 2 sd^2 (1 - rho) and total variance 2 sd^2 (1 + rho); overtime
    points are taken out of the total error first so the constants describe 48 minutes.
    """
    sub = [r for r in recs if r['reg'] and ((r['line'] or {}).get('close') or {}).get('spread') is not None
           and r['line']['close'].get('total') is not None]
    if len(sub) < 200:
        return None
    vm = sum((r['reg'][0] - r['reg'][1] + r['line']['close']['spread']) ** 2 for r in sub) / len(sub)
    ot = [sum(r['final']) - sum(r['reg']) for r in sub]
    mean_ot = sum(ot) / len(ot)
    vt = sum((sum(r['reg']) - (r['line']['close']['total'] - mean_ot)) ** 2 for r in sub) / len(sub)
    return dict(games=len(sub), sd=math.sqrt((vm + vt) / 4), rho=(vt - vm) / (vt + vm), margin_rmse=math.sqrt(vm), total_rmse=math.sqrt(vt))


def overtime_stats(games):
    per = []
    for g in games:
        p = g.get('periods')
        if g['status'] == 'final' and p and len(p[0]) > 4:
            per += list(zip(p[0][4:], p[1][4:]))
    n = len(per)
    if not n:
        return None
    m = sum(a + b for a, b in per) / (2 * n)
    var_h = sum((a - m) ** 2 for a, _ in per) / n
    var_a = sum((b - m) ** 2 for _, b in per) / n
    cov = sum((a - m) * (b - m) for a, b in per) / n
    finals = [g for g in games if g['status'] == 'final' and g.get('periods')]
    return dict(periods=n, mean=m, sd=math.sqrt((var_h + var_a) / 2), rho=cov / math.sqrt(var_h * var_a),
                games_to_ot=sum(len(g['periods'][0]) > 4 for g in finals) / len(finals),
                second_ot_share=sum(len(g['periods'][0]) > 5 for g in finals) / max(1, sum(len(g['periods'][0]) > 4 for g in finals)))


def margin_shape(recs):
    """Observed vs predicted share of regulation margins near zero (no end-game reshape)."""
    obs, pred = {}, {}
    for r in recs:
        if not r['reg']:
            continue
        m = r['reg'][0] - r['reg'][1]
        if abs(m) <= 6:
            obs[m] = obs.get(m, 0) + 1
        for (x, y), p in M._bvn(r['model'][0], r['model'][1], M.SD, M.RHO, int(r['model'][0]) - 50, int(r['model'][0]) + 50,
                                int(r['model'][1]) - 50, int(r['model'][1]) + 50).items():
            if abs(x - y) <= 6:
                pred[x - y] = pred.get(x - y, 0) + p
    return {k: dict(observed=obs.get(k, 0), predicted=pred.get(k, 0), ratio=obs.get(k, 0) / pred[k]) for k in sorted(pred)}


def probability_scores(recs):
    """Moneyline, spread and total log loss from the full grid, against fair closing prices."""
    def ll(p, y):
        p = min(1 - 1e-6, max(1e-6, p))
        return -math.log(p if y else 1 - p)
    acc = dict(n=0, model_ml=0.0, model_ml_brier=0.0, close_ml=0.0, close_ml_brier=0.0, n_close=0, model_ml_on_close=0.0,
               spread_n=0, model_spread=0.0, close_spread=0.0, total_n=0, model_total=0.0, close_total=0.0, priced_ml=0.0, priced_spread=0.0, priced_total=0.0)
    bins = [[0, 0.0, 0] for _ in range(10)]
    for r in recs:
        y = r['final'][0] > r['final'][1]
        d = M.distribution(*r['model'])
        close = (r['line'] or {}).get('close') or {}
        mk = M.markets(d, close.get('spread'), close.get('total'))
        p = mk['moneyline'][0]
        acc['n'] += 1
        acc['model_ml'] += ll(p, y)
        acc['model_ml_brier'] += (p - y) ** 2
        b = bins[min(9, int(p * 10))]
        b[0] += 1; b[1] += p; b[2] += y
        fair = M.fair_pair(close.get('moneyline') or [None, None])
        imp = M.implied(close, r['model']) if close else None
        if fair:
            acc['n_close'] += 1
            acc['close_ml'] += ll(fair[0], y)
            acc['close_ml_brier'] += (fair[0] - y) ** 2
            acc['model_ml_on_close'] += ll(p, y)
            if imp:
                acc['priced_ml'] += ll(M.markets(M.distribution(*imp, width=M.LINE_WIDTH))['moneyline'][0], y)
        margin, total = r['final'][0] - r['final'][1], sum(r['final'])
        s, t = close.get('spread'), close.get('total')
        if s is not None and margin + s != 0 and fair_ok(close.get('spread_prices')):
            acc['spread_n'] += 1
            yc = margin + s > 0
            acc['model_spread'] += ll(mk['spread'][0] / (mk['spread'][0] + mk['spread'][2]), yc)
            acc['close_spread'] += ll(M.fair_pair(close['spread_prices'])[0], yc)
        if t is not None and total != t and fair_ok(close.get('total_prices')):
            acc['total_n'] += 1
            yo = total > t
            acc['model_total'] += ll(mk['total'][0] / (mk['total'][0] + mk['total'][2]), yo)
            acc['close_total'] += ll(M.fair_pair(close['total_prices'])[0], yo)
            if imp:
                pm = M.markets(M.distribution(*imp, width=M.LINE_WIDTH), s, t)['total']
                acc['priced_total'] += ll(pm[0] / (pm[0] + pm[2]), yo)
    n, nc = acc['n'], max(1, acc['n_close'])
    return dict(
        games=n, model_ml_logloss=acc['model_ml'] / n, model_ml_brier=acc['model_ml_brier'] / n,
        with_close_moneyline=acc['n_close'], close_ml_logloss=acc['close_ml'] / nc, close_ml_brier=acc['close_ml_brier'] / nc,
        model_ml_logloss_same_games=acc['model_ml_on_close'] / nc, priced_from_close_ml_logloss=acc['priced_ml'] / nc,
        spread_games=acc['spread_n'], model_cover_logloss=acc['model_spread'] / max(1, acc['spread_n']),
        close_cover_logloss=acc['close_spread'] / max(1, acc['spread_n']),
        total_games=acc['total_n'], model_over_logloss=acc['model_total'] / max(1, acc['total_n']),
        close_over_logloss=acc['close_total'] / max(1, acc['total_n']), priced_over_logloss=acc['priced_total'] / max(1, acc['total_n']),
        calibration=[dict(bin=f'{i * 10}-{i * 10 + 10}%', games=b[0], predicted=b[1] / b[0], observed=b[2] / b[0]) for i, b in enumerate(bins) if b[0]])


def fair_ok(prices):
    return bool(prices and all(prices) and M.fair_pair(prices))


def main():
    data = nba.load()
    games = data['games']
    rest = M.back_to_back(games)
    quick = '--quick' in sys.argv
    # Scores alone favoured ridge 4 and a 50-day half-life. With closing lines as most of
    # the target the ratings can move much faster; this grid searches around that optimum.
    grid = [dict(M.SETTINGS)] if quick else [dict(M.SETTINGS, half_life=h, ridge=l, market=m, gap=g)
                                             for h, l, m, g in itertools.product((10, 15, 25), (.25, .5, 1.0), (.5, .7, .85), (0, 115))]
    search = []
    for s in grid:
        recs = predict_seasons(games, TUNE, s, rest)
        sc = point_scores(recs)['model']
        search.append(dict(settings=s, **sc))
        print(json.dumps(search[-1]), flush=True)
    # Margin and total errors are on different scales and both matter: rank by their sum of squares.
    best = min(search, key=lambda x: x['margin_rmse'] ** 2 + x['total_rmse'] ** 2)
    s = best['settings']
    tune = predict_seasons(games, TUNE, s, rest)
    hold = predict_seasons(games, HOLD, s, rest)
    current = predict_seasons(games, (nba.current_season(),), s, rest)
    res = residuals(tune)
    ot = overtime_stats([g for g in games if g['season'] in TUNE])
    report = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), chosen=s, residuals_tuning=res, line_constants_tuning=line_constants(tune), overtime_tuning=ot, margin_shape_tuning=margin_shape(tune),
        model_constants=dict(MODEL_WIDTH=M.MODEL_WIDTH, LINE_WIDTH=M.LINE_WIDTH, OT=M.OT, MARGIN_SHAPE={str(k): v for k, v in M.MARGIN_SHAPE.items()}),
        tuning=dict(points=point_scores(tune), probabilities=probability_scores(tune)),
        holdout=dict(points=point_scores(hold), probabilities=probability_scores(hold), residuals=residuals(hold) if hold else None),
        current_season=dict(points=point_scores(current), probabilities=probability_scores(current)) if current else None,
        search=sorted(search, key=lambda x: x['margin_rmse'] ** 2 + x['total_rmse'] ** 2)[:10])
    atomic_write(ROOT / 'reports' / 'nba_lab.json', json.dumps(report, indent=1))
    atomic_write(ROOT / 'reports' / 'nba_lab.records.json', json.dumps(tune + hold + current))
    print(json.dumps({k: report[k] for k in ('chosen', 'residuals_tuning', 'line_constants_tuning', 'overtime_tuning', 'margin_shape_tuning', 'tuning', 'holdout')}, indent=1))


if __name__ == '__main__':
    main()
