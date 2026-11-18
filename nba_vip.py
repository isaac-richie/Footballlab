"""NBA VIP picks: the day's strongest total-points calls, saved before tip-off and graded on the final score.

Each morning the SIZE strongest total-points picks (nba_app.picks, which only offers totals
whose 70%+ picks were on target in testing) for games that have not started are written down
once for that day and never edited; only their results are filled in. They sit on the VIP
ticket next to the football picks.

The hosted site's picks come from the scores-only model and are committed (PUBLIC_FILE).
The local Lab may price from bookmaker lines, so its picks stay private in the git-ignored
ledger folder, like the forward ledger.

    python3 nba_vip.py            # save today's picks (local), then grade
"""
import datetime as dt
import json
from pathlib import Path

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
PUBLIC_FILE = ROOT / 'reports' / 'nba_vip_public.json'
LOCAL_FILE = ROOT / 'reports' / 'nba_prospective' / 'vip.json'
SIZE = 3
FIELDS = ('id', 'date', 'tipoff', 'home', 'away', 'home_abbr', 'away_abbr', 'side', 'line', 'probability', 'expected_total', 'source')


def _file(public):
    return PUBLIC_FILE if public else LOCAL_FILE


def load(public=False):
    try:
        return json.loads(_file(public).read_text())
    except (OSError, ValueError):
        return dict(days={})


def choose(totals, now, size=SIZE):
    """The strongest total picks for games that have not tipped off, one per game."""
    seen, out = set(), []
    for p in sorted(totals, key=lambda p: -p['probability']):
        tip = p.get('tipoff')
        if p['id'] in seen or (tip and dt.datetime.fromisoformat(tip.replace('Z', '+00:00')) <= now):
            continue
        seen.add(p['id'])
        out.append({k: p.get(k) for k in FIELDS})
        if len(out) == size:
            break
    return out


def freeze(store, totals, today, now):
    """Write today's picks once; later runs the same day change nothing."""
    day = today.isoformat()
    if day in store['days']:
        return False
    picks = choose(totals, now)
    if not picks:
        return False
    store['days'][day] = dict(frozen_at=now.isoformat(), picks=picks)
    return True


def won(pick, score):
    total = sum(score)
    return total > pick['line'] if pick['side'] == 'over' else total < pick['line']


def grade(store, games):
    """Fill in final scores; a postponed game's pick is void."""
    by_id = {g['id']: g for g in games}
    changed = 0
    for day in store['days'].values():
        for p in day['picks']:
            if 'won' in p or p.get('void'):
                continue
            g = by_id.get(p['id'])
            if g and g['status'] == 'final' and g.get('score'):
                p['score'], p['won'] = list(g['score']), won(p, g['score'])
                changed += 1
            elif g and g['status'] == 'postponed':
                p['void'] = True
                changed += 1
    return changed


def in_play(selection, score, market='total'):
    """Whether a live score already settles a pick: True (won), False (lost) or None (still open).

    Overs are won the moment the total passes the line, unders lost; both-teams-to-score is
    won once both have scored. Totals can only go up, so these can never be undone."""
    h, a = score
    if market == 'btts':
        both = h > 0 and a > 0
        return (True if selection == 'Both teams score' else False) if both else None
    words = selection.split()
    if market != 'total' and not market.startswith('ou') or len(words) < 2:
        return None
    side, line = words[0].lower(), float(words[1])
    if h + a > line:
        return side == 'over'
    return None


def settle_in_play(row, score):
    """Mark a live ticket row won or lost early when its score already decides it, otherwise
    say how much the pick still needs (overs only)."""
    early = in_play(row['selection'], score, row['market'])
    if early is not None:
        row.update(status='won' if early else 'lost', provisional=True, in_play=True)
    elif row['selection'].lower().startswith('over'):
        line = float(row['selection'].split()[1])
        row['needs'] = int(line) + 1 - sum(score)


def status_of(p):
    return 'won' if p.get('won') is True else 'lost' if p.get('won') is False else 'void' if p.get('void') else 'pending'


def run(public=False, now=None):
    """Save today's picks (if not saved yet) and grade everything saved so far."""
    import nba
    import nba_app
    import nba_public
    now = now or dt.datetime.now(dt.timezone.utc)
    store = load(public)
    new = False
    if now.date().isoformat() not in store['days']:          # pricing the picks takes seconds: once a day
        new = freeze(store, nba_app.picks().get('totals') or [], now.date(), now)
    graded = grade(store, (nba_public.load() if public else nba.load())['games'])
    if new or graded:
        _file(public).parent.mkdir(parents=True, exist_ok=True)
        atomic_write(_file(public), json.dumps(store, indent=1))
    return dict(saved_today=new, graded=graded, days=len(store['days']))


def ticket_legs(public, today, live=None, totals=None, now=None):
    """Today's NBA VIP picks for the ticket: saved ones with their state, or (before the morning
    run) the current strongest picks marked unsaved."""
    store = load(public)
    day = store['days'].get(today)
    if day:
        picks, saved = [dict(p, status=status_of(p)) for p in day['picks']], True
    else:
        now = now or dt.datetime.now(dt.timezone.utc)
        picks, saved = [dict(p, status='pending') for p in choose(totals or [], now)], False
    live = live or {}
    rows = []
    for p in picks:
        row = dict(sport='nba', league='NBA', league_id='nba', id=p['id'], date=p['date'], kickoff=p.get('tipoff'),
                   home=p['home'], away=p['away'], home_abbr=p.get('home_abbr'), away_abbr=p.get('away_abbr'),
                   market='total', side=p['side'], line=p['line'], selection=f"{p['side'].title()} {p['line']} points",
                   probability=p['probability'], fair_odds=1 / p['probability'], expected_total=p.get('expected_total'),
                   source=p.get('source'), status=p['status'], score=p.get('score'),
                   clock='Final' if p['status'] in ('won', 'lost') else None, provisional=False)
        if p['status'] == 'pending':
            lv = live.get(p['id']) or live.get(f"{p['date']}|{p.get('home_abbr')}")
            if lv and lv['status'] == 'live':
                row.update(status='live', score=lv['score'], clock=lv['clock'])
                settle_in_play(row, lv['score'])
            elif lv and lv['status'] == 'final':
                row.update(status='won' if won(p, lv['score']) else 'lost', score=lv['score'], clock='Final', provisional=True)
            elif lv and lv['status'] == 'postponed':
                row.update(status='void')
            else:
                row['status'] = 'scheduled'
        rows.append(row)
    return rows, saved


if __name__ == '__main__':
    import config
    config.load_environment()
    print(json.dumps(run()))
