"""Freeze future fixture forecasts and grade them against later source results."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path

from quality import atomic_write, digest

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'reports' / 'prospective'


def fixture_id(fixture):
    return digest({key: fixture[key] for key in ('league_id', 'date', 'home', 'away')})


def register(report, directory=REGISTRY):
    """Keep first overall and first research-eligible forecasts, without revisions."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    created = 0
    for item in report['fixtures']:
        if 'analysis' not in item:
            continue
        fixture = item['fixture']
        # Date-only fixtures have an unknown kickoff hour. A prior date is safe.
        if report.get('run_date', report['generated_at'][:10]) >= fixture['date']:
            continue
        analysis = item['analysis']
        record = {
            'schema': 1, 'fixture': fixture, 'registered_at': report['generated_at'],
            'run_id': report['run_id'], 'data_hash': report['data_hash'],
            'code_hash': report['code_hash'], 'model': report['model'],
            'readiness': analysis['readiness'], 'probabilities': analysis['probabilities'],
            'expected_goals': analysis['expected_goals'], 'over25': analysis['over25'],
            'btts': analysis['btts'], 'decision': analysis['decision']['action'],
            'pricing_source': analysis.get('pricing', {}).get('source', 'model'),
            'model_probabilities': analysis.get('model_view', {}).get('probabilities', analysis['probabilities']),
        }
        for cohort in ('first', 'eligible'):
            if cohort == 'eligible' and analysis['readiness']['status'] != 'research_only':
                continue
            path = (directory if cohort == 'first' else directory / 'eligible') / (fixture_id(fixture) + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, 'w') as handle:
                    json.dump(record, handle, indent=2, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            if cohort == 'first':
                created += 1
    return created


RESCHEDULE_DAYS = 45


def find_match(fixture, matches, by_pair):
    """The source match for a registered fixture: same date, else the same home/away pairing
    in that league moved by at most RESCHEDULE_DAYS (a pairing happens once a season)."""
    match = matches.get(fixture_id(fixture))
    if match is not None:
        return match
    day = dt.date.fromisoformat(fixture['date'])
    near = [m for m in by_pair.get((fixture['league_id'], fixture['home'], fixture['away']), [])
            if abs((dt.date.fromisoformat(m['date']) - day).days) <= RESCHEDULE_DAYS]
    return near[0] if len(near) == 1 else None


def grade(data, directory=REGISTRY, today=None):
    """Recompute grades; result corrections can change grades, never forecasts.

    A fixture moved to another date is graded on its new date, but only if the forecast was
    still registered at least a calendar day before the date it was actually played."""
    today = today or dt.date.today().isoformat()
    directory = Path(directory)
    matches = {fixture_id(m): m for m in data['matches']}
    by_pair = {}
    for m in data['matches']:
        by_pair.setdefault((m['league_id'], m['home'], m['away']), []).append(m)
    rows = []
    paths = [(path, 'first') for path in sorted(directory.glob('*.json'))]
    paths += [(path, 'eligible') for path in sorted((directory / 'eligible').glob('*.json'))]
    for path, cohort in paths:
        record = json.loads(path.read_text())
        fixture = record['fixture']
        match = find_match(fixture, matches, by_pair)
        played = match['date'] if match is not None else fixture['date']
        status = 'pending'
        result = None
        if match is not None and record['registered_at'][:10] >= played:
            status = 'void'          # moved earlier, to or before the day it was registered
        elif played < today:
            status = 'missing_result' if match is None or match['goals'] is None else 'graded'
        row = {'fixture': fixture, 'cohort': cohort, 'registered_at': record['registered_at'],
               'run_id': record['run_id'], 'status': status,
               'readiness': record['readiness']['status']}
        if played != fixture['date']:
            row['played_on'] = played
        if status == 'graded':
            h, a = match['goals']
            outcome = 0 if h > a else 1 if h == a else 2
            probabilities = record['probabilities']
            result = {'goals': [h, a], 'outcome': outcome,
                      'log_loss': -math.log(max(probabilities[outcome], 1e-12)),
                      'brier': sum((p - int(i == outcome)) ** 2 for i, p in enumerate(probabilities)),
                      'over25_brier': (record['over25'] - int(h + a > 2)) ** 2,
                      'btts_brier': (record['btts'] - int(h > 0 and a > 0)) ** 2}
            row['result'] = result
            row['result_hash'] = digest(match)
        rows.append(row)
    first = [row for row in rows if row['cohort'] == 'first']
    eligible = [row for row in rows if row['cohort'] == 'eligible']
    graded = [row for row in first if row['status'] == 'graded']
    eligible_graded = [row for row in eligible if row['status'] == 'graded']
    def average(key, subset):
        return sum(row['result'][key] for row in subset) / len(subset) if subset else None
    def summary(subset):
        return {'matches': len(subset), **{key: average(key, subset)
                for key in ('log_loss', 'brier', 'over25_brier', 'btts_brier')}}
    leagues = sorted({row['fixture']['league_id'] for row in first})
    return {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'data_hash': digest(data), 'registered': len(first),
            'pending': sum(row['status'] == 'pending' for row in first),
            'missing_result': sum(row['status'] == 'missing_result' for row in first),
            'void': sum(row['status'] == 'void' for row in first),
            'overall': summary(graded), 'eligible_registered': len(eligible),
            'eligible_pending': sum(row['status'] == 'pending' for row in eligible),
            'eligible_overall': summary(eligible_graded),
            'by_league': {league: summary([r for r in graded if r['fixture']['league_id'] == league])
                          for league in leagues}, 'fixtures': rows,
            'method': 'First forecast and first research-only forecast are frozen separately. Registration requires a calendar day before fixture date; a fixture moved to another date is graded on the date it was played and void if that was not after registration. Grades use current source results and may change if that source is corrected.'}


if __name__ == '__main__':
    from app import load
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['grade'])
    args = parser.parse_args()
    report = grade(load())
    atomic_write(ROOT / 'reports' / 'prospective-grades.json', json.dumps(report, indent=2))
    print(json.dumps({key: report[key] for key in ('registered', 'eligible_registered', 'pending',
                                                  'missing_result', 'overall', 'eligible_overall')}))
