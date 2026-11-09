"""Training targets for team ratings: bookmaker-implied goals instead of raw scorelines.

A scoreline is one noisy draw; the closing price already reflects everything the
market knew about both teams on the day. Fitting attack/defence ratings to the
goal expectancies implied by closing 1X2 and over/under prices (three parts
market, one part actual score), with a 90-day half-life, cut out-of-time 1X2 log
loss from 1.0120 to 1.0052 over 5,109 matches in 2024-26
(tools/market_ratings_experiment.py). Matches without prices keep their score.

fit() is the production rating fit used by every forecast. Its settings were
chosen on 2023-25 and then scored once on 2025-27 (3,330 matches, eight
leagues, weekly refits on earlier results; tools/accuracy_lab.py). An exactly
solved fit, lighter shrinkage, 90% market targets, a 60-day half-life and the
calibration below moved holdout 1X2 log loss from 1.0075 to 0.9968 in the seven
priced leagues. Leagues without prices (Saudi) fall back to scorelines with a
365-day half-life: 0.9239 to 0.9185.

Private Lab only: these come from football-data.co.uk and are never published.
"""
import json
from pathlib import Path

import odds_data
from implied import implied_rates_rho
from model import fit_dixon_coles, fit_ratings
from quality import atomic_write

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'reports' / 'implied_goals.json'
MARKET_WEIGHT = 0.9
HALF_LIFE_DAYS = 60
RIDGE = 0.005
GOALS_HALF_LIFE_DAYS, GOALS_RIDGE = 365, 0.01      # leagues with no prices
# Goal totals for leagues with no prices come from a second, more heavily shrunk fit:
# how many goals a team's games produce is noisier than who wins them. Weekly
# walk-forward refits on scorelines only (Aug 2025 - Nov 2026, six leagues, 2,608
# games) cut over 1.5/2.5/3.5 and both-teams-score log loss by 0.67% (better in all
# six leagues and all three periods) with 1X2 unchanged, and its 75%+ goal picks came
# in at the rate stated (79.7% said, 79.5% won) where the single fit overpromised
# (80.9% said, 79.2% won). Ridge 0.06-0.2 all did about as well; 0.1 is mid-plateau.
TOTALS_RIDGE = 0.1
# Temperature on log-probabilities and a draw log-odds shift, fitted on 2023-25
# prequential forecasts: the shrunken ratings are slightly too timid and too
# short of draws. Only for the model's own numbers; market prices are left alone.
CALIBRATION = dict(market=dict(temperature=0.91, draw_shift=0.12),
                   goals=dict(temperature=0.94, draw_shift=0.09))
_memo = {}


def _implied(rec):
    o = rec['odds']
    h2h, ou = o.get('avg_close') or o.get('pin_close'), o.get('ou25_avg_close') or o.get('ou25_pin_close')
    if not h2h or not ou:
        return None
    lh, la, _, err = implied_rates_rho(odds_data.no_vig(h2h), odds_data.no_vig(ou)[0], 0.0, (1.4, 1.1))
    return [round(lh, 4), round(la, 4)] if err < .03 else None


def table():
    """{'league|date|home|away': [home xG, away xG]} for every priced, finished match. Cached on disk."""
    # The tag re-keys the cache when record naming changes (football-data's own names for unlinked clubs).
    stamp = [odds_data.MARKET.stat().st_mtime_ns if odds_data.MARKET.exists() else 0, 'own-names']
    if _memo.get('stamp') == stamp:
        return _memo['table']
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    out = cached.get('table', {})
    if cached.get('stamp') != stamp:
        for r in odds_data.load().get('records', []):
            if r.get('upcoming') or not r.get('goals') or not (r.get('home') and r.get('away')):
                continue
            k = '|'.join((r['league_id'], r['date'], r['home'], r['away']))
            if k not in out:
                v = _implied(r)
                if v:
                    out[k] = v
        atomic_write(CACHE, json.dumps(dict(stamp=stamp, table=out)))
    _memo.update(stamp=stamp, table=out)
    return out


def targets(rows, weight=MARKET_WEIGHT):
    """Copies of rows whose goals are blended towards the market's implied goals."""
    t, w = table(), weight
    out = []
    for m in rows:
        imp = t.get('|'.join((m['league_id'], m['date'], m['home'], m['away'])))
        out.append({**m, 'goals': [w * imp[0] + (1 - w) * m['goals'][0], w * imp[1] + (1 - w) * m['goals'][1]]} if imp else m)
    return out


def fit(rows, asof, teams=(), start=None):
    """Production ratings from earlier matches: (expected(home, away), rho, metadata).

    start: the previous fit's expected.state, to warm-start a refit (backtests)."""
    shifted = targets(rows)
    recent = [i for i, m in enumerate(rows) if m['date'] >= _year_before(asof)]
    priced = sum(shifted[i] is not rows[i] for i in recent) > len(recent) / 2
    if priced:
        expected, meta = fit_ratings(shifted, asof, teams, HALF_LIFE_DAYS, RIDGE, start=start)
        rho, rho_meta = fit_dixon_coles(rows, asof, expected)
    else:
        expected, meta = fit_ratings(rows, asof, teams, GOALS_HALF_LIFE_DAYS, GOALS_RIDGE, start=start)
        rho, rho_meta = fit_dixon_coles(rows, asof, expected)
        totals, _ = fit_ratings(rows, asof, teams, GOALS_HALF_LIFE_DAYS, TOTALS_RIDGE)
        expected = with_totals(expected, totals)
        meta['totals_ridge'] = TOTALS_RIDGE
    meta.update(dixon_coles_rho=rho, **rho_meta, targets='market-implied goals' if priced else 'scorelines',
                calibration=CALIBRATION['market' if priced else 'goals'])
    return expected, rho, meta


def with_totals(expected, totals):
    """expected's home/away balance, scaled so the two rates add up to totals' expected goals."""
    def combined(home, away, season=None):
        lh, la = expected(home, away, season)
        th, ta = totals(home, away, season)
        k = (th + ta) / (lh + la)
        return max(.05, min(6, lh * k)), max(.05, min(6, la * k))
    combined.season_aware = getattr(expected, 'season_aware', False)
    combined.state = getattr(expected, 'state', None)
    return combined


def _year_before(asof):
    return f'{int(asof[:4]) - 1}{asof[4:]}'
