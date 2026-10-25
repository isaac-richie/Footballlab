"""Featured games: the most anticipated fixtures, each with a short plain-language take.

Anticipation = how good both clubs are (recent points per game) x how close the
match looks. Write-ups are templated from the numbers only, so they never claim
anything the forecast does not support.
"""
import datetime as dt
import math


# Points per game are earned against different opposition in each division.
LEAGUE_WEIGHT = {'it.2': 0.8, 'de.2': 0.8, 'tr.1': 0.85, 'sco.1': 0.85, 'nl.1': 0.9, 'pt.1': 0.9, 'be.1': 0.85, 'ucl': 1.15}


def form_ppg(rows, team, n=19):
    games = sorted((m for m in rows if team in (m['home'], m['away'])), key=lambda m: m['date'])[-n:]
    if not games:
        return 1.0
    pts = 0
    for m in games:
        own = 0 if m['home'] == team else 1
        gf, ga = m['goals'][own], m['goals'][1 - own]
        pts += 3 if gf > ga else 1 if gf == ga else 0
    return pts / len(games)


def anticipation(home_ppg, away_ppg, probabilities):
    quality = (home_ppg + away_ppg) / 6                # 0..1, both sides winning everything = 1
    entropy = -sum(p * math.log(p) for p in probabilities if p) / math.log(3)   # 1 = completely open
    return round(100 * (0.6 * quality + 0.4 * entropy) * (0.75 + 0.25 * min(home_ppg, away_ppg) / 3), 1)


def pct(p):
    return f'{round(p * 100)}%'


def write_up(f, home_ppg, away_ppg):
    """A few short sentences in plain football language."""
    h, a, p = f['home'], f['away'], f['probabilities']
    lines = []
    fav = max(range(3), key=lambda i: p[i])
    gap = sorted(p)[-1] - sorted(p)[-2]
    if fav == 1 or gap < 0.06:
        lines.append(f'Too close to call: {h} {pct(p[0])}, draw {pct(p[1])}, {a} {pct(p[2])}.')
    else:
        name = h if fav == 0 else a
        strength = 'clear favourites' if p[fav] >= 0.6 else 'slight favourites' if p[fav] < 0.45 else 'favourites'
        lines.append(f'{name} are {strength} at {pct(p[fav])}{" away from home" if fav == 2 else ""}.')
    if f['over25'] >= 0.6:
        lines.append(f'Goals expected: over 2.5 at {pct(f["over25"])}' + (f', both teams to score {pct(f["btts"])}.' if f['btts'] >= 0.55 else '.'))
    elif f['over25'] <= 0.42:
        lines.append(f'Could be tight: under 2.5 goals at {pct(1 - f["over25"])}.')
    else:
        lines.append(f'Goals: over 2.5 at {pct(f["over25"])}, both teams to score {pct(f["btts"])}.')
    lines.append(f'Most likely score {f["top_score"]["score"]} ({pct(f["top_score"]["probability"])}).')
    if abs(home_ppg - away_ppg) >= 0.8:
        better = h if home_ppg > away_ppg else a
        lines.append(f'Form check: {better} have taken {max(home_ppg, away_ppg):.1f} points a game recently, '
                     f'against {min(home_ppg, away_ppg):.1f}.')
    mp = f.get('model_probabilities')
    if mp and f['source'] != 'model':
        diff = max(range(3), key=lambda i: abs(mp[i] - p[i]))
        if abs(mp[diff] - p[diff]) >= 0.07:
            who = [h, 'the draw', a][diff]
            lines.append(f'Our model rates {who} {"higher" if mp[diff] > p[diff] else "lower"} than the bookies '
                         f'({pct(mp[diff])} vs {pct(p[diff])}), but bookies have the better track record.')
    if f.get('thin_history'):
        lines.append('One side has little recent history at this level, so treat the numbers with care.')
    return lines


def featured(data, leagues, slate_fn, history_fn, period='week', limit=10):
    today = dt.date.today()
    candidates = []
    for league_id, name in leagues.items():
        try:
            s = slate_fn(data, league_id)
        except ValueError:
            continue
        rows = history_fn(data, today.isoformat(), league_id)
        for f in s['fixtures']:
            candidates.append((league_id, name, f, rows))
    if not candidates:
        return dict(period=period, games=[], note='No upcoming fixtures in the data.')
    if period == 'day':
        first = min(f['date'] for _, _, f, _ in candidates)   # the next matchday with games
        candidates = [c for c in candidates if c[2]['date'] == first]
        label = dt.date.fromisoformat(first).strftime('%A %-d %B')
    else:
        until = (today + dt.timedelta(days=7)).isoformat()
        candidates = [c for c in candidates if c[2]['date'] <= until]
        label = 'Next 7 days'
    games = []
    for league_id, name, f, rows in candidates:
        hp, ap = form_ppg(rows, f['home']), form_ppg(rows, f['away'])
        games.append(dict(league_id=league_id, league=name.split(' — ')[-1], date=f['date'], home=f['home'], away=f['away'],
                          probabilities=f['probabilities'], over25=f['over25'], btts=f['btts'], top_score=f['top_score'],
                          expected_goals=f['expected_goals'], source=f['source'], kickoff=f.get('kickoff'), status=f.get('status'), form=[round(hp, 2), round(ap, 2)],
                          hype=round(anticipation(hp, ap, f['probabilities']) * LEAGUE_WEIGHT.get(league_id, 1), 1), take=write_up(f, hp, ap)))
    games.sort(key=lambda g: -g['hype'])
    # Spread across the leagues: each league's biggest game first, then the best of the
    # rest with at most two per league, so one division never fills the list.
    picked, per = [], {}
    for g in games:
        if g['league_id'] not in per:
            picked.append(g); per[g['league_id']] = 1
    for cap in (2, 3):
        for g in games:
            if len(picked) >= limit:
                break
            if g not in picked and per[g['league_id']] < cap:
                picked.append(g); per[g['league_id']] += 1
    picked = sorted(picked, key=lambda g: -g['hype'])[:limit]
    every = sorted(games, key=lambda g: (g['date'], g.get('kickoff') or '', g['league']))
    return dict(period=period, label=label, games=picked, all=every,
                leagues={lid: n.split(' — ')[-1] for lid, n in leagues.items() if any(g['league_id'] == lid for g in games)},
                note='Chosen by how strong both clubs are and how close the game looks. Write-ups come straight from the numbers.')
