"""Model health: do the saved picks win about as often as they said?

Run by the daily job after the picks are graded. For each sport and pick type it compares
the average stated chance ("said") with the share that won ("won") on the saved,
before-kickoff record, overall and over the last 28 days, and gives a plain status:

    collecting  too few settled picks to judge (fewer than MIN_PICKS)
    ok          within 3 points of what we said
    watch       3 to 5 points below what we said
    alert       5+ points below, or clearly below given the sample (z <= -2.5): over-confident
    cautious    5+ points above what we said (safe, but the percentages undersell the picks)

Football counts each game once (record.vip_ledger). NBA days rebuilt from frozen forecasts
(15-18 November 2026) are reported separately from picks saved as shown.

    python3 model_health.py
"""
import datetime as dt
import json
import math
from pathlib import Path

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'reports' / 'model_health.json'
MIN_PICKS, MIN_RECENT, RECENT_DAYS = 100, 50, 28


def judge(picks, minimum=MIN_PICKS):
    """picks: [(probability, won)] -> summary with a status."""
    n = len(picks)
    if not n:
        return dict(picks=0, status='collecting')
    said = sum(p for p, _ in picks) / n
    won = sum(bool(w) for _, w in picks) / n
    gap = won - said
    z = gap / math.sqrt(max(said * (1 - said), 1e-9) / n)
    if n < minimum:
        status = 'collecting'
    elif gap <= -.05 or z <= -2.5:
        status = 'alert'
    elif gap <= -.03:
        status = 'watch'
    elif gap >= .05:
        status = 'cautious'
    else:
        status = 'ok'
    return dict(picks=n, said=round(said, 4), won=round(won, 4), gap=round(gap, 4), z=round(z, 2), status=status)


def _groups(rows, today):
    """rows: [(group, date, probability, won)] -> {group: {all, recent}}."""
    cut = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    out = {}
    for g in sorted({r[0] for r in rows}):
        sub = [r for r in rows if r[0] == g]
        out[g] = dict(all=judge([(p, w) for _, _, p, w in sub]),
                      recent=judge([(p, w) for _, d, p, w in sub if d >= cut], MIN_RECENT))
    return out


def football_rows(ledger):
    rows = []
    for day in ledger['days']:
        for p in day['picks']:
            if not p.get('counted', True) or p['status'] not in ('won', 'lost'):
                continue
            won = p['status'] == 'won'
            side = p.get('side') or ('wins' if p['market'] == '1x2' else 'overs' if p['selection'].startswith('Over') else 'unders')
            for g in ('all goal and win picks', {'overs': 'overs', 'unders': 'unders (3.5)', 'wins': 'favourites to win'}.get(side, side)):
                rows.append((g, p['date'], p['probability'], won))
    return rows


def nba_rows(results):
    rows = []
    for day in results['days']:
        for x in day['picks']:
            for k in ('total', 'winner'):
                pk = x.get(k)
                if not pk or 'won' not in pk:
                    continue
                tag = ' (rebuilt days)' if x.get('rebuilt') else ''
                names = ['over/under' + tag, ('overs' if pk['side'] == 'over' else 'unders') + tag] if k == 'total' else ['winners' + tag]
                for g in names:
                    rows.append((g, x['date'], pk['probability'], pk['won']))
    return rows


def run(today=None, write=True):
    import nba_picks_ledger
    import nba_public
    import record
    today = today or dt.date.today()
    report = dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), min_picks=MIN_PICKS, recent_days=RECENT_DAYS,
                  football=_groups(football_rows(record.vip_ledger(max_days=100000)), today),
                  nba=_groups(nba_rows(nba_picks_ledger.results(nba_public.load()['games'])), today),
                  method=__doc__.split('\n\n')[1].strip())
    flags = [f'{sport} {g}: {v["all"]["status"]} (said {v["all"]["said"]:.1%}, won {v["all"]["won"]:.1%}, {v["all"]["picks"]} picks)'
             for sport in ('football', 'nba') for g, v in report[sport].items() if v['all']['status'] in ('alert', 'watch')]
    report['flags'] = flags
    if write:
        atomic_write(FILE, json.dumps(report, indent=1))
    return report


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return None


if __name__ == '__main__':
    r = run()
    for sport in ('football', 'nba'):
        for g, v in r[sport].items():
            a = v['all']
            print(f"{sport:8} {g:28} {a['status']:10} picks {a['picks']:4}" + (f"  said {a['said']:.1%} won {a['won']:.1%}" if a['picks'] else ''))
    print('FLAGS:' if r['flags'] else 'No flags.', *r['flags'], sep='\n  ')
