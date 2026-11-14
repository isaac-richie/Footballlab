"""Stress test of the NBA score distribution on the picks people actually play.

For every game with a closing line, the distribution is priced the way the app
prices it (from the line, or from the model ratings alone) and graded on:

    moneyline     the winner, overtime included
    spread        alternate spreads from line-9 to line+9
    total         alternate totals from line-12 to line+12
    team_total    each team's points, five lines around its expectation
    combo         favourite wins + over/under at several totals, cover + over/under

Scores are log loss per family and calibration: do 70%, 80%, 90% picks win that
often? Pushes are left out. The width of the distribution (margin sd, total sd,
favourite-total link, margin slope) is tuned on 2023-24 and 2024-25 and the result
is reported once on 2025-26.

Needs reports/nba_lab.records.json from tools/nba_lab.py.

    python3 tools/nba_calib.py                # both sources
    python3 tools/nba_calib.py --only model   # one source
"""
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nba_model as M  # noqa: E402
from quality import atomic_write  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TUNE, HOLD = (2024, 2025), (2026,)
FAMILIES = ('moneyline', 'spread', 'total', 'team_total', 'combo')
BINS = [(.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.0)]
_RECS = []


def _load():
    global _RECS
    seen, out = set(), []
    for r in json.loads((ROOT / 'reports' / 'nba_lab.records.json').read_text()):
        c = ((r.get('line') or {}).get('close') or {})
        if r['id'] in seen or not r['final'] or c.get('spread') is None or c.get('total') is None:
            continue
        seen.add(r['id'])
        out.append(r)
    _RECS = out


def picks(r, width, source):
    """[(family, p, won)] for one game; p is the chance of the stated outcome."""
    close = r['line']['close']
    means = M.implied(close, r['model'], width) if source == 'line' else M.stretch(r['model'], width.get('stretch', 1.0))
    g = M.distribution(*means, width=width)['grid']
    fm, ft = r['final'][0] - r['final'][1], sum(r['final'])
    margin, total, th, ta = {}, {}, {}, {}
    for (x, y), p in g.items():
        margin[x - y] = margin.get(x - y, 0) + p
        total[x + y] = total.get(x + y, 0) + p
        th[x] = th.get(x, 0) + p
        ta[y] = ta.get(y, 0) + p

    def over(d, line):
        return sum(p for k, p in d.items() if k > line)

    out = []
    ph = over(margin, 0)
    out.append(('moneyline', ph, fm > 0))
    s0, t0 = close['spread'], close['total']
    for k in (-9, -6, -3, 0, 3, 6, 9):
        line = s0 + k                      # home line: covers when margin + line > 0
        if fm + line == 0:
            continue
        push = margin.get(-line, 0) if float(line).is_integer() else 0
        out.append(('spread', over(margin, -line) / (1 - push), fm + line > 0))
    for k in range(-12, 13, 3):
        line = t0 + k
        if ft == line:
            continue
        push = total.get(line, 0) if float(line).is_integer() else 0
        out.append(('total', over(total, line) / (1 - push), ft > line))
    for d, e, pts in ((th, means[0], r['final'][0]), (ta, means[1], r['final'][1])):
        for k in (-8, -4, 0, 4, 8):
            line = math.floor(e) + .5 + k
            out.append(('team_total', over(d, line), pts > line))
    # Combos, all from one pass over the joint grid (favourite by the priced expectation).
    fav = 1 if means[0] >= means[1] else -1
    T = math.floor(t0) + .5
    S = s0 if not float(s0).is_integer() else s0 + .5 * fav   # half-point main spread, no pushes
    defs = [('fav_win_over', lambda m, t, k: m * fav > 0 and t > T + k, (-10, -5, 0)),
            ('fav_win_under', lambda m, t, k: m * fav > 0 and t < T + k, (0, 5, 10)),
            ('fav_cover_over', lambda m, t, k: (m + S) * fav > 0 and t > T + k, (0,)),
            ('fav_cover_under', lambda m, t, k: (m + S) * fav > 0 and t < T + k, (0,)),
            ('dog_cover_over', lambda m, t, k: (m + S) * fav < 0 and t > T + k, (0,)),
            ('dog_cover_under', lambda m, t, k: (m + S) * fav < 0 and t < T + k, (0,))]
    combos = [(f, k) for _, f, ks in defs for k in ks]
    acc = [0.0] * len(combos)
    for (x, y), p in g.items():
        m, t = x - y, x + y
        for i, (f, k) in enumerate(combos):
            if f(m, t, k):
                acc[i] += p
    for (f, k), p in zip(combos, acc):
        out.append(('combo', p, f(fm, ft, k)))
    return out


def _grade(args):
    width, source, seasons = args
    rows = []
    for r in _RECS:
        if r['season'] in seasons:
            rows += picks(r, width, source)
    return rows


def score(rows):
    out = {}
    for fam in FAMILIES:
        sub = [(p, y) for f, p, y in rows if f == fam]
        if not sub:
            continue
        ll = -sum(math.log(min(1 - 1e-6, max(1e-6, p if y else 1 - p))) for p, y in sub) / len(sub)
        bins = []
        for lo, hi in BINS:
            # Each prediction is read as a pick of its likelier side, so 30% over = 70% under.
            b = [(max(p, 1 - p), y if p >= .5 else not y) for p, y in sub if lo <= max(p, 1 - p) < hi]
            if len(b) >= 30:
                n = len(b)
                pred = sum(p for p, _ in b) / n
                hit = sum(y for _, y in b) / n
                se = math.sqrt(pred * (1 - pred) / n)
                bins.append(dict(bin=f'{int(lo * 100)}-{int(hi * 100)}%', picks=n, predicted=round(pred, 4), won=round(hit, 4),
                                 gap=round(hit - pred, 4), z=round((hit - pred) / se, 2) if se else None))
        sure = [(max(p, 1 - p), y if p >= .5 else not y) for p, y in sub if max(p, 1 - p) >= .7]
        out[fam] = dict(picks=len(sub), log_loss=round(ll, 5), calibration=bins,
                        sure_70_plus=dict(picks=len(sure), predicted=round(sum(p for p, _ in sure) / max(1, len(sure)), 4),
                                          won=round(sum(y for _, y in sure) / max(1, len(sure)), 4)))
    return out


def evaluate(pool, widths, source, seasons):
    res = pool.map(_grade, [(w, source, seasons) for w in widths])
    return [score(r) for r in res]


def total_loss(sc, fams):
    return sum(sc[f]['log_loss'] for f in fams if f in sc)


def tune(pool, start, source, log, rounds=2):
    """Coordinate search: (model: stretch first), margin, total, link and slope."""
    best = dict(start)
    steps = ([('stretch', [1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3], ('moneyline', 'spread', 'combo'))] if source == 'model' else []) + [('margin', [-1.5, -1, -.5, 0, .5, 1, 1.5], ('moneyline', 'spread', 'team_total')),
             ('total', [-1.5, -1, -.5, 0, .5, 1, 1.5], ('total', 'team_total')),
             ('link', [-.15, -.1, -.05, 0, .05, .1, .15], ('combo',)),
             ('slope', [-.3, -.2, -.1, 0, .1, .2], ('moneyline', 'spread', 'combo'))]
    history = []
    for rnd in range(rounds):
        for key, deltas, fams in steps:
            cands = [dict(best, **{key: round(best[key] + d, 3)}) for d in deltas]
            if key == 'link':
                cands = [dict(best, link=round(d, 3)) for d in deltas]
            if key == 'stretch':
                cands = [dict(best, stretch=d) for d in deltas]
            if key == 'slope':
                cands = [dict(best, slope=round(d, 3)) for d in deltas]
            scores = evaluate(pool, cands, source, TUNE)
            losses = [total_loss(s, fams) for s in scores]
            i = min(range(len(cands)), key=lambda j: losses[j])
            history.append(dict(round=rnd, key=key, tried=[c[key] for c in cands], loss=[round(x, 5) for x in losses], chose=cands[i][key]))
            log(f'{source} round {rnd} {key}: ' + ', '.join(f'{c[key]}:{x:.5f}' for c, x in zip(cands, losses)) + f' -> {cands[i][key]}')
            best = cands[i]
    return best, history


def main():
    _load()
    log = lambda m: print(m, flush=True)
    log(f'{len(_RECS)} games with closing lines: ' + ', '.join(f'{s}: {sum(r["season"] == s for r in _RECS)}' for s in sorted({r["season"] for r in _RECS})))
    report = dict(method=__doc__.strip().split('\n\n')[0])
    with Pool(initializer=_load) as pool:
        only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
        try:
            report.update(json.loads((ROOT / 'reports' / 'nba_calib.json').read_text()))   # keep the other source's result
        except (OSError, ValueError):
            pass
        for source, start in (('line', dict(M.LINE_WIDTH)), ('model', dict(M.MODEL_WIDTH))):
            if only and source != only:
                continue
            before_t, before_h = evaluate(pool, [start], source, TUNE)[0], evaluate(pool, [start], source, HOLD)[0]
            best, history = tune(pool, start, source, log, rounds=1 if source == 'model' else 2)
            after_t, after_h = evaluate(pool, [best], source, TUNE)[0], evaluate(pool, [best], source, HOLD)[0]
            report[source] = dict(start=start, chosen=best, search=history,
                                  tuning=dict(before=before_t, after=after_t), holdout=dict(before=before_h, after=after_h))
            log(f'{source}: chosen {best}')
            for fam in FAMILIES:
                b, a = before_h.get(fam), after_h.get(fam)
                if b and a:
                    log(f'  holdout {fam:10s} log loss {b["log_loss"]:.5f} -> {a["log_loss"]:.5f}; 70%+ picks: said {a["sure_70_plus"]["predicted"]:.3f}, won {a["sure_70_plus"]["won"]:.3f} ({a["sure_70_plus"]["picks"]})')
    atomic_write(ROOT / 'reports' / 'nba_calib.json', json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
