"""Walk-forward check of over/under goal picks (the production forecast, refit as of each match day).

Every finished match from August 2024 is forecast with app.fixture_rates as of its own
date: only earlier results and pre-match prices. Pick rules are chosen on 2024-25 and
reported once on 2025-26 and on 2026-27 to date.

    python3 tools/goal_lines_check.py            # rebuild records, then report
    python3 tools/goal_lines_check.py --report   # report from saved records
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import record  # noqa: E402
from parlay import legs_for  # noqa: E402
from quality import atomic_write  # noqa: E402

START = '2024-08-01'
RECORDS = ROOT / 'reports' / 'cache' / 'goal_lines_records.json'
OUT = ROOT / 'reports' / 'goal_lines_check.json'
TUNE, HOLD = ('2024-25',), ('2025-26', '2026-27')
LINES = ('Over 1.5', 'Under 1.5', 'Over 2.5', 'Under 2.5', 'Over 3.5', 'Under 3.5')


def run_league(league_id):
    data = app.load()
    season = {(m['date'], m['home'], m['away']): m['season'] for m in data['matches'] if m['league_id'] == league_id}
    days = sorted({m['date'] for m in data['matches'] if m['league_id'] == league_id and m['goals'] is not None and m['date'] >= START})
    out = []
    for day in days:
        _, legs = record._forecasts_for_day(data, day, [league_id], app.fixture_rates, app.distribution, legs_for)
        by = {}
        for l in legs:
            if l['market'] == '1x2':
                key = 'home' if l['selection'] == f"{l['home']} win" else 'away' if l['selection'] == f"{l['away']} win" else 'draw'
                by.setdefault((l['home'], l['away']), dict(league_id=league_id, date=day, home=l['home'], away=l['away'],
                                                           goals=l['goals'], source=l['source'],
                                                           season=season.get((day, l['home'], l['away']))))[key] = round(l['probability'], 4)
            if l['selection'] in LINES:
                by.setdefault((l['home'], l['away']), dict(league_id=league_id, date=day, home=l['home'], away=l['away'],
                                                           goals=l['goals'], source=l['source'],
                                                           season=season.get((day, l['home'], l['away']))))[l['selection']] = round(l['probability'], 4)
        out += by.values()
    return out


def won(r, sel):
    t, line = sum(r['goals']), float(sel.split()[-1])
    return t > line if sel.startswith('Over') else t < line


def table(rows, sel, floor, cap=.92):
    sub = [r for r in rows if floor <= r.get(sel, 0) <= cap]
    if not sub:
        return dict(picks=0)
    return dict(picks=len(sub), said=round(sum(r[sel] for r in sub) / len(sub), 4), won=round(sum(won(r, sel) for r in sub) / len(sub), 4))


RULE = (('Over 2.5', .65), ('Over 1.5', .78), ('Under 3.5', .70))     # record.VIP_PRIORITY, in order


def rule_pick(r, rule=RULE, cap=.92):
    for sel, floor in rule:
        if floor <= r.get(sel, 0) <= cap:
            return sel
    return None


def rule_report(rows, rule=RULE):
    out = {}
    for name, seasons in (('tune', TUNE), ('2025-26', HOLD[:1]), ('2026-27', HOLD[1:])):
        picks = [(r, rule_pick(r, rule)) for r in rows if r['season'] in seasons]
        picks = [(r, s) for r, s in picks if s]
        part = {}
        for label, keep in (('all', lambda s: True), ('overs', lambda s: s.startswith('Over')), ('unders', lambda s: s.startswith('Under')),
                            *((sel, lambda s, sel=sel: s == sel) for sel, _ in rule)):
            sub = [(r, s) for r, s in picks if keep(s)]
            part[label] = dict(picks=len(sub), said=round(sum(r[s] for r, s in sub) / len(sub), 4) if sub else None,
                               won=round(sum(won(r, s) for r, s in sub) / len(sub), 4) if sub else None)
        out[name] = part
    return out


def report(rows):
    out = {}
    for sel in LINES:
        out[sel] = {}
        for floor in (.6, .65, .7, .75, .8):
            out[sel][f'{int(floor * 100)}%+'] = {name: table([r for r in rows if r['season'] in seasons], sel, floor)
                                                for name, seasons in (('tune', TUNE), ('2025-26', HOLD[:1]), ('2026-27', HOLD[1:]))}
    return out


def main():
    if '--report' not in sys.argv:
        with Pool() as pool:
            rows = [r for part in pool.map(run_league, list(app.OPEN_LEAGUES)) for r in part]
        atomic_write(RECORDS, json.dumps(rows))
    rows = json.loads(RECORDS.read_text())
    rep = dict(matches=len(rows), by_season={s: sum(r['season'] == s for r in rows) for s in TUNE + HOLD}, lines=report(rows),
               rule=[dict(selection=s, floor=f) for s, f in RULE], vip_rule=rule_report(rows), generated_at=__import__('datetime').datetime.now().isoformat(timespec='seconds'))
    atomic_write(OUT, json.dumps(rep, indent=1))
    for name, part in rep['vip_rule'].items():
        print('RULE', name, {k: (v['picks'], v['said'], v['won']) for k, v in part.items()})
    for sel, floors in rep['lines'].items():
        for f, v in floors.items():
            if v['tune'].get('picks'):
                print(f'{sel:10} {f:5}', '  '.join(f"{k}: {x.get('picks', 0):5} said {x.get('said', 0):.3f} won {x.get('won', 0):.3f}" for k, x in v.items()))


if __name__ == '__main__':
    main()
