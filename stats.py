"""Provenance-preserving importer for supplemental match statistics.

The goal feed does not contain shots or disciplinary events.  This module does
not scrape a site or guess missing columns: it accepts an explicitly supplied
CSV, validates it against known fixtures, and keeps its source label with every
record.  Predictions are withheld until enough validated rows exist.
"""
import csv
import datetime as dt
import json
import math
from pathlib import Path

from quality import atomic_write

REQUIRED = ('league_id', 'date', 'home', 'away', 'home_shots', 'away_shots',
            'home_red_cards', 'away_red_cards', 'source')


def load(path):
    return json.loads(path.read_text()) if path.exists() else {'records': [], 'imported_at': None}


def import_csv(path, destination, fixtures):
    """Import only stats that map exactly to a known completed fixture."""
    fixture_keys = {(m['league_id'], m['date'], m['home'], m['away'])
                    for m in fixtures if m['goals'] is not None}
    with open(path, newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED) - set(reader.fieldnames or [])
        if missing:
            raise ValueError('Stats CSV is missing columns: ' + ', '.join(sorted(missing)))
        parsed = []
        for number, row in enumerate(reader, 2):
            key = tuple(row[k].strip() for k in ('league_id', 'date', 'home', 'away'))
            try:
                dt.date.fromisoformat(key[1])
                shots = [int(row[k]) for k in ('home_shots', 'away_shots')]
                reds = [int(row[k]) for k in ('home_red_cards', 'away_red_cards')]
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Invalid numeric/date value at CSV row {number}') from exc
            if key not in fixture_keys:
                raise ValueError(f'CSV row {number} does not exactly match a known completed fixture: {key}')
            if any(x < 0 or x > 80 for x in shots) or any(x < 0 or x > 4 for x in reds):
                raise ValueError(f'Implausible shot/card value at CSV row {number}')
            source = row['source'].strip()
            if not source:
                raise ValueError(f'CSV row {number} has no source label')
            parsed.append(dict(league_id=key[0], date=key[1], home=key[2], away=key[3],
                               home_shots=shots[0], away_shots=shots[1],
                               home_red_cards=reds[0], away_red_cards=reds[1], source=source))
    old = load(destination)
    merged = {(r['league_id'], r['date'], r['home'], r['away']): r for r in old['records']}
    merged.update({(r['league_id'], r['date'], r['home'], r['away']): r for r in parsed})
    payload = dict(imported_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   records=sorted(merged.values(), key=lambda r: (r['date'], r['league_id'], r['home'])))
    atomic_write(destination, json.dumps(payload, indent=2))
    return dict(imported=len(parsed), total=len(payload['records']), sources=sorted({r['source'] for r in parsed}))


def poisson_over(rate, line):
    probability = math.exp(-rate)
    under_or_equal = probability
    for goal in range(1, int(math.floor(line)) + 1):
        probability *= rate / goal
        under_or_equal += probability
    return 1 - under_or_equal


def market_rates(records, home, away, asof, field_home, field_away, minimum=200, prior_games=12):
    """Conservative position-aware rate estimates for a supplemental count."""
    rows = [r for r in records if r['date'] < asof]
    if len(rows) < minimum:
        return None
    cutoff = dt.date.fromisoformat(asof)
    weighted = [(r, .5 ** (max(0, (cutoff - dt.date.fromisoformat(r['date'])).days) / 365)) for r in rows]
    weight = sum(w for _, w in weighted)
    league_home = sum(r[field_home] * w for r, w in weighted) / weight
    league_away = sum(r[field_away] * w for r, w in weighted) / weight

    def team(team, side, field, prior):
        chosen = [(r, w) for r, w in weighted if r[side] == team]
        return ((sum(r[field] * w for r, w in chosen) + prior_games * prior) /
                (sum(w for _, w in chosen) + prior_games))
    home_rate = team(home, 'home', field_home, league_home) * team(away, 'away', field_home, league_home) / max(league_home, .01)
    away_rate = team(away, 'away', field_away, league_away) * team(home, 'home', field_away, league_away) / max(league_away, .01)
    counts = {t: sum(t in (r['home'], r['away']) for r in rows) for t in (home, away)}
    return max(.01, home_rate), max(.01, away_rate), counts, len(rows)


def own_count_rates(records, home, away, asof, field_home, field_away, minimum=300, prior_games=18):
    """Rates for events owned by the team itself (for example red cards).

    Unlike shots, opponent rates are not treated as a defensive factor: doing
    so would conflate an opponent's own cards with cards issued to its rivals.
    """
    rows = [r for r in records if r['date'] < asof]
    if len(rows) < minimum:
        return None
    cutoff = dt.date.fromisoformat(asof)
    weighted = [(r, .5 ** (max(0, (cutoff - dt.date.fromisoformat(r['date'])).days) / 365)) for r in rows]
    def positional(team, side, field):
        chosen = [(r, w) for r, w in weighted if r[side] == team]
        league = sum(r[field] * w for r, w in weighted) / sum(w for _, w in weighted)
        return (sum(r[field] * w for r, w in chosen) + prior_games * league) / (sum(w for _, w in chosen) + prior_games)
    counts = {t: sum(t in (r['home'], r['away']) for r in rows) for t in (home, away)}
    return positional(home, 'home', field_home), positional(away, 'away', field_away), counts, len(rows)
