"""Training targets for team ratings: bookmaker-implied goals instead of raw scorelines.

A scoreline is one noisy draw; the closing price already reflects everything the
market knew about both teams on the day. Fitting attack/defence ratings to the
goal expectancies implied by closing 1X2 and over/under prices (three parts
market, one part actual score), with a 90-day half-life, cut out-of-time 1X2 log
loss from 1.0120 to 1.0052 over 5,109 matches in 2024-26
(tools/market_ratings_experiment.py). Matches without prices keep their score.

Private Lab only: these come from football-data.co.uk and are never published.
"""
import json
from pathlib import Path

import odds_data
from implied import implied_rates_rho
from quality import atomic_write

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'reports' / 'implied_goals.json'
MARKET_WEIGHT = 0.75
HALF_LIFE_DAYS = 90
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
    stamp = odds_data.MARKET.stat().st_mtime_ns if odds_data.MARKET.exists() else 0
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


def targets(rows):
    """Copies of rows whose goals are blended towards the market's implied goals."""
    t, w = table(), MARKET_WEIGHT
    out = []
    for m in rows:
        imp = t.get('|'.join((m['league_id'], m['date'], m['home'], m['away'])))
        out.append({**m, 'goals': [w * imp[0] + (1 - w) * m['goals'][0], w * imp[1] + (1 - w) * m['goals'][1]]} if imp else m)
    return out
