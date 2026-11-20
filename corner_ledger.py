"""Corner picks saved before kickoff and graded on the final corner count (the corners forward record).

Each morning the daily job saves one corner pick for every game in the next three days that has a
tested one: Under 10.5 at 65%+, else Under 11.5 at 70%+ (corners.VALIDATED; the two lines that
matched their stated chance on seasons the model never saw). A saved pick is never changed. Results
come from corners_data.json once the game's statistics arrive. Corner picks are not on the VIP slip:
they earn that with a few weeks of this record.

    python3 corner_ledger.py
"""
import datetime as dt
import json
from pathlib import Path

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'reports' / 'corner_picks.json'
ORDER = ((10.5, .65), (11.5, .70))          # the stronger line first


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return dict(picks={})


def choose(forecast):
    if forecast.get('status') != 'ok':
        return None
    by_line = {l['line']: l for l in forecast['lines']}
    for line, floor in ORDER:
        l = by_line.get(line)
        if l and l['under'] >= floor:
            return dict(side='under', line=line, probability=round(l['under'], 4))
    return None


def freeze(data, slate_fn, leagues, store, today=None, now=None, days=3):
    import corners
    today = today or dt.date.today()
    now = now or dt.datetime.now(dt.timezone.utc)
    end = (today + dt.timedelta(days=days)).isoformat()
    added = 0
    for lg in leagues:
        try:
            fixtures = slate_fn(data, lg)['fixtures']
        except ValueError:
            continue
        for f in fixtures:
            if not (today.isoformat() <= f['date'] <= end) or f.get('status', 'scheduled') != 'scheduled':
                continue
            if f.get('kickoff') and dt.datetime.fromisoformat(f['kickoff'].replace('Z', '+00:00')) <= now:
                continue
            key = '|'.join((lg, f['date'], f['home'], f['away']))
            if key in store['picks']:
                continue
            fc = corners.forecast(data['matches'], lg, f['home'], f['away'], today.isoformat())
            pick = choose(fc)
            if pick:
                store['picks'][key] = dict(league_id=lg, date=f['date'], home=f['home'], away=f['away'], kickoff=f.get('kickoff'),
                                           expected_total=round(fc['expected_total'], 2), saved_at=now.isoformat(), **pick)
                added += 1
    return added


def grade(data, store, today=None):
    """Fill in final corner totals from corners_data.json (matched by date within a day and team names)."""
    import corners
    rows = corners.load()
    ours = corners.name_map(rows, data['matches'])             # (league, API name) -> our name
    by = {}
    for r in rows:
        h, a = ours.get((r['league_id'], r['home'])), ours.get((r['league_id'], r['away']))
        if h and a:
            by[(r['league_id'], r['date'], h, a)] = sum(r['corners'])
    today = (today or dt.date.today()).isoformat()
    graded = 0
    for p in store['picks'].values():
        if 'corners' in p:
            continue
        d = dt.date.fromisoformat(p['date'])
        for shift in (0, 1, -1):
            total = by.get((p['league_id'], (d + dt.timedelta(days=shift)).isoformat(), p['home'], p['away']))
            if total is not None:
                p['corners'] = total
                p['won'] = total < p['line'] if p['side'] == 'under' else total > p['line']
                graded += 1
                break
        else:
            if p['date'] < (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat():
                p['void'] = True                                 # no statistics a week later: postponed or missing
    return graded


def summary(store=None, latest_days=1):
    store = store or load()
    picks = list(store['picks'].values())
    settled = [p for p in picks if 'won' in p]
    won = sum(p['won'] for p in settled)
    by_line = {}
    for p in settled:
        b = by_line.setdefault(str(p['line']), dict(picks=0, won=0, said=0.0))
        b['picks'] += 1; b['won'] += p['won']; b['said'] += p['probability']
    for b in by_line.values():
        b['said'] = round(b['said'] / b['picks'], 4); b['hit_rate'] = round(b['won'] / b['picks'], 4)
    days = sorted({p['date'] for p in settled}, reverse=True)[:latest_days]
    return dict(picks=len(picks), settled=len(settled), won=won, lost=len(settled) - won,
                pending=sum(1 for p in picks if 'won' not in p and not p.get('void')),
                hit_rate=round(won / len(settled), 4) if settled else None,
                said=round(sum(p['probability'] for p in settled) / len(settled), 4) if settled else None,
                by_line=by_line, since=min((p['saved_at'][:10] for p in picks), default=None),
                latest=[p for p in sorted(settled, key=lambda p: (p['date'], p['league_id'])) if p['date'] in days])


def run():
    import app
    data = app.load()
    store = load()
    added = freeze(data, app.slate, list(app.LEAGUES), store)
    graded = grade(data, store)
    store['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_write(FILE, json.dumps(store, indent=0))
    return dict(added=added, graded=graded, **{k: v for k, v in summary(store).items() if k in ('picks', 'settled', 'won', 'lost')})


if __name__ == '__main__':
    import config
    config.load_environment()
    print(json.dumps(dict(corner_picks=run())))
