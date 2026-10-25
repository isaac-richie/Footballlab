"""Our record: how the forecasts have actually done on finished games.

Two sources, kept apart:

  replay  For each finished game in the window, the production forecast is re-run as
          of the day before kickoff: only earlier results and pre-match (opening)
          bookie prices, so nothing from after kickoff leaks in. The Champions League
          is left out, because its league-strength offsets are fitted on all
          European games, including later ones.
  live    Forecasts frozen before kickoff (freeze()), graded once results arrive.

Graded per game: the 1X2 pick (most likely outcome), log loss against the base
rates, and the day's VIP pick (one per game, 70-92% likely, at most 3 per league).
Saved to reports/record.json so the hosted Lab can show it without recomputing.

    python3 app.py record
"""
import datetime as dt
import json
import math
from pathlib import Path

from quality import atomic_write

ROOT = Path(__file__).resolve().parent
FILE = ROOT / 'reports' / 'record.json'
LIVE = ROOT / 'reports' / 'record-live.json'
REPLAY_DAYS = 42
VIP_MIN, VIP_MAX, VIP_PER_LEAGUE, VIP_SIZE = .70, .92, 3, 12


def outcome(goals):
    h, a = goals
    return 0 if h > a else 1 if h == a else 2


def leg_won(leg, goals):
    """Did a parlay-style leg (market + selection) come in?"""
    h, a = goals
    o, total, home, away = outcome(goals), h + a, leg['home'], leg['away']
    sel, market = leg['selection'], leg['market']
    if market == '1x2':
        return (sel == f'{home} win' and o == 0) or (sel == 'Draw' and o == 1) or (sel == f'{away} win' and o == 2)
    if market == 'dc':
        return (sel == f'{home} or draw' and o != 2) or (sel == f'{away} or draw' and o != 0) or (sel == f'{home} or {away}' and o != 1)
    if market.startswith('ou'):
        line = float(sel.split()[-1])
        return total > line if sel.startswith('Over') else total < line
    if market == 'btts':
        both = h > 0 and a > 0
        return both if sel == 'Both teams score' else not both
    return False


def _forecasts_for_day(data, day, leagues, fixture_rates, distribution, legs_for):
    """Production forecasts as of `day` for that day's finished games, plus every candidate leg."""
    games, legs = [], []
    for league_id in leagues:
        fixtures = [m for m in data['matches'] if m['league_id'] == league_id and m['date'] == day and m['goals'] is not None]
        if not fixtures:
            continue
        try:
            _, rho, priced = fixture_rates(data, league_id, [{**m, 'goals': None} for m in fixtures], day)
        except ValueError:
            continue                                   # too little history before this date
        result = {(m['home'], m['away']): m['goals'] for m in fixtures}
        for m, _, rates, source, _ in priced:
            d = distribution(*rates, m.get('_rho', rho), m['_cal'] if source == 'model' else None)
            goals = result[(m['home'], m['away'])]
            games.append(dict(date=day, league_id=league_id, home=m['home'], away=m['away'], goals=list(goals),
                              probabilities=[round(x, 4) for x in d['probabilities']], source=source))
            for leg in legs_for({**m, 'league_id': league_id}, d, source):
                legs.append({**leg, 'goals': list(goals)})
    return games, legs


def vip_from(legs):
    """The same selection rule as the VIP picks page, applied to one day's legs."""
    best = {}
    for leg in legs:
        if VIP_MIN <= leg['probability'] <= VIP_MAX and leg['probability'] > best.get(leg['fixture'], {}).get('probability', 0):
            best[leg['fixture']] = leg
    picks, per = [], {}
    for leg in sorted(best.values(), key=lambda c: -c['probability']):
        if per.get(leg['league_id'], 0) < VIP_PER_LEAGUE:
            per[leg['league_id']] = per.get(leg['league_id'], 0) + 1
            picks.append(leg)
        if len(picks) == VIP_SIZE:
            break
    return picks


def replay(data, leagues, fixture_rates, distribution, legs_for, days=REPLAY_DAYS, cached=None):
    """Re-run and grade the last `days` days; days already in `cached` are reused."""
    cached = cached or {}
    today = dt.date.today()
    out = {}
    for k in range(days, 0, -1):
        day = (today - dt.timedelta(days=k)).isoformat()
        if day in cached:
            out[day] = cached[day]
            continue
        games, legs = _forecasts_for_day(data, day, [lg for lg in leagues if lg != 'ucl'], fixture_rates, distribution, legs_for)
        vip = [dict(league_id=l['league_id'], home=l['home'], away=l['away'], market=l['market'], selection=l['selection'],
                    probability=round(l['probability'], 4), won=leg_won(l, l['goals']), goals=l['goals']) for l in vip_from(legs)]
        out[day] = dict(games=games, vip=vip)
    return out


def _metrics(games, base):
    n = len(games)
    if not n:
        return dict(games=0)
    hits = sum(max(range(3), key=lambda i: g['probabilities'][i]) == outcome(g['goals']) for g in games)
    ll = sum(-math.log(max(g['probabilities'][outcome(g['goals'])], 1e-9)) for g in games) / n
    bl = sum(-math.log(base[outcome(g['goals'])]) for g in games) / n
    sure = [g for g in games if max(g['probabilities']) >= .6]
    sure_hits = sum(max(range(3), key=lambda i: g['probabilities'][i]) == outcome(g['goals']) for g in sure)
    return dict(games=n, pick_hit_rate=round(hits / n, 4), log_loss=round(ll, 4), baseline_log_loss=round(bl, 4),
                sharper_than_guessing=round(1 - ll / bl, 4), confident_games=len(sure),
                confident_hit_rate=round(sure_hits / len(sure), 4) if sure else None)


def summarize(days, leagues):
    games = [g for d in days.values() for g in d['games']]
    vip = [v for d in days.values() for v in d['vip']]
    counts = [0, 0, 0]
    for g in games:
        counts[outcome(g['goals'])] += 1
    base = [(c + 1) / (sum(counts) + 3) for c in counts]      # what a no-information guess would say
    weeks = {}
    for g in games:
        d = dt.date.fromisoformat(g['date'])
        weeks.setdefault((d - dt.timedelta(days=d.weekday())).isoformat(), []).append(g)
    vip_weeks = {}
    for day, d in days.items():
        w = dt.date.fromisoformat(day)
        vip_weeks.setdefault((w - dt.timedelta(days=w.weekday())).isoformat(), []).extend(d['vip'])
    trend = [dict(week=w, **_metrics(gs, base),
                  vip_picks=len(vip_weeks.get(w, [])), vip_hit_rate=round(sum(v['won'] for v in vip_weeks.get(w, [])) / len(vip_weeks[w]), 4) if vip_weeks.get(w) else None)
             for w, gs in sorted(weeks.items())]
    by_league = {lg: _metrics([g for g in games if g['league_id'] == lg], base) for lg in sorted({g['league_id'] for g in games})}
    latest = sorted(games, key=lambda g: (g['date'], g['league_id']), reverse=True)[:40]
    for g in latest:
        pick = max(range(3), key=lambda i: g['probabilities'][i])
        g['pick'], g['hit'] = pick, pick == outcome(g['goals'])
    vip_days = [dict(date=day, picks=len(d['vip']), won=sum(v['won'] for v in d['vip']), all_won=bool(d['vip']) and all(v['won'] for v in d['vip']))
                for day, d in sorted(days.items(), reverse=True) if d['vip']]
    return dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), window_days=len(days),
                first_day=min(days) if days else None, last_day=max(days) if days else None,
                overall=_metrics(games, base), base_rates=[round(b, 4) for b in base],
                vip=dict(picks=len(vip), won=sum(v['won'] for v in vip), hit_rate=round(sum(v['won'] for v in vip) / len(vip), 4) if vip else None,
                         average_confidence=round(sum(v['probability'] for v in vip) / len(vip), 4) if vip else None, days=vip_days[:14]),
                trend=trend, by_league=by_league, latest=latest,
                method='Replayed: each finished game is forecast as of the day before kickoff with the production model, '
                       'using only earlier results and pre-match (opening) bookie prices, then graded. Champions League excluded.')


def build(data, leagues, fixture_rates, distribution, legs_for):
    try:
        saved = json.loads(FILE.read_text())
    except (OSError, ValueError):
        saved = {}
    # Reuse graded days from the same dataset; recompute when the data changes.
    cached = saved.get('days', {}) if saved.get('data_stamp') == data.get('fetched_at') else {}
    cached.pop((dt.date.today() - dt.timedelta(days=1)).isoformat(), None)   # yesterday's results may still be landing
    days = replay(data, leagues, fixture_rates, distribution, legs_for, cached=cached)
    report = summarize(days, leagues)
    atomic_write(FILE, json.dumps(dict(report, data_stamp=data.get('fetched_at'), days=days)))
    return report


def load():
    try:
        saved = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return None
    saved.pop('days', None)
    return saved


def freeze_and_grade(data, leagues, slate_fn, vip_fn, model_version):
    """Live record: freeze upcoming forecasts once (never revised), grade the frozen ones that have finished."""
    try:
        live = json.loads(LIVE.read_text())
    except (OSError, ValueError):
        live = dict(games={}, vip={})
    today = dt.date.today()
    horizon = (today + dt.timedelta(days=3)).isoformat()
    for league_id in leagues:
        try:
            slate = slate_fn(data, league_id)
        except ValueError:
            continue
        for f in slate['fixtures']:
            key = '|'.join((league_id, f['date'], f['home'], f['away']))
            if f['date'] <= horizon and key not in live['games'] and f.get('status', 'scheduled') == 'scheduled':
                live['games'][key] = dict(date=f['date'], league_id=league_id, home=f['home'], away=f['away'],
                                          probabilities=[round(x, 4) for x in f['probabilities']], source=f['source'],
                                          model=model_version, frozen_at=dt.datetime.now(dt.timezone.utc).isoformat())
    slip = vip_fn(data)
    day = today.isoformat()
    if day not in live['vip'] and slip['legs']:
        live['vip'][day] = [dict(league_id=l['league_id'], date=l['date'], home=l['home'], away=l['away'], market=l['market'],
                                 selection=l['selection'], probability=round(l['probability'], 4)) for l in slip['legs']]
    results = {(m['league_id'], m['date'], m['home'], m['away']): m['goals'] for m in data['matches'] if m['goals'] is not None}
    for g in live['games'].values():
        goals = results.get((g['league_id'], g['date'], g['home'], g['away']))
        if goals and 'goals' not in g:
            g['goals'] = list(goals)
    for legs in live['vip'].values():
        for l in legs:
            goals = results.get((l['league_id'], l['date'], l['home'], l['away']))
            if goals and 'won' not in l:
                l['goals'], l['won'] = list(goals), leg_won(l, goals)
    atomic_write(LIVE, json.dumps(live))
    graded = [g for g in live['games'].values() if 'goals' in g]
    legs = [l for v in live['vip'].values() for l in v if 'won' in l]
    hits = sum(max(range(3), key=lambda i: g['probabilities'][i]) == outcome(g['goals']) for g in graded)
    return dict(frozen=len(live['games']), graded=len(graded), pending=len(live['games']) - len(graded),
                pick_hit_rate=round(hits / len(graded), 4) if graded else None,
                vip_legs_graded=len(legs), vip_hit_rate=round(sum(l['won'] for l in legs) / len(legs), 4) if legs else None,
                since=min((g['frozen_at'] for g in live['games'].values()), default=None))
