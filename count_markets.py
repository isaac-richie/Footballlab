"""Corners, cards and shots-on-target from football-data.co.uk statistics.

Out-of-time testing on 2025-26 (en.1, it.1, de.1, monthly refits) found that
team-specific rate models (Poisson/negative binomial attack-defence fits at
several shrinkage and half-life settings) did NOT beat the league's own recent
frequency for corners, and only matched it for cards and shots on target.
So line probabilities here are the league's empirical frequencies over the
past year, and team figures are descriptive recent averages.
"""
import datetime as dt

MIN_RECORDS = 200
SPECS = {
    'corners': dict(stat='corners', totals=(7.5, 8.5, 9.5, 10.5, 11.5, 12.5)),
    'cards': dict(stat='cards', totals=(2.5, 3.5, 4.5, 5.5, 6.5)),
    'shots_on_target': dict(stat='shots_on_target', totals=(6.5, 7.5, 8.5, 9.5, 10.5, 11.5)),
}
TEST_RESULT = ('Tested out of time: team-specific models did not beat these league frequencies, '
               'so line probabilities are the same for every match in the league.')


def stat_value(record, stat):
    stats = (record or {}).get('stats', {})
    if stat == 'cards':
        if 'yellow_cards' in stats and 'red_cards' in stats:
            return [y + r for y, r in zip(stats['yellow_cards'], stats['red_cards'])]
        return None
    return stats.get(stat)


def count_markets(rows, market, league_id, home, away, asof):
    """rows: earlier dataset matches; market: odds_data.index output."""
    cutoff = dt.date.fromisoformat(asof)
    out, withheld = {}, []
    for name, spec in SPECS.items():
        observed = []
        for m in rows:
            value = stat_value(market.get((league_id, m['date'], m['home'], m['away'])), spec['stat'])
            if value is not None:
                observed.append((m, value))
        recent = [(m, v) for m, v in observed if (cutoff - dt.date.fromisoformat(m['date'])).days <= 365]
        if len(recent) < MIN_RECORDS:
            withheld.append(f'{name}: {len(recent)} matches with data in the past year, {MIN_RECORDS} needed')
            continue
        totals = [sum(v) for _, v in recent]
        teams = {}
        for side, team in (('home', home), ('away', away)):
            last = sorted(((m, v) for m, v in observed if team in (m['home'], m['away'])),
                          key=lambda x: x[0]['date'], reverse=True)[:10]
            own = [v[0] if m['home'] == team else v[1] for m, v in last]
            opp = [v[1] if m['home'] == team else v[0] for m, v in last]
            teams[side] = dict(team=team, matches=len(last),
                               average_for=sum(own) / len(own) if own else None,
                               average_against=sum(opp) / len(opp) if opp else None)
        out[name] = dict(league_matches=len(recent), league_average=sum(totals) / len(totals),
                         totals={str(l): sum(t > l for t in totals) / len(totals) for l in spec['totals']},
                         teams=teams)
    return dict(markets=out, withheld=withheld, note=TEST_RESULT + ' Cards count yellows plus reds. '
                'Source: football-data.co.uk (private research use).')
