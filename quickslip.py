"""Quick Slip: build a slip to a strategy from every priced football and NBA pick.

Strategies (one pick per game, games treated as independent):
  safest   the surest pick in each game, surest games first
  balanced mostly bankers (80%+) with two swings (60-75%); a new seed reshuffles the swings
  value    picks priced between fair odds 1.35 and 1.85, best confidence first: the band where a
           confident pick still pays something
  banker   two or three near-certain bankers (85%+) first, then the surest 70-85% picks

`when` filters by kickoff in the viewer's own clock (tz = minutes east of UTC):
early before 15:00, afternoon 15:00-18:59, late 19:00 onward.
"""
import datetime as dt
import math
import random

STRATEGIES = ('safest', 'balanced', 'value', 'banker')
FOOTBALL_MARKETS = ('1x2', 'dc', 'ou15', 'ou25', 'ou35', 'btts')
NBA_MARKETS = ('winner', 'total')
FLOOR = .55                 # nothing below this goes on a quick slip


def local_hour(kickoff, tz_minutes):
    if not kickoff:
        return None
    try:
        t = dt.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
    except ValueError:
        return None
    return (t + dt.timedelta(minutes=tz_minutes)).hour


def in_window(hour, when):
    if when in (None, '', 'all') or hour is None:
        return when in (None, '', 'all')
    return {'early': hour < 15, 'afternoon': 15 <= hour < 19, 'late': hour >= 19}.get(when, True)


def choose(legs, n, strategy='balanced', seed=0, score=lambda l: 0):
    """Pick up to n legs, one per game, by strategy. `score` ranks within the value strategy."""
    by_game = {}
    for l in legs:
        if l['probability'] >= FLOOR:
            by_game.setdefault(l['game'], []).append(l)
    best = {g: max(ls, key=lambda l: l['probability']) for g, ls in by_game.items()}
    rng = random.Random(seed)
    if strategy == 'safest':
        return sorted(best.values(), key=lambda l: -l['probability'])[:n]
    if strategy == 'value':
        pool = [max(ls, key=score) for ls in ([l for l in ls if 1.35 <= 1 / l['probability'] <= 1.85] for ls in by_game.values()) if ls]
        pool.sort(key=lambda l: (-score(l), -l['probability']))
        if seed:
            pool = sorted(pool[:max(n * 2, n)], key=lambda l: -score(l) * rng.uniform(.85, 1.15))
        cap, per, out = max(2, -(-n // 3)), {}, []      # no market takes more than about a third of the slip
        for l in pool:
            if per.get(l['market'], 0) < cap:
                out.append(l); per[l['market']] = per.get(l['market'], 0) + 1
            if len(out) == n:
                break
        return out
    if strategy == 'banker':
        bankers = sorted((l for l in best.values() if l['probability'] >= .85), key=lambda l: -l['probability'])[:min(3, n)]
        used = {l['game'] for l in bankers}
        rest = [max((x for x in ls if .70 <= x['probability'] < .85), key=lambda x: x['probability'], default=None)
                for g, ls in by_game.items() if g not in used]
        rest = sorted((l for l in rest if l), key=lambda l: -l['probability'])
        if seed:
            rng.shuffle(rest)
            rest.sort(key=lambda l: -l['probability'] * rng.uniform(.9, 1.1))
        return bankers + rest[:n - len(bankers)]
    # balanced: bankers plus two swings from other games
    swings_n = min(2, max(0, n - 1))
    bank = sorted((l for l in best.values() if l['probability'] >= .80), key=lambda l: -l['probability'])
    if seed:
        bank = sorted(bank[:n * 2], key=lambda l: -l['probability'] * rng.uniform(.95, 1.05))
    bank = bank[:n - swings_n]
    used = {l['game'] for l in bank}
    swing_pool = [x for g, ls in by_game.items() if g not in used for x in ls if .60 <= x['probability'] <= .75]
    rng.shuffle(swing_pool)
    swings, seen = [], set()
    for x in sorted(swing_pool, key=lambda x: -x['probability'] * (rng.uniform(.8, 1.2) if seed else 1)):
        if x['game'] not in seen:
            swings.append(x); seen.add(x['game'])
        if len(swings) == swings_n:
            break
    out = bank + swings
    if len(out) < n:                                   # not enough bankers or swings: fill with the surest left
        used = {l['game'] for l in out}
        out += sorted((l for g, l in best.items() if g not in used), key=lambda l: -l['probability'])[:n - len(out)]
    return out


def summary(legs):
    p = math.prod(l['probability'] for l in legs) if legs else 0.0
    return dict(probability=p, fair_odds=(1 / p) if p else None)
