"""Out-of-time model experiments scored against bookmaker prices.

Each evaluated week is predicted from a fit on results strictly before that
week (weekly refits keep the grid affordable; every variant gets the same
schedule, so comparisons are fair).  Variants are compared on 1X2 and
over/under 2.5 log loss, alongside opening and closing market prices.
"""
import argparse
import datetime as dt
import json
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from app import distribution, load
from model import fit_dixon_coles, fit_team_rates
from odds_data import index as market_index, load as load_market, no_vig
from quality import atomic_write

ROOT = Path(__file__).resolve().parent
LEAGUES = ['en.1', 'es.1', 'it.1', 'de.1', 'fr.1', 'de.2']
SEASONS = ['2023-24', '2024-25', '2025-26']


def shot_adjusted(rows, stats_by_key, weight):
    """Blend goals with shots-on-target times the league's conversion rate."""
    if not weight:
        return rows
    sot = goals = 0
    for m in rows:
        s = stats_by_key.get((m['league_id'], m['date'], m['home'], m['away']))
        if s:
            sot += sum(s)
            goals += sum(m['goals'])
    if not sot:
        return rows
    conversion = goals / sot
    out = []
    for m in rows:
        s = stats_by_key.get((m['league_id'], m['date'], m['home'], m['away']))
        if s:
            target = [(1 - weight) * g + weight * conversion * x for g, x in zip(m['goals'], s)]
            out.append({**m, 'goals': target})
        else:
            out.append(m)
    return out


def week_start(date):
    d = dt.date.fromisoformat(date)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def run_variant(args):
    league, variant = args
    data = load()
    market = market_index(load_market(), data['matches'])
    stats = {k: r['stats']['shots_on_target'] for k, r in market.items() if 'shots_on_target' in r.get('stats', {})}
    matches = [m for m in data['matches'] if m['league_id'] == league and m['goals'] is not None]
    targets = [m for m in matches if m['season'] in SEASONS]
    weeks = defaultdict(list)
    for m in targets:
        weeks[week_start(m['date'])].append(m)
    out = []
    for start, games in sorted(weeks.items()):
        rows = [m for m in matches if m['date'] < start]
        if len(rows) < 300:
            continue
        fit_rows = shot_adjusted(rows, stats, variant.get('sot', 0))
        teams = sorted({t for g in games for t in (g['home'], g['away'])})
        expected, _ = fit_team_rates(fit_rows, start, teams, variant.get('half_life', 365), variant.get('ridge', .025))
        rho, _ = fit_dixon_coles(rows, start, expected, variant.get('half_life', 365))
        for g in games:
            lh, la = expected(g['home'], g['away'])
            d = distribution(lh, la, rho)
            rec = market.get((league, g['date'], g['home'], g['away']), {})
            odds = rec.get('odds', {})
            h, a = g['goals']
            out.append(dict(league=league, season=g['season'], date=g['date'],
                            outcome=0 if h > a else 1 if h == a else 2, over=int(h + a > 2.5),
                            model=d['probabilities'], model_over=d['over25'],
                            open=no_vig(odds['avg_open']) if 'avg_open' in odds else None,
                            close=no_vig(odds['avg_close']) if 'avg_close' in odds else None,
                            pin_close=no_vig(odds['pin_close']) if 'pin_close' in odds else None,
                            ou_open=no_vig(odds['ou25_avg_open'])[0] if 'ou25_avg_open' in odds else None,
                            ou_close=no_vig(odds['ou25_avg_close'])[0] if 'ou25_avg_close' in odds else None))
    return league, variant['name'], out


def ll(p, k):
    return -math.log(max(p[k], 1e-12))


def blend(p, q, w):
    """Geometric pool: weight w on the model, 1-w on the market."""
    x = [max(a, 1e-12) ** w * max(b, 1e-12) ** (1 - w) for a, b in zip(p, q)]
    s = sum(x)
    return [v / s for v in x]


def summarize(records):
    both = [r for r in records if r['open'] and r['close']]
    if not both:
        return {}
    n = len(both)
    s = lambda f: sum(f(r) for r in both) / n
    ou = [r for r in both if r['ou_open'] is not None and r['ou_close'] is not None]
    bll = lambda p, y: -math.log(max(p if y else 1 - p, 1e-12))
    return dict(matches=n,
                model=s(lambda r: ll(r['model'], r['outcome'])),
                market_open=s(lambda r: ll(r['open'], r['outcome'])),
                market_close=s(lambda r: ll(r['close'], r['outcome'])),
                model_accuracy=s(lambda r: max(range(3), key=lambda i: r['model'][i]) == r['outcome']),
                close_accuracy=s(lambda r: max(range(3), key=lambda i: r['close'][i]) == r['outcome']),
                ou_model=sum(bll(r['model_over'], r['over']) for r in ou) / len(ou),
                ou_open=sum(bll(r['ou_open'], r['over']) for r in ou) / len(ou),
                ou_close=sum(bll(r['ou_close'], r['over']) for r in ou) / len(ou))


VARIANTS = [dict(name='baseline')] + \
    [dict(name=f'hl{h}', half_life=h) for h in (180, 270, 540, 730)] + \
    [dict(name=f'ridge{r}', ridge=r) for r in (.01, .05, .1)] + \
    [dict(name=f'sot{w}', sot=w) for w in (.3, .5, .7)]


def main(names=None, output=ROOT / 'reports' / 'experiments.json'):
    variants = [v for v in VARIANTS if not names or v['name'] in names]
    jobs = [(league, v) for v in variants for league in LEAGUES]
    results = defaultdict(list)
    with ProcessPoolExecutor() as pool:
        for league, name, recs in pool.map(run_variant, jobs):
            results[name] += recs
    table = {name: dict(overall=summarize(recs),
                        by_league={lg: summarize([r for r in recs if r['league'] == lg]) for lg in LEAGUES})
             for name, recs in results.items()}
    atomic_write(output, json.dumps(dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                         seasons=SEASONS, table=table), indent=1))
    atomic_write(output.with_suffix('.records.json'), json.dumps(results))
    for name, t in table.items():
        o = t['overall']
        print(f"{name:10s} n={o['matches']} 1X2 model {o['model']:.4f} open {o['market_open']:.4f} close {o['market_close']:.4f} "
              f"| acc {o['model_accuracy']:.3f}/{o['close_accuracy']:.3f} | OU model {o['ou_model']:.4f} open {o['ou_open']:.4f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('variants', nargs='*')
    main(parser.parse_args().variants)
