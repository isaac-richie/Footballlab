"""Forward ledger for NBA forecasts: freeze before tip-off, grade after the final.

Every upcoming game on the board is written down before it starts, twice:

    first   the earliest forecast seen, never changed afterwards
    last    the latest forecast before tip-off (overwritten until the game starts)

Each record keeps the probabilities the app showed (priced from the line when one
was posted, from the ratings otherwise) and the ratings' own view, so both can be
graded. Grades are recomputed from the stored final scores every time; a forecast
is never edited after tip-off.

The probabilities partly come from ESPN BET lines, which have no published reuse
terms, so the ledger stays private like nba_data.json (git-ignored folder).

    python3 nba_ledger.py            # freeze upcoming games, then grade
"""
import datetime as dt
import json
import math
import os
from pathlib import Path

from quality import atomic_write, digest

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / 'reports' / 'nba_prospective'
GRADES = ROOT / 'reports' / 'nba_prospective-grades.json'
BINS = [(.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]


def _tipoff(row):
    t = row.get('tipoff')
    return dt.datetime.fromisoformat(t.replace('Z', '+00:00')) if t else None


def record_for(row, now, version):
    """The frozen fields for one board row (nba_app._board row shape)."""
    m = row['model']
    return dict(schema=1, id=row['id'], date=row['date'], tipoff=row['tipoff'], home=row['home'], away=row['away'],
                kind=row.get('kind'), registered_at=now.isoformat(), version=version, source=row['source'], book=row.get('book'),
                moneyline=row['moneyline'][0], spread_line=row['spread_line'], cover=row['cover'],
                total_line=row['total_line'], over=row['over'],
                expected=row['expected_points'],
                model=dict(moneyline=m['moneyline'][0], cover=m['cover'], over=m['over'], expected=m['expected_points']))


def _write_new(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w') as handle:
        json.dump(record, handle, indent=1, allow_nan=False)
    return True


def register(rows, now=None, version=None, directory=LEDGER):
    """Freeze rows that have not started. Returns (new first records, last records updated)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    directory = Path(directory)
    new = updated = 0
    for row in rows:
        start = _tipoff(row)
        if start is None or now >= start or row.get('status') not in (None, 'scheduled'):
            continue                  # unknown tip-off or already started: never written
        rec = record_for(row, now, version)
        if _write_new(directory / 'first' / f"{row['id']}.json", rec):
            new += 1
        last = directory / 'last' / f"{row['id']}.json"
        last.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(last, json.dumps(rec, indent=1, allow_nan=False))
        updated += 1
    return new, updated


def _ll(p, y):
    p = min(1 - 1e-9, max(1e-9, p))
    return -math.log(p if y else 1 - p)


def picks(rec, score, view=None):
    """[(market, p, won)] for one graded record; pushes are left out."""
    v = rec if view is None else rec['model']
    margin, total = score[0] - score[1], score[0] + score[1]
    out = [('moneyline', v['moneyline'], margin > 0)]
    if margin + rec['spread_line'] != 0:
        out.append(('spread', v['cover'], margin + rec['spread_line'] > 0))
    if total != rec['total_line']:
        out.append(('total', v['over'], total > rec['total_line']))
    return out


def summarise(rows):
    out = {}
    for market in ('moneyline', 'spread', 'total'):
        sub = [(p, y) for m, p, y in rows if m == market]
        if not sub:
            continue
        side = [(max(p, 1 - p), y if p >= .5 else not y) for p, y in sub]
        bins = []
        for lo, hi in BINS:
            b = [(p, y) for p, y in side if lo <= p < hi]
            if b:
                bins.append(dict(bin=f'{int(lo * 100)}-{min(100, int(hi * 100))}%', picks=len(b),
                                 predicted=sum(p for p, _ in b) / len(b), won=sum(y for _, y in b) / len(b)))
        out[market] = dict(picks=len(sub), log_loss=sum(_ll(p, y) for p, y in sub) / len(sub),
                           brier=sum((p - y) ** 2 for p, y in sub) / len(sub),
                           predicted=sum(p for p, _ in side) / len(side), won=sum(y for _, y in side) / len(side),
                           calibration=bins)
    return out


def grade(games, directory=LEDGER, cohort='last'):
    """Grades from the stored finals; recomputed in full each time."""
    finals = {g['id']: g for g in games if g['status'] == 'final' and g.get('score')}
    lost = {g['id'] for g in games if g['status'] == 'postponed'}
    shown, model, by_source, rows = [], [], {}, []
    pending = void = 0
    for path in sorted((Path(directory) / cohort).glob('*.json')):
        rec = json.loads(path.read_text())
        g = finals.get(rec['id'])
        if g is None:
            if rec['id'] in lost:
                void += 1
            else:
                pending += 1
            continue
        p = picks(rec, g['score'])
        shown += p
        model += picks(rec, g['score'], 'model')
        by_source.setdefault(rec['source'], []).extend(p)
        rows.append(dict(id=rec['id'], date=rec['date'], home=rec['home'], away=rec['away'], source=rec['source'],
                         score=g['score'], moneyline=rec['moneyline'], spread_line=rec['spread_line'], cover=rec['cover'],
                         total_line=rec['total_line'], over=rec['over'], registered_at=rec['registered_at']))
    return dict(cohort=cohort, graded=len(rows), pending=pending, void=void,
                shown=summarise(shown), model_only=summarise(model),
                by_source={k: summarise(v) for k, v in by_source.items()},
                recent=sorted(rows, key=lambda r: (r['date'], r['id']))[-20:][::-1])


def report(games, directory=LEDGER):
    out = dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), data_hash=digest([
        (g['id'], g['score']) for g in games if g['status'] == 'final']),
        first=grade(games, directory, 'first'), last=grade(games, directory, 'last'),
        method='Each game is frozen before its listed tip-off: the first forecast seen and the last one before tip-off. '
               'Grades come from ESPN final scores (overtime included) and are recomputed on every run. Pushes are left out. '
               '"shown" is what the board displayed (line-priced where a line was posted); "model_only" is the ratings alone.')
    return out


def run(days=7):
    """Freeze the current board, grade everything, write the private grades file."""
    import nba
    import nba_app
    data, rest = nba_app._data()
    if not data or not data['games']:
        return dict(error='no NBA data')
    today = dt.date.today().isoformat()
    now = dt.datetime.now(dt.timezone.utc)
    version = nba_app._version()
    rows = [dict(x['row'], status=nba_app._status(x['game'], now)) for x in nba_app._board(data, rest, today, days)]
    new, updated = register(rows, now, version)
    rep = report(nba.load()['games'])
    atomic_write(GRADES, json.dumps(rep, indent=1))
    return dict(new=new, updated=updated, graded=rep['last']['graded'], pending=rep['last']['pending'])


def summary():
    """Short view for the board, or None before anything is graded."""
    try:
        rep = json.loads(GRADES.read_text())
    except (OSError, ValueError):
        return None
    last = rep['last']
    return dict(generated_at=rep['generated_at'], graded=last['graded'], pending=last['pending'],
                shown={k: {x: v[x] for x in ('picks', 'predicted', 'won', 'log_loss')} for k, v in last['shown'].items()})


if __name__ == '__main__':
    print(json.dumps(run()))
