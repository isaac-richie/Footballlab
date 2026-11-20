"""Can we predict total corners better than the league's own average? (research, walk-forward)

Data: tools/fetch_corners.py (API-Football match statistics, git-ignored cache).
Every match is forecast from earlier matches only (a 365-day window before its date).

    base     the league's frequency of each total over the past year (what the site shows now)
    teams    team corner ratings: won and conceded, home and away, recent games weighted more,
             shrunk towards the league; total ~ negative binomial with a league dispersion
    shots    as teams, with each rating blended with the team's shots ratings (shots lead to corners)

Settings are chosen on 2024-25 (from 1 November, once teams have history) and reported once on
2025-26 and 2026-27. A model is useful only if it beats `base` on log loss on those seasons and its
confident picks (70%+) win about as often as they say.

    python3 tools/corners_lab.py
"""
import datetime as dt
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from quality import atomic_write  # noqa: E402

DATA = ROOT / 'reports' / 'cache' / 'match_stats.json'
OUT = ROOT / 'reports' / 'corners_lab.json'
LINES = (8.5, 9.5, 10.5, 11.5)
TUNE, HOLD = (2024,), (2025, 2026)
TUNE_FROM = '2024-11-01'
WINDOW = 365


def load():
    rows = []
    for g in json.loads(DATA.read_text()).values():
        s = g['stats']
        c = [s[0].get('corners'), s[1].get('corners')]
        if None in c:
            continue
        rows.append(dict(g, corners=[int(c[0]), int(c[1])], shots=[s[0].get('shots'), s[1].get('shots')]))
    return sorted(rows, key=lambda r: r['date'])


def nb_tail(mu, r, line):
    """P(X > line) for a negative binomial with mean mu and size r (r -> inf is Poisson)."""
    k_max = int(line)
    if r > 1e6:
        p0, cdf, term = math.exp(-mu), 0.0, math.exp(-mu)
        for k in range(k_max + 1):
            cdf += term
            term *= mu / (k + 1)
        return max(1e-9, min(1 - 1e-9, 1 - cdf))
    p = r / (r + mu)
    term = p ** r
    cdf = 0.0
    for k in range(k_max + 1):
        cdf += term
        term *= (k + r) / (k + 1) * (1 - p)
    return max(1e-9, min(1 - 1e-9, 1 - cdf))


def ratings(hist, date, half_life, shrink, shots_w):
    """Team multipliers from history before `date` (weighted, shrunk towards 1)."""
    d0 = dt.date.fromisoformat(date)
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])   # w, corners for, corners against, shots for, shots against
    lg = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]                      # w, home corners, away corners, home shots, away shots, w with shots
    for r in hist:
        age = (d0 - dt.date.fromisoformat(r['date'])).days
        w = 0.5 ** (age / half_life)
        h, a = r['corners']
        sh, sa = r['shots']
        lg[0] += w; lg[1] += w * h; lg[2] += w * a
        if sh is not None and sa is not None:
            lg[3] += w * sh; lg[4] += w * sa; lg[5] += w
        for team, cf, ca, sf, sg, home in ((r['home'], h, a, sh, sa, True), (r['away'], a, h, sa, sh, False)):
            x = acc[team]
            # express each game relative to the league's home/away level so venue does not bias ratings
            x[0] += w; x[1] += w * cf / (1.1 if home else 0.9); x[2] += w * ca / (0.9 if home else 1.1)
            if sf is not None and sg is not None:
                x[3] += w * sf; x[4] += w * sg
    if not lg[0]:
        return None
    mh, ma = lg[1] / lg[0], lg[2] / lg[0]
    mean = (mh + ma) / 2
    ms = (lg[3] + lg[4]) / (2 * lg[5]) if lg[5] else None
    out = {}
    for team, (w, cf, ca, sf, sg) in acc.items():
        att = (cf + shrink * mean) / ((w + shrink) * mean)
        dfn = (ca + shrink * mean) / ((w + shrink) * mean)
        if shots_w and ms:
            satt = (sf + shrink * ms) / ((w + shrink) * ms)
            sdef = (sg + shrink * ms) / ((w + shrink) * ms)
            att = (1 - shots_w) * att + shots_w * satt
            dfn = (1 - shots_w) * dfn + shots_w * sdef
        out[team] = (att, dfn, w)
    return dict(home=mh, away=ma, teams=out)


def dispersion(hist, mu_fn):
    """Negative binomial size r from method of moments on the window's totals."""
    totals = [sum(r['corners']) for r in hist]
    if len(totals) < 50:
        return 1e9
    m = sum(totals) / len(totals)
    v = sum((t - m) ** 2 for t in totals) / (len(totals) - 1)
    return m * m / (v - m) if v > m else 1e9


def run(rows, half_life, shrink, shots_w, base_only=False):
    """[(league, season, date, model probs per line, base probs per line, total)]"""
    by_league = defaultdict(list)
    for r in rows:
        by_league[r['league_id']].append(r)
    out = []
    for lg, games in by_league.items():
        dates = sorted({g['date'] for g in games})
        for d in dates:
            start = (dt.date.fromisoformat(d) - dt.timedelta(days=WINDOW)).isoformat()
            hist = [g for g in games if start <= g['date'] < d]
            if len(hist) < 120:
                continue
            totals = [sum(g['corners']) for g in hist]
            base = {L: max(1e-6, min(1 - 1e-6, sum(t > L for t in totals) / len(totals))) for L in LINES}
            rt = None if base_only else ratings(hist, d, half_life, shrink, shots_w)
            r = dispersion(hist, None)
            for g in (g for g in games if g['date'] == d):
                total = sum(g['corners'])
                if rt and g['home'] in rt['teams'] and g['away'] in rt['teams']:
                    ah, dh, _ = rt['teams'][g['home']]
                    aa, da, _ = rt['teams'][g['away']]
                    mu = rt['home'] * ah * da + rt['away'] * aa * dh
                    model = {L: nb_tail(mu, r, L) for L in LINES}
                else:
                    model = dict(base)
                out.append((lg, g['season'], d, model, base, total))
    return out


def ll(p, y):
    return -math.log(p if y else 1 - p)


def score(recs, seasons, which, since=None):
    sub = [x for x in recs if x[1] in seasons and (since is None or x[2] >= since)]
    if not sub:
        return None
    idx = 3 if which == 'model' else 4
    loss = sum(ll(x[idx][L], x[5] > L) for x in sub for L in LINES) / (len(sub) * len(LINES))
    conf = [(max(x[idx][L], 1 - x[idx][L]), (x[5] > L) == (x[idx][L] >= .5)) for x in sub for L in LINES if max(x[idx][L], 1 - x[idx][L]) >= .7]
    cal = dict(picks=len(conf), said=round(sum(p for p, _ in conf) / len(conf), 4), won=round(sum(w for _, w in conf) / len(conf), 4)) if conf else dict(picks=0)
    return dict(games=len(sub), log_loss=round(loss, 5), sure_70_plus=cal)


def main():
    rows = load()
    print('games with corners:', len(rows), {s: sum(r['season'] == s for r in rows) for s in (2024, 2025, 2026)}, flush=True)
    grid = list(itertools.product((60, 120, 240), (3, 8, 20), (0.0, 0.3, 0.6)))
    best, results = None, []
    for hl, k, sw in grid:
        recs = run(rows, hl, k, sw)
        s = score(recs, TUNE, 'model', TUNE_FROM)
        results.append(dict(half_life=hl, shrink=k, shots=sw, tune=s))
        if best is None or s['log_loss'] < best[0]['log_loss']:
            best = (s, (hl, k, sw), recs)
        print(hl, k, sw, s['log_loss'], flush=True)
    s, (hl, k, sw), recs = best
    report = dict(chosen=dict(half_life=hl, shrink=k, shots=sw), lines=LINES,
                  tune=dict(model=score(recs, TUNE, 'model', TUNE_FROM), base=score(recs, TUNE, 'base', TUNE_FROM)),
                  holdout={str(se): dict(model=score(recs, (se,), 'model'), base=score(recs, (se,), 'base')) for se in HOLD},
                  by_league={lg: dict(model=score([x for x in recs if x[0] == lg], HOLD, 'model'), base=score([x for x in recs if x[0] == lg], HOLD, 'base'))
                             for lg in sorted({x[0] for x in recs})},
                  grid=sorted(results, key=lambda x: x['tune']['log_loss'])[:10],
                  generated_at=dt.datetime.now().isoformat(timespec='seconds'), method=__doc__.split('\n\n')[0])
    atomic_write(OUT, json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ('chosen', 'tune', 'holdout')}, indent=1))


if __name__ == '__main__':
    main()
