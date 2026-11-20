"""Deterministic match briefing: evidence, not invented model explanations."""
import math


def briefing(rows, home, away, forecast):
    probabilities = forecast['probabilities']
    order = sorted(range(3), key=lambda i: probabilities[i], reverse=True)
    labels = [home + ' win', 'Draw', away + ' win']
    teams = []
    for team in (home, away):
        recent = sorted((r for r in rows if team in (r['home'], r['away'])),
                        key=lambda r: (r['date'], r['home'], r['away']), reverse=True)[:10]
        scored = conceded = wins = draws = 0
        form = []
        for match in recent:
            own = 0 if match['home'] == team else 1
            gf, ga = match['goals'][own], match['goals'][1-own]
            scored += gf
            conceded += ga
            wins += gf > ga
            draws += gf == ga
            form.append('W' if gf > ga else 'D' if gf == ga else 'L')
        n = len(recent)
        teams.append(dict(team=team, matches=n, form=form, wins=wins, draws=draws,
                          losses=n-wins-draws, goals_for=scored, goals_against=conceded,
                          points_per_match=(3*wins+draws)/n if n else None,
                          latest_date=recent[0]['date'] if n else None))
    return dict(leading_outcome=labels[order[0]], leading_probability=probabilities[order[0]],
                alternative_probability=1-probabilities[order[0]],
                lead_margin=probabilities[order[0]]-probabilities[order[1]],
                normalized_entropy=-sum(p*math.log(p) for p in probabilities if p)/math.log(3),
                team_form=teams,
                interpretation='Outcome concentration is not confidence in model accuracy. Recent form is descriptive, not a causal explanation or an additional model input.',
                limitations=['No verified lineup, injury, referee or weather inputs.',
                             'Model-generated goal rates are not shot-based xG.',
                             'Historical source corrections limit retrospective realism.',
                             'Forward accuracy is not established by this individual forecast.'])


def _own(m, team):
    i = 0 if m['home'] == team else 1
    return m['goals'][i], m['goals'][1 - i]


def _season_of(date):
    y, mth = int(date[:4]), int(date[5:7])
    start = y if mth >= 7 else y - 1
    return f'{start}-{str(start + 1)[-2:]}'


def form_guide(matches, league_id, home, away, asof, h2h_n=8, goals_n=8, halves_n=10):
    """Head to head, season so far, goals record and when goals come, from finished results only.

    matches: every match in the data (any league); only games before `asof` with a score are used.
    The season table counts this league's current season; head to head counts any competition."""
    done = [m for m in matches if m.get('goals') is not None and m['date'] < asof]
    season = m_season = _season_of(asof)
    meet = sorted((m for m in done if {m['home'], m['away']} == {home, away}), key=lambda m: m['date'], reverse=True)[:h2h_n]
    h2h_rows = [dict(date=m['date'], home=m['home'], away=m['away'], goals=m['goals'], league_id=m['league_id'],
                     league=(m.get('league') or m['league_id']).split(' — ')[-1]) for m in meet]
    tally = dict(home=0, draw=0, away=0)
    for m in meet:
        gf, ga = _own(m, home)
        tally['home' if gf > ga else 'away' if gf < ga else 'draw'] += 1
    h2h = dict(games=h2h_rows, wins=tally, avg_goals=(sum(sum(m['goals']) for m in meet) / len(meet)) if meet else None,
               over25=sum(sum(m['goals']) > 2 for m in meet), btts=sum(min(m['goals']) > 0 for m in meet))
    teams = []
    for team in (home, away):
        lg = sorted((m for m in done if m['league_id'] == league_id and m.get('season', _season_of(m['date'])) == m_season
                     and team in (m['home'], m['away'])), key=lambda m: m['date'])
        res = [_own(m, team) for m in lg]
        w = sum(a > b for a, b in res); d = sum(a == b for a, b in res)
        streak = ''
        for a, b in reversed(res):
            r = 'W' if a > b else 'D' if a == b else 'L'
            if not streak or streak[0] == r:
                streak = r + str(int(streak[1:] or 0) + 1)
            else:
                break
        big = max(lg, key=lambda m: (_own(m, team)[0] - _own(m, team)[1], _own(m, team)[0]), default=None)
        big_margin = _own(big, team) if big else None
        venue = lambda where: [(a, b) for m, (a, b) in zip(lg, res) if (m['home'] == team) == (where == 'home')]
        split = {k: dict(played=len(v), won=sum(a > b for a, b in v), drawn=sum(a == b for a, b in v), lost=sum(a < b for a, b in v))
                 for k, v in (('home', venue('home')), ('away', venue('away')))}
        recent = [_own(m, team) for m in sorted((m for m in done if team in (m['home'], m['away'])), key=lambda m: m['date'])[-goals_n:]]
        scored = {str(k): sum(a > k for a, _ in recent) for k in (0.5, 1.5, 2.5, 3.5)}
        conceded = {str(k): sum(b > k for _, b in recent) for k in (0.5, 1.5, 2.5, 3.5)}
        with_ht = [m for m in sorted((m for m in done if team in (m['home'], m['away']) and m.get('ht')), key=lambda m: m['date'])[-halves_n:]]
        first = [(_ht(m, team)) for m in with_ht]
        full = [_own(m, team) for m in with_ht]
        halves = dict(games=len(with_ht),
                      scored=[sum(f[0] for f in first), sum(g[0] - f[0] for g, f in zip(full, first))],
                      conceded=[sum(f[1] for f in first), sum(g[1] - f[1] for g, f in zip(full, first))])
        teams.append(dict(team=team, season=season, played=len(lg), won=w, drawn=d, lost=len(lg) - w - d,
                          goals_for=sum(a for a, _ in res), goals_against=sum(b for _, b in res),
                          points=3 * w + d, clean_sheets=sum(b == 0 for _, b in res), failed_to_score=sum(a == 0 for a, _ in res),
                          biggest_win=(f'{big_margin[0]}-{big_margin[1]}' if big_margin and big_margin[0] > big_margin[1] else None),
                          streak=streak or None, split=split, goals_record=dict(games=len(recent), scored=scored, conceded=conceded),
                          halves=halves))
    return dict(h2h=h2h, teams=teams, note='From final scores in our open results feeds. Head to head counts every competition we hold since 2021.')


def _ht(m, team):
    i = 0 if m['home'] == team else 1
    return m['ht'][i], m['ht'][1 - i]
