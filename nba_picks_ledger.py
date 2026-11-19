"""The hosted site's daily NBA picks, saved before tip-off and marked won or lost.

The daily job writes every pick on the Picks page (winners and total points) to
reports/nba_public_picks/<game id>.json while the game has not started; a file is
never written after tip-off. Results are worked out from the stored final scores
on every request, so a pick's outcome cannot be edited.

Days before this file existed (15-18 November 2026) are rebuilt from the forward
ledger's frozen forecasts with the same rules (winners 60%+, totals about 70%), marked "rebuilt".
"""
import datetime as dt
import json
from pathlib import Path

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'reports' / 'nba_public_picks'
LEDGER = ROOT / 'reports' / 'nba_public_prospective' / 'last'
FLOOR = .6


def _started(tipoff, now):
    return tipoff is not None and now >= dt.datetime.fromisoformat(tipoff.replace('Z', '+00:00'))


def save(p, now=None, directory=DIR):
    """Write the picks of nba_app.picks() for games that have not started. Returns how many games were written."""
    now = now or dt.datetime.now(dt.timezone.utc)
    games = {}
    for x in p.get('picks') or []:
        games.setdefault(x['id'], dict(x, winner=None, total=None))['winner'] = dict(team=x['team'], probability=x['probability'])
    for x in p.get('totals') or []:
        games.setdefault(x['id'], dict(x, winner=None, total=None))['total'] = dict(side=x['side'], line=x['line'], probability=x['probability'])
    dates = set(p.get('dates') or [])
    for path in Path(directory).glob('*.json'):
        r = json.loads(path.read_text())
        if r['date'] in dates and r['id'] not in games and not r.get('rebuilt') and not _started(r.get('tipoff'), now):
            path.unlink()                     # no longer a pick, and the game has not started
    n = 0
    for gid, x in games.items():
        if not x.get('tipoff') or _started(x['tipoff'], now):
            continue
        rec = dict(schema=1, id=gid, date=x['date'], tipoff=x['tipoff'], home=x['home'], away=x['away'],
                   home_abbr=x['home_abbr'], away_abbr=x['away_abbr'], saved_at=now.isoformat(),
                   winner=x['winner'], total=x['total'])
        Path(directory).mkdir(parents=True, exist_ok=True)
        atomic_write(Path(directory) / f'{gid}.json', json.dumps(rec, indent=1))
        n += 1
    return n


def _rebuilt_total(r):
    """The total-points pick the Picks page rule gives for a frozen forecast (scores-only model, its expected points)."""
    import nba_app
    import nba_model as M
    mk = M.markets(M.distribution(*r['model']['expected'], width=M.PUBLIC_WIDTH))
    return nba_app.total_pick(dict(total_line=mk['main_total'],
                                   alt_totals={k: v[0] for k, v in mk['totals'].items() if abs(float(k) - mk['main_total']) <= 12.5}))


def rebuild(abbrs, directory=DIR, ledger=LEDGER, before='2026-11-19'):
    """Picks for the days before picks were saved, from the forward ledger's last forecasts (frozen before tip-off):
    winner picks (60%+ side, the rule shown then) and total-points picks (the about-70% rule)."""
    n = 0
    for path in sorted(Path(ledger).glob('*.json')):
        r = json.loads(path.read_text())
        out = Path(directory) / path.name
        if r['date'] >= before:
            continue
        try:
            rec = json.loads(out.read_text())
        except (OSError, ValueError):
            rec = None
        if rec and not rec.get('rebuilt'):
            continue
        ml = r['moneyline']
        side = 0 if ml >= .5 else 1
        p = ml if side == 0 else 1 - ml
        total = _rebuilt_total(r)
        rec = dict(schema=1, id=r['id'], date=r['date'], tipoff=r['tipoff'], home=r['home'], away=r['away'],
                   home_abbr=abbrs.get(r['home']), away_abbr=abbrs.get(r['away']), saved_at=r['registered_at'],
                   winner=dict(team=(r['home'], r['away'])[side], probability=p) if p >= FLOOR else None,
                   total=dict(side=total['side'], line=total['line'], probability=total['probability']) if total else None,
                   rebuilt=True)
        if not rec['winner'] and not rec['total']:
            continue
        Path(directory).mkdir(parents=True, exist_ok=True)
        atomic_write(out, json.dumps(rec, indent=1))
        n += 1
    return n


def results(games, directory=DIR, days=None):
    """Saved picks with their outcomes, grouped by day (latest first), plus running totals."""
    finals = {g['id']: g for g in games if g['status'] == 'final' and g.get('score')}
    void = {g['id'] for g in games if g['status'] == 'postponed'}
    by_day, tally = {}, dict(winner=[0, 0], total=[0, 0], over=[0, 0], under=[0, 0])
    for path in Path(directory).glob('*.json'):
        r = json.loads(path.read_text())
        g = finals.get(r['id'])
        score = g['score'] if g else None
        row = dict(r, score=score, status='void' if r['id'] in void else 'final' if g else 'pending')
        if score:
            h, a = score
            if r.get('winner'):
                won = (h > a) == (r['winner']['team'] == r['home'])
                row['winner'] = dict(r['winner'], won=won)
                tally['winner'][0 if won else 1] += 1
            if r.get('total'):
                t, line = h + a, r['total']['line']
                won = t > line if r['total']['side'] == 'over' else t < line
                row['total'] = dict(r['total'], won=won, points=t)
                tally['total'][0 if won else 1] += 1
                tally[r['total']['side']][0 if won else 1] += 1
        by_day.setdefault(r['date'], []).append(row)
    out = []
    for date in sorted(by_day, reverse=True)[:days]:
        rows = sorted(by_day[date], key=lambda x: (x['tipoff'] or '', x['id']))
        won = sum(bool(x.get(k) and x[k].get('won')) for x in rows for k in ('winner', 'total'))
        lost = sum(bool(x.get(k) and x[k].get('won') is False) for x in rows for k in ('winner', 'total'))
        out.append(dict(date=date, won=won, lost=lost, pending=sum(x['status'] == 'pending' for x in rows), picks=rows))
    return dict(days=out, winner=dict(won=tally['winner'][0], lost=tally['winner'][1]),
                total=dict(won=tally['total'][0], lost=tally['total'][1]),
                over=dict(won=tally['over'][0], lost=tally['over'][1]), under=dict(won=tally['under'][0], lost=tally['under'][1]))
