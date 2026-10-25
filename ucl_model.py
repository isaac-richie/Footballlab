"""Champions League forecasts: domestic ratings put on one scale across leagues.

A club's attack and defence come from its own league's production ratings on the
match date, relative to that league's average. Leagues differ in quality, so each
gets a strength offset learned from past European results:

    log λ_home = α + h + b·(log att_home + log def_away) + s[league_home] − s[league_away]
    log λ_away = α     + b·(log att_away + log def_home) + s[league_away] − s[league_home]

Clubs from leagues the Lab does not track share an 'other' offset with average
ratings. b < 1 shrinks domestic form towards average, since dominance in a weak
league overstates European strength. Fitted by penalised Poisson likelihood.
"""
import datetime as dt
import math
from functools import lru_cache

TRACKED = ('en.1', 'es.1', 'it.1', 'de.1', 'fr.1', 'tr.1', 'sco.1', 'it.2', 'de.2', 'sa.1')
OTHER = 'other'


def _week(date):
    d = dt.date.fromisoformat(date)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


class Strengths:
    """Domestic attack/defence multipliers per club, cached per league and week."""

    def __init__(self, data, fit):
        self.data, self.fit = data, fit
        self.by_league = {}
        for m in data['matches']:
            if m['league_id'] in TRACKED:
                self.by_league.setdefault(m['league_id'], []).append(m)
        self.cache = {}

    def league_of(self, team, date):
        """The tracked league the club played in during the year before the date."""
        lo = (dt.date.fromisoformat(date) - dt.timedelta(days=365)).isoformat()
        best = None
        for lg, rows in self.by_league.items():
            if lg in ('it.2', 'de.2'):
                continue
            n = sum(1 for m in rows if lo <= m['date'] < date and team in (m['home'], m['away']))
            if n >= 5 and (best is None or n > best[1]):
                best = (lg, n)
        return best[0] if best else None

    def table(self, league, date):
        key = (league, _week(date))
        if key in self.cache:
            return self.cache[key]
        cut = _week(date)
        rows = [m for m in self.by_league[league] if m['goals'] is not None and m['date'] < cut]
        lo = (dt.date.fromisoformat(cut) - dt.timedelta(days=365)).isoformat()
        teams = sorted({t for m in rows if m['date'] >= lo for t in (m['home'], m['away'])})
        out = {}
        if len(rows) >= 100 and len(teams) >= 6:
            expected, _, _ = self.fit(rows, cut, teams)
            pairs = [(a, b) for a in teams for b in teams if a != b]
            mean = math.exp(sum(math.log(x) for a, b in pairs for x in expected(a, b)) / (2 * len(pairs)))
            for t in teams:
                scored = [expected(t, o)[0] for o in teams if o != t] + [expected(o, t)[1] for o in teams if o != t]
                conceded = [expected(t, o)[1] for o in teams if o != t] + [expected(o, t)[0] for o in teams if o != t]
                gm = lambda xs: math.exp(sum(math.log(x) for x in xs) / len(xs))
                out[t] = (gm(scored) / mean, gm(conceded) / mean)
        self.cache[key] = out
        return out

    def of(self, team, date):
        """(league or 'other', log attack, log defence)."""
        lg = self.league_of(team, date)
        if not lg:
            return OTHER, 0.0, 0.0
        att, dfn = self.table(lg, date).get(team, (1.0, 1.0))
        return lg, math.log(att), math.log(dfn)


def features(matches, strengths):
    out = []
    for m in matches:
        lh, ah, dh = strengths.of(m['home'], m['date'])
        la, aa, da = strengths.of(m['away'], m['date'])
        out.append((m, lh, ah, dh, la, aa, da))
    return out


def fit_params(rows, ridge=0.08, iterations=600):
    """Penalised Poisson fit of α, h, b and league offsets s (s['en.1'] fixed at 0)."""
    leagues = sorted({r[1] for r in rows} | {r[4] for r in rows} | {OTHER})
    free = [lg for lg in leagues if lg != 'en.1']
    p = dict(alpha=math.log(1.35), h=0.2, b=0.8, **{'s_' + lg: 0.0 for lg in free})
    keys = list(p)
    m_, v_ = {k: 0.0 for k in keys}, {k: 0.0 for k in keys}
    s = lambda lg: 0.0 if lg == 'en.1' else p['s_' + lg]
    for step in range(1, iterations + 1):
        g = {k: 0.0 for k in keys}
        for m, lh, ah, dh, la, aa, da in rows:
            hg, ag = m['goals']
            eh = p['alpha'] + p['h'] + p['b'] * (ah + da) + s(lh) - s(la)
            ea = p['alpha'] + p['b'] * (aa + dh) + s(la) - s(lh)
            rh, ra = math.exp(min(eh, 3)) - hg, math.exp(min(ea, 3)) - ag
            g['alpha'] += rh + ra; g['h'] += rh; g['b'] += rh * (ah + da) + ra * (aa + dh)
            if lh != 'en.1': g['s_' + lh] += rh - ra
            if la != 'en.1': g['s_' + la] += ra - rh
        n = len(rows)
        for k in keys:
            gk = g[k] / n + (ridge * p[k] if k.startswith('s_') else 0.0)
            m_[k] = .9 * m_[k] + .1 * gk; v_[k] = .999 * v_[k] + .001 * gk * gk
            p[k] -= .02 * (m_[k] / (1 - .9 ** step)) / (math.sqrt(v_[k] / (1 - .999 ** step)) + 1e-8)
    return p


def rates(p, lh, ah, dh, la, aa, da):
    s = lambda lg: 0.0 if lg == 'en.1' else p.get('s_' + lg, p.get('s_' + OTHER, 0.0))
    return (math.exp(p['alpha'] + p['h'] + p['b'] * (ah + da) + s(lh) - s(la)),
            math.exp(p['alpha'] + p['b'] * (aa + dh) + s(la) - s(lh)))


def evaluate(data, ucl_matches, fit, distribution, test_from='2024-07-01'):
    """Out-of-time: offsets learned before test_from, scored on later European games."""
    played = sorted((m for m in ucl_matches if m['goals'] is not None), key=lambda m: m['date'])
    st = Strengths(data, fit)
    rows = features(played, st)
    train = [r for r in rows if r[0]['date'] < test_from]
    test = [r for r in rows if r[0]['date'] >= test_from]
    p = fit_params(train)
    flat = fit_params(train, ridge=1e6)          # no league offsets: domestic ratings taken at face value
    base = [1, 1, 1]
    for r in train:
        h, a = r[0]['goals']; base[0 if h > a else 1 if h == a else 2] += 1
    base = [x / sum(base) for x in base]
    ll = {'model': 0.0, 'no_league_strength': 0.0, 'base_rates': 0.0}
    for r in test:
        h, a = r[0]['goals']; o = 0 if h > a else 1 if h == a else 2
        ll['model'] -= math.log(max(distribution(*rates(p, *r[1:]))['probabilities'][o], 1e-9))
        ll['no_league_strength'] -= math.log(max(distribution(*rates(flat, *r[1:]))['probabilities'][o], 1e-9))
        ll['base_rates'] -= math.log(base[o])
    n = max(1, len(test))
    tracked = sum(r[1] != OTHER and r[4] != OTHER for r in test)
    return dict(train=len(train), test=len(test), test_both_tracked=tracked,
                log_loss={k: round(v / n, 4) for k, v in ll.items()},
                params={k: round(v, 3) for k, v in p.items()})


class Forecaster:
    """Production use: offsets fitted on every finished European game, cached per day on disk."""

    def __init__(self, data, ucl_matches, fit, cache_file):
        import json
        self.strengths = Strengths(data, fit)
        today = dt.date.today().isoformat()
        try:
            saved = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            saved = {}
        played = [m for m in ucl_matches if m['goals'] is not None and m['date'] < today]
        stamp = f'{today}|{len(played)}'
        if saved.get('stamp') == stamp:
            self.params = saved['params']
        else:
            self.params = fit_params(features(played, self.strengths))
            from quality import atomic_write
            atomic_write(cache_file, json.dumps(dict(stamp=stamp, params=self.params, games=len(played))))

    def rates(self, home, away, date):
        lh, ah, dh = self.strengths.of(home, date)
        la, aa, da = self.strengths.of(away, date)
        return rates(self.params, lh, ah, dh, la, aa, da), (lh, la)
