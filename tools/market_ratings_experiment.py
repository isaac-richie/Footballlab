"""Out-of-time test: do team ratings fitted to market-implied goals beat goals-only ratings?

For each league and each weekly cutoff in the test seasons, ratings are fitted on
earlier matches only, then scored on the following week's results (1X2 log loss,
lower is better). Variants differ only in the training target:

  goals   actual scorelines (the current model)
  market  goal expectancies implied by closing prices (scorelines where no prices)
  blend   halfway between the two

The market's own closing price on the scored match is reported as a ceiling.
Run from the repo root:  python3 tools/market_ratings_experiment.py
"""
import datetime as dt
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import LEAGUES, distribution, load  # noqa: E402
from implied import implied_rates_rho  # noqa: E402
from model import fit_dixon_coles, fit_team_rates  # noqa: E402
import odds_data  # noqa: E402

TEST_FROM = '2024-08-01'
WINDOW_DAYS = 3 * 365
OUT = ROOT / 'reports' / 'market_ratings_experiment.json'


def key(league_id, date, home, away):
    return '|'.join((league_id, date, home, away))


def implied_one(rec):
    o = rec['odds']
    h2h, ou = o.get('avg_close') or o.get('pin_close'), o.get('ou25_avg_close') or o.get('ou25_pin_close')
    if not h2h or not ou:
        return None
    p = odds_data.no_vig(h2h)
    lh, la, rho, err = implied_rates_rho(p, odds_data.no_vig(ou)[0], 0.0, (1.4, 1.1))
    return (key(rec['league_id'], rec['date'], rec['home'], rec['away']), [lh, la], p) if err < .03 else None


def implied_table():
    recs = [r for r in odds_data.load().get('records', []) if r.get('home') and r.get('away')]
    with ProcessPoolExecutor() as pool:
        out = [x for x in pool.map(implied_one, recs, chunksize=64) if x]
    return {k: (rates, p) for k, rates, p in out}


def ll(p, outcome):
    return -math.log(max(p[outcome], 1e-12))


def run_league(args):
    league_id, matches, table = args
    done = sorted((m for m in matches if m['goals'] is not None), key=lambda m: m['date'])
    tests = [m for m in done if m['date'] >= TEST_FROM]
    if not tests:
        return league_id, {}
    totals = {}
    start = dt.date.fromisoformat(TEST_FROM)
    start -= dt.timedelta(days=start.weekday())
    cutoff = start
    while cutoff.isoformat() <= tests[-1]['date']:
        lo, hi = cutoff.isoformat(), (cutoff + dt.timedelta(days=7)).isoformat()
        week = [m for m in tests if lo <= m['date'] < hi]
        if week:
            since = (cutoff - dt.timedelta(days=WINDOW_DAYS)).isoformat()
            rows = [m for m in done if since <= m['date'] < lo]
            if len(rows) >= 100:
                teams = sorted({t for m in week for t in (m['home'], m['away'])})
                goals_fit, _ = fit_team_rates(rows, lo, teams)
                rho, _ = fit_dixon_coles(rows, lo, goals_fit)
                def target(m, w):
                    imp = table.get(key(league_id, m['date'], m['home'], m['away']))
                    if not imp:
                        return m
                    g = m['goals']
                    return {**m, 'goals': [w * imp[0][0] + (1 - w) * g[0], w * imp[0][1] + (1 - w) * g[1]]}
                fits = {'goals': goals_fit}
                for w, label in ((1, 'market'), (.5, 'blend'), (.75, 'mostly_market')):
                    shifted = [target(m, w) for m in rows]
                    for half in (365, 180, 90):
                        fits[f'{label}_h{half}'] = fit_team_rates(shifted, lo, teams, half_life_days=half)[0]
                for m in week:
                    h, a = m['goals']
                    outcome = 0 if h > a else 1 if h == a else 2
                    imp = table.get(key(league_id, m['date'], m['home'], m['away']))
                    if not imp:
                        continue                      # compare on the same matches only
                    for name, fit in fits.items():
                        p = distribution(*fit(m['home'], m['away']), rho)['probabilities']
                        t = totals.setdefault(name, [0.0, 0]); t[0] += ll(p, outcome); t[1] += 1
                    t = totals.setdefault('closing', [0.0, 0]); t[0] += ll(imp[1], outcome); t[1] += 1
        cutoff += dt.timedelta(days=7)
    return league_id, {k: dict(log_loss=round(s / n, 4), n=n) for k, (s, n) in totals.items() if n}


def main():
    data = load(fill_gaps=True)
    table = implied_table()
    print(f'implied rates for {len(table)} matches', flush=True)
    jobs = [(lg, [m for m in data['matches'] if m['league_id'] == lg], table) for lg in LEAGUES]
    with ProcessPoolExecutor() as pool:
        results = dict(pool.map(run_league, jobs))
    overall = {}
    for res in results.values():
        for k, v in res.items():
            s = overall.setdefault(k, [0.0, 0]); s[0] += v['log_loss'] * v['n']; s[1] += v['n']
    summary = {k: dict(log_loss=round(s / n, 4), n=n) for k, (s, n) in overall.items()}
    report = dict(test_from=TEST_FROM, window_days=WINDOW_DAYS, by_league=results, overall=summary)
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
