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
# From 21 November 2026 the slip also carries up to WINS winners at WIN_FLOOR or better, from games
# without a total pick (80%+ winner picks won 84.9% on the held-out 2025-26 season).
WINS, WIN_FLOOR = 2, .80
FIELDS = ('id', 'date', 'tipoff', 'home', 'away', 'home_abbr', 'away_abbr', 'side', 'line', 'probability', 'expected_total', 'source',
          'market', 'team')


def _file(public):
    return PUBLIC_FILE if public else LOCAL_FILE


def load(public=False):
    try:
        return json.loads(_file(public).read_text())
    except (OSError, ValueError):
        return dict(days={})


def _open(p, now):
    tip = p.get('tipoff')
    return not (tip and dt.datetime.fromisoformat(tip.replace('Z', '+00:00')) <= now)


def choose(totals, now, size=SIZE, winners=(), wins=WINS):
    """The strongest total picks for games that have not tipped off, one per game, then up to
    `wins` winner picks at WIN_FLOOR+ from other games."""
    seen, out = set(), []
    for p in sorted(totals, key=lambda p: -p['probability']):
        if p['id'] in seen or not _open(p, now):
            continue
        seen.add(p['id'])
        out.append(dict({k: p.get(k) for k in FIELDS}, market='total'))
        if len(out) == size:
            break
    taken = 0
    for p in sorted(winners, key=lambda p: -p['probability']):
        if taken == wins or p['id'] in seen or p['probability'] < WIN_FLOOR or not _open(p, now):
            continue
        seen.add(p['id'])
        out.append(dict({k: p.get(k) for k in FIELDS}, market='winner', team=p['team'], side=None, line=None))
        taken += 1
    return out


def label(p):
    return f"{p['team']} to win" if p.get('market') == 'winner' else f"{p['side'].title()} {p['line']} points"


def freeze(store, totals, today, now, winners=()):
    """Write today's picks once; later runs the same day change nothing."""
    day = today.isoformat()
    if day in store['days']:
        return False
    picks = choose(totals, now, winners=winners)
    if not picks:
        return False
    store['days'][day] = dict(frozen_at=now.isoformat(), picks=picks)
    return True


def won(pick, score):
    if pick.get('market') == 'winner':
        return (score[0] > score[1]) == (pick['team'] == pick['home'])
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
        p = nba_app.picks()
        new = freeze(store, p.get('totals') or [], now.date(), now, winners=p.get('picks') or [])
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
                   market=p.get('market') or 'total', team=p.get('team'), side=p.get('side'), line=p.get('line'), selection=label(p),
                   probability=p['probability'], fair_odds=1 / p['probability'], expected_total=p.get('expected_total'),
                   source=p.get('source'), status=p['status'], score=p.get('score'),
                   clock='Final' if p['status'] in ('won', 'lost') else None, provisional=False)
        if p['status'] == 'pending':
            lv = live.get(p['id']) or live.get(f"{p['date']}|{p.get('home_abbr')}")
            if lv and lv['status'] == 'live':
                row.update(status='live', score=lv['score'], clock=lv['clock'])
                if row['market'] == 'total':
                    settle_in_play(row, lv['score'])
            elif lv and lv['status'] == 'final':
                row.update(status='won' if won(p, lv['score']) else 'lost', score=lv['score'], clock='Final', provisional=True)
            elif lv and lv['status'] == 'postponed':
                row.update(status='void')
            else:
                row['status'] = 'scheduled'
        rows.append(row)
    return rows, saved


def ledger(public, max_days=60):
    """Every saved NBA VIP slip with each pick's result, plus running totals. A game on more than one
    slip counts once in the totals, under the first pick published for it (as for football)."""
    store = load(public)
    days, seen = [], set()
    for day in sorted(store['days']):
        picks = []
        for p in store['days'][day]['picks']:
            q = dict(p, status=status_of(p), selection=label(p), market=p.get('market') or 'total', counted=p['id'] not in seen)
            seen.add(p['id'])
            picks.append(q)
        won_ = sum(q['status'] == 'won' for q in picks); lost = sum(q['status'] == 'lost' for q in picks)
        pending = sum(q['status'] == 'pending' for q in picks)
        days.append(dict(date=day, frozen_at=store['days'][day].get('frozen_at'), picks=picks, won=won_, lost=lost, pending=pending,
                         void=len(picks) - won_ - lost - pending, settled=pending == 0, all_won=pending == 0 and lost == 0 and won_ > 0))
    days.reverse()
    counted = [q for d in days for q in d['picks'] if q['counted']]
    settled = [q for q in counted if q['status'] in ('won', 'lost')]
    won_ = sum(q['status'] == 'won' for q in settled)

    def part(keep):
        sub = [q for q in settled if keep(q)]
        w = sum(q['status'] == 'won' for q in sub)
        return dict(picks=len(sub), won=w, lost=len(sub) - w)
    streak = 0
    for q in sorted(settled, key=lambda q: (q['date'], q.get('tipoff') or ''), reverse=True):
        if q['status'] != 'won':
            break
        streak += 1
    summary = dict(slips=len(days), picks=len(counted), settled=len(settled), won=won_, lost=len(settled) - won_,
                   pending=sum(q['status'] == 'pending' for q in counted),
                   hit_rate=round(won_ / len(settled), 4) if settled else None,
                   average_confidence=round(sum(q['probability'] for q in settled) / len(settled), 4) if settled else None,
                   win_streak=streak, since=days[-1]['date'] if days else None,
                   perfect_slips=sum(d['all_won'] for d in days), settled_slips=sum(d['settled'] and d['won'] + d['lost'] > 0 for d in days),
                   by_type=dict(overs=part(lambda q: q['market'] == 'total' and q.get('side') == 'over'),
                                unders=part(lambda q: q['market'] == 'total' and q.get('side') == 'under'),
                                winners=part(lambda q: q['market'] == 'winner')))
    return dict(summary=summary, days=days[:max_days])


if __name__ == '__main__':
    import config
    config.load_environment()
    print(json.dumps(run()))
