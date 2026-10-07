"""Automated parlay (accumulator) builder.

Candidate legs come from the same priced forecasts as the rest of the app
(bookmaker-implied where odds exist, otherwise the model). One leg per
fixture, so legs are treated as independent and the combined probability is
their product. Building is deterministic for a seed: "shuffle" is a new seed.
"""
import datetime as dt
import math
import random

MARKETS = {
    '1x2': 'Match result', 'dc': 'Double chance', 'ou15': 'Over/Under 1.5', 'ou25': 'Over/Under 2.5',
    'ou35': 'Over/Under 3.5', 'btts': 'Both teams score',
}


def legs_for(fixture, d, source):
    """All candidate legs for one fixture from its distribution `d`."""
    h, a = fixture['home'], fixture['away']
    p = d['probabilities']
    o = d['total_goal_overs']
    rows = [
        ('1x2', f'{h} win', p[0]), ('1x2', 'Draw', p[1]), ('1x2', f'{a} win', p[2]),
        ('dc', f'{h} or draw', p[0] + p[1]), ('dc', f'{a} or draw', p[1] + p[2]), ('dc', f'{h} or {a}', p[0] + p[2]),
        ('ou15', 'Over 1.5', o['1.5']), ('ou15', 'Under 1.5', 1 - o['1.5']),
        ('ou25', 'Over 2.5', o['2.5']), ('ou25', 'Under 2.5', 1 - o['2.5']),
        ('ou35', 'Over 3.5', o['3.5']), ('ou35', 'Under 3.5', 1 - o['3.5']),
        ('btts', 'Both teams score', d['btts']), ('btts', 'Not both teams score', 1 - d['btts']),
    ]
    key = f"{fixture['league_id']}|{fixture['date']}|{h}|{a}"
    return [dict(id=f'{key}|{m}|{sel}', fixture=key, league_id=fixture['league_id'], date=fixture['date'],
                 home=h, away=a, market=m, market_label=MARKETS[m], selection=sel, probability=prob,
                 fair_odds=1 / prob if prob > 0 else None, source=source) for m, sel, prob in rows]


def build(candidates, n, min_p=0.0, max_p=1.0, markets=None, locked=(), exclude=(), seed=0, mode='balanced'):
    """Pick n legs, one per fixture.

    mode 'safest' takes the most likely leg per fixture and the most likely fixtures;
    'balanced' samples among each fixture's eligible legs, weighted by probability,
    so shuffling gives genuinely different slips.
    """
    by_id = {c['id']: c for c in candidates}
    chosen = [by_id[i] for i in locked if i in by_id][:n]
    used = {c['fixture'] for c in chosen}
    pool = [c for c in candidates if min_p <= c['probability'] <= max_p and (not markets or c['market'] in markets)
            and c['fixture'] not in used and c['fixture'] not in set(exclude)]
    per_fixture = {}
    for c in pool:
        per_fixture.setdefault(c['fixture'], []).append(c)
    rng = random.Random(seed)
    picks = []
    for fixture, legs in per_fixture.items():
        if mode == 'safest' or seed == 0:
            picks.append(max(legs, key=lambda c: c['probability']))
        else:
            weights = [c['probability'] ** 2 for c in legs]
            picks.append(rng.choices(legs, weights)[0])
    if mode == 'safest' or seed == 0:
        picks.sort(key=lambda c: -c['probability'])
    else:
        rng.shuffle(picks)
        picks.sort(key=lambda c: -c['probability'] * rng.uniform(0.85, 1.15))
    chosen += picks[:max(0, n - len(chosen))]
    prob = math.prod(c['probability'] for c in chosen) if chosen else 0.0
    return dict(legs=chosen, probability=prob, fair_odds=1 / prob if prob > 0 else None,
                requested=n, complete=len(chosen) == n,
                note='Legs are from different fixtures and treated as independent. Fair odds have no bookmaker margin; '
                     'any price below them is negative value.')
