"""Push fixtures, results and the Lab's forecasts to the Beat the Lab league.

Run from the football-lab folder after refreshing data:

    python3 app.py refresh && python3 community/sync.py

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (never ship the
service key to the browser).  Only openly licensed data is published:
OpenFootball (CC0) and OpenLigaDB (ODbL, attribution and share-alike apply).
Bookmaker odds are never sent, and the Lab forecast uses the score model only.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import LEAGUES, distribution, fixture_rates, load  # noqa: E402
from prospective import fixture_id  # noqa: E402
import live_odds  # noqa: E402

PUBLIC_LEAGUES = [k for k in LEAGUES if k not in ('it.2', 'sa.1')]  # Serie B: no open current feed; Saudi: not openly licensed
LOOKAHEAD_DAYS, LOOKBACK_DAYS = 14, 10


def kickoff_times(league_id):
    """Exact UTC kickoff times from the live-odds cache, when it has them."""
    entry = live_odds.load_cache().get('leagues', {}).get(league_id, {})
    return {key: value['commence_time'] for key, value in entry.get('odds', {}).items() if value.get('commence_time')}


def build_rows(data, today=None):
    """Upcoming rows carry the Lab forecast; past rows carry only results."""
    today = today or dt.date.today()
    upcoming, results = [], []
    for league_id in PUBLIC_LEAGUES:
        window = [m for m in data['matches'] if m['league_id'] == league_id and
                  today - dt.timedelta(days=LOOKBACK_DAYS) <= dt.date.fromisoformat(m['date']) <= today + dt.timedelta(days=LOOKAHEAD_DAYS)]
        future = [m for m in window if m['goals'] is None and m['date'] > today.isoformat()]
        times = kickoff_times(league_id)
        base = lambda m: dict(id=fixture_id(m), league_id=league_id, league_name=LEAGUES[league_id].split(' — ')[-1],
                              season=m['season'], kickoff_date=m['date'], home=m['home'], away=m['away'])
        if future:
            _, rho, priced = fixture_rates(data, league_id, future, today.isoformat())
            for m, model_rates, *_ in priced:
                p = distribution(*model_rates, rho)['probabilities']
                upcoming.append(dict(base(m), status='scheduled', home_goals=None, away_goals=None,
                                     kickoff_at=times.get('|'.join((m['date'], m['home'], m['away']))),
                                     lab_home=round(p[0], 4), lab_draw=round(p[1], 4), lab_away=round(p[2], 4)))
        for m in window:
            if m['date'] > today.isoformat():
                continue
            if m['goals'] is not None:
                results.append(dict(base(m), status='finished', home_goals=m['goals'][0], away_goals=m['goals'][1]))
            elif (today - dt.date.fromisoformat(m['date'])).days > 2:
                results.append(dict(base(m), status='postponed', home_goals=None, away_goals=None))
    return upcoming, results


def push(rows, url, key):
    if not rows:
        return 0
    request = Request(url.rstrip('/') + '/rest/v1/fixtures?on_conflict=id', data=json.dumps(rows).encode(), method='POST',
                      headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                               'Prefer': 'resolution=merge-duplicates,return=minimal'})
    with urlopen(request, timeout=30) as response:
        if response.status not in (200, 201, 204):
            raise RuntimeError(f'Supabase answered {response.status}')
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='print what would be sent')
    args = parser.parse_args()
    from config import load_environment
    load_environment()
    upcoming, results = build_rows(load(fill_gaps=False))   # public: open-licence results only
    if args.dry_run:
        print(json.dumps(dict(upcoming=len(upcoming), results=len(results), sample=(upcoming or results)[:2]), indent=2))
        return
    url, key = os.environ.get('SUPABASE_URL', '').strip(), os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url or not key:
        raise SystemExit('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env first (see community/README.md).')
    # Upcoming rows include every column; result rows omit lab_* and kickoff_at so the
    # frozen Lab forecast and kickoff time are never overwritten.
    sent = push(upcoming, url, key) + push(results, url, key)
    print(json.dumps(dict(sent=sent, upcoming=len(upcoming), results=len(results))))


if __name__ == '__main__':
    main()
