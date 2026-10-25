"""Out-of-time accuracy lab: rating models, margin removal, blending and calibration.

Every week of 2023-24 to 2026-27 (to date) in every league is predicted from fits
on results strictly before that week. Choices are made on the tuning seasons
(2023-24, 2024-25) only and then scored once on the holdout (2025-26, 2026-27),
so the holdout numbers are not flattered by the search.

    python3 tools/accuracy_lab.py            # all variants, writes reports/accuracy_lab.json
    python3 tools/accuracy_lab.py --summary  # re-summarize saved records
"""
import argparse
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import LEAGUES, distribution, load  # noqa: E402
import live_odds  # noqa: E402
import market_ratings  # noqa: E402
import odds_data  # noqa: E402
from model import fit_dixon_coles, fit_ratings, fit_team_rates, newcomers  # noqa: E402

TUNE = ('2023-24', '2024-25')
HOLDOUT = ('2025-26', '2026-27')
OUT = ROOT / 'reports' / 'accuracy_lab.json'
RECORDS = ROOT / 'reports' / 'accuracy_lab.records.json'
METHODS = ('proportional', 'shin', 'power', 'odds_ratio', 'additive')
PRICES = ('avg_open', 'avg_close', 'pin_open', 'pin_close')

# Unlisted settings are the 1.1 production values (below), not today's module
# defaults, so 'prod' and 'exact' stay fixed reference points.
BASE = dict(half_life=90, weight=.75, ridge=.025)
VARIANTS = {
    'prod': dict(old=True),
    'exact': dict(new=False),
    **{f'r{r}': dict(ridge=r, new=False) for r in (.01, .005, .0025)},
    **{f'r{r}_mw{w}_hl{h}': dict(ridge=r, weight=w, half_life=h, new=False)
       for r in (.01, .005) for w in (.75, .9) for h in (60, 90, 120) if (w, h) != (.75, 90)},
    'r0.005_mw0.9_hl60_new': dict(ridge=.005, weight=.9, half_life=60),
    **{f'goals_hl{h}_r{r}': dict(weight=0, half_life=h, ridge=r, new=False) for h in (365, 540, 730) for r in (.025, .01)},
    'goals_hl540_r0.01_new': dict(weight=0, half_life=540, ridge=.01),
}


def same_team(a, b):
    return live_odds.similarity(a, b) >= .8


def fit(rows, start, teams, flags, v):
    v = {**BASE, **v}
    target = market_ratings.targets(rows, v['weight']) if v['weight'] else rows
    if v.get('old'):
        expected, _ = fit_team_rates(target, start, teams, half_life_days=v['half_life'], ridge=v['ridge'])
    else:
        expected, _ = fit_ratings(target, start, teams, half_life_days=v['half_life'], ridge=v['ridge'],
                                  newcomers=flags if v.get('new', True) else None)
    rho, _ = fit_dixon_coles(rows, start, expected)
    return expected, rho


def run_league(league_id):
    data = load()
    market = odds_data.index(odds_data.load(), data['matches'])
    flags = newcomers(data['matches'], league_id, same_team)
    done = sorted((m for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None), key=lambda m: m['date'])
    tests = [m for m in done if m['season'] in TUNE + HOLDOUT]
    weeks = defaultdict(list)
    for m in tests:
        d = dt.date.fromisoformat(m['date'])
        weeks[(d - dt.timedelta(days=d.weekday())).isoformat()].append(m)
    out = []
    for start, games in sorted(weeks.items()):
        rows = [m for m in done if m['date'] < start]
        if len(rows) < 300:
            continue
        teams = sorted({t for g in games for t in (g['home'], g['away'])})
        fits = {name: fit(rows, start, teams, flags, v) for name, v in VARIANTS.items()}
        for g in games:
            h, a = g['goals']
            rec = dict(league=league_id, season=g['season'], date=g['date'], home=g['home'], away=g['away'],
                       outcome=0 if h > a else 1 if h == a else 2, over=int(h + a > 2.5), goals=[h, a],
                       newcomer=bool(flags.get((g['home'], g['season'])) or flags.get((g['away'], g['season']))))
            for name, (expected, rho) in fits.items():
                lh, la = expected(g['home'], g['away'], g['season']) if getattr(expected, 'season_aware', False) \
                    else expected(g['home'], g['away'])
                dist = distribution(lh, la, rho)
                rec[name] = [round(x, 6) for x in dist['probabilities']] + [round(dist['over25'], 6)]
            odds = market.get((league_id, g['date'], g['home'], g['away']), {}).get('odds', {})
            rec['odds'] = {k: odds[k] for k in PRICES + tuple('ou25_' + p for p in PRICES) if k in odds}
            out.append(rec)
    return out


def ll(p, k):
    return -math.log(max(p[k], 1e-12))


def score(rows, get):
    """Mean 1X2 log loss, Brier, ranked probability score and hit rate."""
    n = len(rows)
    if not n:
        return None
    tot = dict(log_loss=0.0, brier=0.0, rps=0.0, accuracy=0.0)
    for r in rows:
        p, y = get(r), r['outcome']
        tot['log_loss'] += ll(p, y)
        tot['brier'] += sum((p[i] - (i == y)) ** 2 for i in range(3))
        c = [p[0], p[0] + p[1]]
        o = [y == 0, y <= 1]
        tot['rps'] += sum((c[i] - o[i]) ** 2 for i in range(2)) / 2
        tot['accuracy'] += max(range(3), key=lambda i: p[i]) == y
    return {k: round(v / n, 5) for k, v in tot.items()} | dict(n=n)


def ou_ll(rows, get):
    rows = [r for r in rows if get(r) is not None]
    if not rows:
        return None
    return round(sum(-math.log(max(get(r) if r['over'] else 1 - get(r), 1e-12)) for r in rows) / len(rows), 5)


def pool(ps, ws):
    """Logarithmic opinion pool of several probability vectors."""
    x = [math.exp(sum(w * math.log(max(p[i], 1e-12)) for p, w in zip(ps, ws))) for i in range(3)]
    s = sum(x)
    return [v / s for v in x]


def calibrate(p, t, draw):
    """Temperature on log-probabilities plus a draw log-odds shift."""
    x = [math.exp(math.log(max(v, 1e-12)) / t) for v in p]
    x[1] *= math.exp(draw)
    s = sum(x)
    return [v / s for v in x]


def grid_best(rows, f, grid):
    return min(grid, key=lambda w: sum(ll(f(r, w), r['outcome']) for r in rows))


def summarize(records):
    tune = [r for r in records if r['season'] in TUNE]
    hold = [r for r in records if r['season'] in HOLDOUT]
    leagues = sorted({r['league'] for r in records})
    report = dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), tune=TUNE, holdout=HOLDOUT,
                  matches=dict(tune=len(tune), holdout=len(hold)))

    # 1. Rating-model variants on every match.
    model = lambda name: (lambda r: r[name][:3])
    report['models'] = {name: dict(tune=score(tune, model(name)), holdout=score(hold, model(name)),
                                   ou25=dict(tune=ou_ll(tune, lambda r, n=name: r[n][3]), holdout=ou_ll(hold, lambda r, n=name: r[n][3])),
                                   newcomer_matches=score([r for r in hold if r['newcomer']], model(name)))
                        for name in VARIANTS}
    # Leagues with no prices at all (Saudi) are routed to the scoreline model, as
    # market_ratings.fit does. The newcomer prior is excluded from selection: it
    # never gained more than 0.0002 on tuning seasons, well inside the noise.
    priced_leagues = {r['league'] for r in records if r['odds']}
    priced = [r for r in tune if r['league'] in priced_leagues]
    simple = [n for n in VARIANTS if not n.endswith('_new')]
    best_model = min((n for n in simple if not n.startswith('goals_')), key=lambda n: score(priced, model(n))['log_loss'])
    unpriced_best = min((n for n in simple if n.startswith('goals_')), key=lambda n: score(tune, model(n))['log_loss'])
    report['chosen'] = dict(model=best_model, model_without_prices=unpriced_best)
    report['models_by_league'] = {lg: {n: score([r for r in hold if r['league'] == lg], model(n))
                                       for n in ('prod', best_model, unpriced_best)} for lg in leagues}

    # 2. Margin removal: every method on every price, same matches.
    def market(src, method):
        return lambda r: odds_data.fair(r['odds'][src], method)
    report['margin'] = {}
    for src in PRICES:
        both_t = [r for r in tune if src in r['odds']]
        both_h = [r for r in hold if src in r['odds']]
        report['margin'][src] = {m: dict(tune=score(both_t, market(src, m)), holdout=score(both_h, market(src, m)))
                                 for m in METHODS}
    best_method = min(METHODS, key=lambda m: score([r for r in tune if 'avg_open' in r['odds']], market('avg_open', m))['log_loss'])
    report['chosen']['margin_method'] = best_method

    # 3. Pre-kickoff prices (opening) and blending the model in. Pinnacle stops
    # appearing in football-data in 2025, so it is compared where both exist.
    t3 = [r for r in tune if 'avg_open' in r['odds']]
    h3 = [r for r in hold if 'avg_open' in r['odds']]
    avg = lambda r: odds_data.fair(r['odds']['avg_open'], best_method)
    pin = lambda r: odds_data.fair(r['odds']['pin_open'], best_method)
    mdl = model(best_model)
    w_model = grid_best(t3, lambda r, w: pool([mdl(r), avg(r)], [w, 1 - w]), [i / 50 for i in range(26)])
    blend = lambda r: pool([mdl(r), avg(r)], [w_model, 1 - w_model])
    with_pin = [r for r in records if 'avg_open' in r['odds'] and 'pin_open' in r['odds']]
    report['pre_kickoff'] = dict(
        model_weight=w_model,
        tune=dict(market=score(t3, avg), market_plus_model=score(t3, blend), model=score(t3, mdl)),
        holdout=dict(market=score(h3, avg), market_plus_model=score(h3, blend), model=score(h3, mdl)),
        closing_holdout=score([r for r in h3 if 'avg_close' in r['odds']], lambda r: odds_data.fair(r['odds']['avg_close'], best_method)),
        pinnacle_vs_average=dict(seasons=sorted({r['season'] for r in with_pin}), average=score(with_pin, avg), pinnacle=score(with_pin, pin)))

    # 4. Calibration of the model when there are no prices (fitted on tuning seasons).
    grid = [(t / 100, d / 100) for t in range(70, 116, 3) for d in range(-15, 25, 3)]
    cal = {}
    for name in (best_model, unpriced_best):
        f = model(name)
        t, d = grid_best(tune, lambda r, w: calibrate(f(r), *w), grid)
        cal[name] = dict(temperature=t, draw_shift=d, holdout_raw=score(hold, f),
                         holdout_calibrated=score(hold, lambda r: calibrate(f(r), t, d)))
    report['calibration'] = cal

    # 5. The production configuration end to end, against the 1.1 model.
    def production(r):
        name = best_model if r['league'] in priced_leagues else unpriced_best
        return calibrate(r[name][:3], cal[name]['temperature'], cal[name]['draw_shift'])
    groups = dict(all=lambda r: True, priced_leagues=lambda r: r['league'] in priced_leagues,
                  unpriced_leagues=lambda r: r['league'] not in priced_leagues)
    report['production'] = {g: dict(previous=score([r for r in hold if f(r)], model('prod')),
                                    current=score([r for r in hold if f(r)], production)) for g, f in groups.items()}
    report['production_by_league'] = {lg: dict(previous=score([r for r in hold if r['league'] == lg], model('prod')),
                                               current=score([r for r in hold if r['league'] == lg], production))
                                      for lg in leagues}
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--summary', action='store_true')
    parser.add_argument('--leagues', nargs='*', help='re-run only these leagues, keeping the others')
    args = parser.parse_args()
    if args.summary:
        records = json.loads(RECORDS.read_text())
    else:
        leagues = args.leagues or list(LEAGUES)
        kept = [r for r in json.loads(RECORDS.read_text()) if r['league'] not in leagues] if args.leagues else []
        market_ratings.table()          # build the shared cache once, before the workers start
        with ProcessPoolExecutor() as pool_:
            records = kept + [r for chunk in pool_.map(run_league, leagues) for r in chunk]
        RECORDS.write_text(json.dumps(records))
    report = summarize(records)
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ('matches', 'chosen', 'pre_kickoff', 'calibration', 'production')}, indent=1))
    for src, methods in report['margin'].items():
        print(src, {m: v['holdout']['log_loss'] for m, v in methods.items() if v['holdout']})
    for name, v in report['models'].items():
        print(f"{name:14s} tune {v['tune']['log_loss']:.4f}  holdout {v['holdout']['log_loss']:.4f}  acc {v['holdout']['accuracy']:.3f}"
              f"  OU {v['ou25']['holdout']}")


if __name__ == '__main__':
    main()
