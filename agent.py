"""Deterministic research runner with explicit quality gates and reproducible records."""
import argparse
import datetime as dt
import json
import fcntl
from pathlib import Path

from app import LEAGUES, MODEL, STATS, load, predict, refresh
from quality import atomic_write, coverage, digest
from stats import load as load_stats
from prospective import grade as grade_prospective, register as register_prospective

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'reports'


def run(days, output=REPORTS):
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('Days must be between 1 and 30')
    data = load()
    stats = load_stats(STATS)
    today = dt.date.today()
    cutoff = (today + dt.timedelta(days=days)).isoformat()
    checks = [coverage(data, league, today.isoformat()) for league in LEAGUES]
    # Date-only data cannot identify which fixtures have already started today.
    fixtures = [m for m in data['matches'] if m['goals'] is None and today.isoformat() < m['date'] <= cutoff]
    analyses = []
    for match in fixtures:
        fixture = {k: match[k] for k in ('date', 'league_id', 'league', 'home', 'away')}
        try:
            analysis = predict(data, {**fixture, 'date': today.isoformat()}, stats)
            analyses.append({'fixture': fixture, 'status': analysis['readiness']['status'],
                             'analysis': analysis})
        except ValueError as exc:
            analyses.append({'fixture': fixture, 'status': 'skipped', 'reason': str(exc)})
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    data_hash = digest(data)
    code_files = ['app.py','model.py','markets.py','simulate.py','lineups.py','implied.py','odds_data.py','live_odds.py','count_markets.py','stats.py','decision.py','jev_reviewer.py','quality.py','evaluation.py','agent.py','prospective.py']
    code_hash = digest({name:(ROOT/name).read_text() for name in code_files})
    report = {'run_id':run_id, 'generated_at':generated, 'run_date':today.isoformat(), 'window_days':days,
              'data_hash':data_hash, 'code_hash':code_hash, 'model':MODEL, 'league_coverage':checks,
              'state':'review_required' if any(c['issues'] for c in checks) else 'research_only',
              'fixtures':analyses, 'data_fetched_at':data['fetched_at'], 'stats_hash':digest(stats),
              'limitations':['Deterministic batch workflow; optional JEV is advisory; no scheduler is active.',
                             'Same-day fixtures excluded because kickoff timestamps are unavailable.',
                             'Shots/cards are withheld unless validated supplemental history meets its eligibility gate; no lineups or current odds.',
                             'Empty fixture lists may indicate missing source coverage, not no matches.']}
    output = Path(output)
    atomic_write(output/'datasets'/f'{data_hash}.json', json.dumps(data, indent=2))
    atomic_write(output/'code'/f'{code_hash}.json', json.dumps({name:(ROOT/name).read_text() for name in code_files}, indent=2))
    atomic_write(output/'runs'/f'{run_id}.json', json.dumps(report, indent=2))
    report['new_registrations'] = register_prospective(report, output/'prospective')
    prospective_grades = grade_prospective(data, output/'prospective')
    atomic_write(output/'prospective-grades.json', json.dumps(prospective_grades, indent=2))
    atomic_write(output/'latest.json', json.dumps(report, indent=2))
    lines = [f'# Football Lab research run — {today}', '',
             f'{len(analyses)} fixtures in the next {days} days (excluding today).',
             'Status: '+report['state'], '', '## Coverage', '']
    for c in checks:
        lines.append(f"- {LEAGUES[c['league_id']]}: {c['status']} — "+('; '.join(c['issues']) or 'Initial freshness checks passed; research only'))
    lines += ['', '## Forecasts', '']
    for item in analyses:
        f = item['fixture']
        label = f"{f['date']} · {f['league']} · {f['home']} v {f['away']}"
        if 'analysis' not in item:
            lines.append(f"- {label}: skipped — {item['reason']}")
            continue
        a = item['analysis']
        probs = '/'.join(f'{p:.1%}' for p in a['probabilities'])
        lines.append(f"- {label}: {item['status']}; 1X2 {probs}; expected goals "
                     f"{a['expected_goals'][0]:.2f}–{a['expected_goals'][1]:.2f}; "
                     f"O2.5 {a['over25']:.1%}; BTTS {a['btts']:.1%}; decision {a['decision']['action']}.")
    lines += ['', f"Prospective ledger: {prospective_grades['registered']} registered, {prospective_grades['overall']['matches']} graded, {prospective_grades['pending']} pending.",
              'These are uncalibrated research forecasts, not recommendations.', '',
              f'Run: {run_id} · data: {data_hash} · code: {code_hash}']
    atomic_write(output/'latest.md', '\n'.join(lines)+'\n')
    return report


if __name__ == '__main__':
    from config import load_environment
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--days', type=int, default=7, choices=range(1,31))
    args = parser.parse_args()
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another runner is active')
        try:
            if args.refresh:
                refresh()
            report = run(args.days)
            print(json.dumps(dict(run_id=report['run_id'], state=report['state'], fixtures=len(report['fixtures']))))
        except Exception as exc:
            atomic_write(REPORTS/'last_failure.json', json.dumps(dict(at=dt.datetime.now(dt.timezone.utc).isoformat(), error=str(exc))))
            raise
