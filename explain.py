"""Why this pick, and how much to trust it.

`reason` writes one or two plain sentences from the teams' own recent games (football) or
the projected score (NBA), so every claim can be checked against the results.

`confidence` is a 0-100 score with a High / Medium / Low label. It is not the pick's chance
(that is shown beside it); it says how much the evidence behind that chance holds up:
  strength   how far the chance sits above a coin flip (50% -> 0, 90% -> 1)
  record     how this market did at this chance on our own graded VIP picks: won more than
             it said -> up, less -> down (neutral until a band has 15 graded picks)
  agreement  whether the model alone and the bookmaker-informed price agree (neutral when
             only one of them exists)
minus a penalty when a side has little recent history.
"""

GOAL_LINES = {'ou15': 1.5, 'ou25': 2.5, 'ou35': 3.5}
BANDS = ((.9, '90%+'), (.8, '80-90%'), (.7, '70-80%'), (.6, '60-70%'), (0, 'under 60%'))
MIN_TRACK = 15
MARKET_NAMES = {'ou15': '1.5-goal', 'ou25': '2.5-goal', 'ou35': '3.5-goal', 'btts': 'both-teams-score',
                '1x2': 'match-result', 'dc': 'double-chance', 'total': 'total-points', 'winner': 'winner'}


def band(p):
    return next(name for lo, name in BANDS if p >= lo)


def recent(rows, team, venue=None, n=10):
    """The team's last n finished games (oldest first), optionally only at home or away."""
    games = [m for m in rows if m.get('goals') is not None and (
        (venue != 'away' and m['home'] == team) or (venue != 'home' and m['away'] == team))]
    return sorted(games, key=lambda m: m['date'])[-n:]


def _side(m, team):
    own = 0 if m['home'] == team else 1
    return m['goals'][own], m['goals'][1 - own]


def stats(rows, team, venue=None, n=10):
    g = recent(rows, team, venue, n)
    if not g:
        return None
    tot = [sum(m['goals']) for m in g]
    gf_ga = [_side(m, team) for m in g]
    return dict(n=len(g), totals=tot, avg_total=sum(tot) / len(g),
                over={k: sum(t > k for t in tot) for k in (1.5, 2.5, 3.5)},
                btts=sum(a > 0 and b > 0 for a, b in gf_ga), clean=sum(b == 0 for _, b in gf_ga),
                blank=sum(a == 0 for a, _ in gf_ga), won=sum(a > b for a, b in gf_ga),
                drawn=sum(a == b for a, b in gf_ga), lost=sum(a < b for a, b in gf_ga),
                ppg=sum(3 if a > b else 1 if a == b else 0 for a, b in gf_ga) / len(g),
                gf=sum(a for a, _ in gf_ga) / len(g), ga=sum(b for _, b in gf_ga) / len(g))


def _goals_reason(leg, h, a, hs, as_):
    line = GOAL_LINES[leg['market']]
    over = leg['selection'].startswith('Over')
    hc, ac = hs['over'][line], as_['over'][line]
    if not over:
        hc, ac = hs['n'] - hc, as_['n'] - ac
    word = f'{"over" if over else "under"} {line}'
    avg = (hs['avg_total'] + as_['avg_total']) / 2
    first = f'{hc} of {h}\'s last {hs["n"]} and {ac} of {a}\'s last {as_["n"]} went {word}.'
    tail = f' Their games average {avg:.1f} goals.'
    if over and hs['gf'] + as_['gf'] >= 3:
        tail = f' Between them they score {hs["gf"] + as_["gf"]:.1f} a game.'
    elif not over and hs['ga'] + as_['ga'] <= 2:
        tail = f' Between them they concede {hs["ga"] + as_["ga"]:.1f} a game.'
    return first + tail


def _btts_reason(leg, h, a, hs, as_):
    yes = leg['selection'] == 'Both teams score'
    if yes:
        return (f'Both teams scored in {hs["btts"]} of {h}\'s last {hs["n"]} and {as_["btts"]} of {a}\'s. '
                f'{h} have failed to score {hs["blank"]} times, {a} {as_["blank"]}.')
    return (f'{hs["clean"] + as_["clean"]} clean sheets and {hs["blank"] + as_["blank"]} blanks between them in their last '
            f'{hs["n"] + as_["n"]} games; both scored in only {hs["btts"]} of {h}\'s and {as_["btts"]} of {a}\'s.')


def _result_reason(leg, h, a, rows):
    home, away = stats(rows, h, 'home', 8), stats(rows, a, 'away', 8)
    if not home or not away:
        return None
    sel = leg['selection']
    hf = f'{h} at home: {home["won"]}W {home["drawn"]}D {home["lost"]}L, {home["ppg"]:.1f} points a game'
    af = f'{a} away: {away["won"]}W {away["drawn"]}D {away["lost"]}L, {away["ppg"]:.1f}'
    if sel == 'Draw':
        return f'{home["drawn"]} of {h}\'s last {home["n"]} home games and {away["drawn"]} of {a}\'s last {away["n"]} away were draws. {hf}; {af}.'
    if sel in (f'{h} win', f'{h} or draw'):
        lose = f' {h} have lost {home["lost"]} of their last {home["n"]} at home.' if sel.endswith('draw') else ''
        return f'{hf}; {af}.{lose}'
    if sel in (f'{a} win', f'{a} or draw'):
        lose = f' {a} have lost {away["lost"]} of their last {away["n"]} away.' if sel.endswith('draw') else ''
        return f'{af}; {hf}.{lose}'
    if sel == f'{h} or {a}':
        return f'Only {home["drawn"]} of {h}\'s last {home["n"]} home games and {away["drawn"]} of {a}\'s last {away["n"]} away were draws.'
    return None


def reason(leg, rows):
    """One or two plain sentences behind a football pick, from the clubs' recent results (rows:
    finished games of the league before today), or behind an NBA pick from its projection."""
    if leg.get('sport') == 'nba':
        return nba_reason(leg)
    h, a = leg['home'], leg['away']
    hs, as_ = stats(rows, h), stats(rows, a)
    if not hs or not as_:
        return 'One side has little recent history in this league, so this rests mostly on the model.'
    m = leg['market']
    if m in GOAL_LINES:
        return _goals_reason(leg, h, a, hs, as_)
    if m == 'btts':
        return _btts_reason(leg, h, a, hs, as_)
    if m in ('1x2', 'dc'):
        return _result_reason(leg, h, a, rows)
    return None


def nba_reason(leg):
    exp = leg.get('expected_total')
    if leg.get('market') == 'total' and exp and leg.get('line') is not None:
        gap = exp - leg['line']
        side = 'over' if (leg.get('side') or '').lower() == 'over' else 'under'
        return (f'We project {exp:.0f} points in all, {abs(gap):.0f} {"above" if gap > 0 else "below"} this line: '
                f'the line is set that far from our projection so the {side} lands about {round(leg["probability"] * 100)}% of the time.')
    if leg.get('market') in ('winner', 'moneyline') and leg.get('team'):
        where = ' at home' if leg.get('at_home') else ' on the road' if leg.get('at_home') is False else ''
        return f'Our team ratings make {leg["team"]} a {round(leg["probability"] * 100)}% winner{where}, priced the same way as every pick on our public record.'
    return None


def track_table(record):
    """{(market, band): [picks, won, sum of stated chances]} from the graded VIP picks in record.json."""
    table = {}
    for day in (record or {}).get('days', {}).values():
        for leg in day.get('vip') or []:
            if leg.get('won') is None:
                continue
            t = table.setdefault((leg['market'], band(leg['probability'])), [0, 0, 0.0])
            t[0] += 1
            t[1] += bool(leg['won'])
            t[2] += leg['probability']
    return table


def confidence(leg, track=None, model_p=None, thin=False):
    """{score, label, parts} for one pick; see the module docstring."""
    p = leg['probability']
    strength = min(1.0, max(0.0, (p - .5) / .4))
    rec, record_note = .5, None
    t = (track or {}).get((leg.get('market'), band(p)))
    r = leg.get('record')                                 # NBA: the walk-forward record of this pick's band
    if not t and isinstance(r, dict) and r.get('picks') and r.get('won') is not None and r.get('predicted') is not None:
        t = [r['picks'], r['won'] * r['picks'], r['predicted'] * r['picks']]
    if t and t[0] >= MIN_TRACK:
        won, said = t[1] / t[0], t[2] / t[0]
        rec = min(1.0, max(0.0, .5 + (won - said) * 5))
        record_note = f'{band(p)} {MARKET_NAMES.get(leg.get("market"), leg.get("market"))} picks won {round(won * 100)}% of {t[0]} (said {round(said * 100)}%)'
    agree, agree_note = .5, None
    if model_p is not None and leg.get('source') not in (None, 'model'):
        gap = abs(model_p - p)
        agree = max(0.0, 1 - gap / .15)
        agree_note = 'model and bookmakers agree' if gap < .04 else f'model and bookmakers differ by {round(gap * 100)} points'
    score = 100 * (.55 * strength + .25 * rec + .2 * agree) - (15 if thin else 0)
    score = int(round(min(99, max(1, score))))
    return dict(score=score, label='High' if score >= 70 else 'Medium' if score >= 45 else 'Low',
                parts=[x for x in (record_note, agree_note) if x])


def annotate(legs, rows_for, track=None):
    """Add `why` and `confidence` to each leg in place. rows_for(league_id) -> finished games before today."""
    cache = {}
    for leg in legs:
        try:
            if leg.get('sport') == 'nba':
                rows = []
            else:
                lid = leg['league_id']
                if lid not in cache:
                    cache[lid] = rows_for(lid)
                rows = cache[lid]
            leg['why'] = reason(leg, rows)
            thin = leg.get('sport') != 'nba' and any((s or {}).get('n', 0) < 6 for s in (stats(rows, leg['home']), stats(rows, leg['away'])))
            leg['confidence'] = confidence(leg, track, leg.get('model_probability'), thin)
        except Exception:                                  # an explanation is a nice-to-have
            leg.setdefault('why', None)
    return legs
