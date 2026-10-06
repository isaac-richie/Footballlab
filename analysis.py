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
