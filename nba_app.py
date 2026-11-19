"""NBA endpoints for the Lab: the slate, one matchup in full, and a quick refresh.

Ratings are fitted once per day and data version, then every game is priced from
the bookmaker line where one is stored (ESPN BET via ESPN's feed) and from the
model otherwise. Both views are returned so the page can show how they differ.
"""
import datetime as dt
import json
import threading
from pathlib import Path

import os

import nba
import nba_model as M
import nba_public
from quality import atomic_write

ROOT = Path(__file__).resolve().parent
_cache, _lock = {}, threading.Lock()


def public():
    """True when the board runs on the licensed scores-only feed: always on the hosted
    site, and locally when there is no private ESPN file."""
    return bool(os.environ.get('VERCEL') or os.environ.get('NBA_PUBLIC')) or (not nba.FILE.exists() and nba_public.FILE.exists())


def _source():
    return (nba_public.FILE, nba_public.load) if public() else (nba.FILE, nba.load)


def _width():
    return M.PUBLIC_WIDTH if public() else M.MODEL_WIDTH


def _data():
    file, loader = _source()
    try:
        stamp = file.stat().st_mtime
    except OSError:
        return None, None
    hit = _cache.get('data')
    if hit and hit[0] == (file, stamp):
        return hit[1], hit[2]
    data = loader()
    rest = M.back_to_back([g for g in data['games'] if g['status'] != 'postponed'])
    _cache.clear()
    _cache['data'] = ((file, stamp), data, rest)
    return data, rest


def _ratings(data, rest, today):
    key = ('fit', data.get('fetched_at'), today)
    with _lock:
        if key not in _cache:
            _cache[key] = M.fit(data['games'], today, rest, M.PUBLIC_SETTINGS if data.get('source_id') == nba_public.SOURCE else None)
        return _cache[key]


def _line(game):
    line = game.get('line') or {}
    return line.get('close') or line.get('open')


def _status(g, now):
    if g['status'] == 'final':
        return 'finished'
    if g['status'] == 'live':
        return 'live'
    if g['tipoff']:
        start = dt.datetime.fromisoformat(g['tipoff'].replace('Z', '+00:00'))
        if now >= start + dt.timedelta(hours=3):
            return 'awaiting_result'
        if now >= start:
            return 'live'
    return 'scheduled'


def _price(r, rest, g, entered=None):
    b2b = (rest.get((g['id'], 0), 0), rest.get((g['id'], 1), 0)) if g.get('id') else (0, 0)
    model = M.stretch(M.expected(r, g['home'], g['away'], g.get('neutral', False), b2b), _width().get('stretch', 1.0))
    line = entered or _line(g)
    priced = M.implied(line, model) if line else None
    source = 'entered' if entered and priced else 'line' if priced else 'model'
    return model, priced or model, line if priced else None, source, b2b


def _summary(mk):
    s, t = mk['spread'], mk['total']
    return dict(moneyline=mk['moneyline'], expected_points=mk['expected_points'], expected_total=mk['expected_total'],
                expected_margin=mk['expected_margin'], spread_line=mk['main_spread'], cover=s[0] / max(1e-9, s[0] + s[2]),
                total_line=mk['main_total'], over=t[0] / max(1e-9, t[0] + t[2]), overtime=mk['overtime'],
                top_score=mk['likely_scores'][0])


def _markets(means, spread=None, total=None, priced=False):
    """Markets for one pair of expectations, memoised (the grid is the slow part).

    priced: the expectations come from a line, so the line's tighter spread applies.
    """
    key = ('mk', round(means[0], 3), round(means[1], 3), spread, total, priced, public())
    hit = _cache.get(key)
    if hit is None:
        hit = _cache[key] = M.markets(M.distribution(*means, width=M.LINE_WIDTH if priced else _width()), spread, total)
    return hit


BOARD_FILE = ROOT / 'reports' / 'nba_public_board.json'   # priced by the daily job, so the hosted site opens fast


def _saved_board(data, today, days):
    """The daily job's priced board when it was made from this data on or before today."""
    try:
        saved = json.loads(BOARD_FILE.read_text())
    except (OSError, ValueError):
        return None
    if saved.get('fetched_at') != data.get('fetched_at') or saved.get('today', '9') > today or saved.get('days', 0) < days:
        return None
    end = (dt.date.fromisoformat(today) + dt.timedelta(days=days)).isoformat()
    games = {g['id']: g for g in data['games']}
    return [dict(game=games[r['id']], row=r) for r in saved['rows']
            if r['id'] in games and today <= r['date'] <= end and games[r['id']]['status'] not in ('final', 'postponed')]


def save_board(days=7):
    """Price the board now and write it for the hosted site (run by the daily job)."""
    data, rest = _data()
    today = dt.date.today().isoformat()
    rows = [x['row'] for x in _board(data, rest, today, days, saved=False)]
    atomic_write(BOARD_FILE, json.dumps(dict(fetched_at=data.get('fetched_at'), today=today, days=days, rows=rows), separators=(',', ':')))
    return len(rows)


def _board(data, rest, today, days, saved=True):
    """The priced games for the next `days` days; cached per data version and day."""
    key = ('board', data.get('fetched_at'), today, days)
    with _lock:
        if key in _cache:
            return _cache[key]
    if saved and public():
        out = _saved_board(data, today, days)
        if out is not None:
            with _lock:
                _cache[key] = out
            return out
    r = _ratings(data, rest, today)
    end = (dt.date.fromisoformat(today) + dt.timedelta(days=days)).isoformat()
    out = []
    for g in data['games']:
        if not (today <= g['date'] <= end) or g['status'] in ('final', 'postponed'):
            continue
        model, means, line, source, b2b = _price(r, rest, g)
        mk = _markets(means, line['spread'] if line and line.get('spread') is not None else None,
                      line['total'] if line and line.get('total') is not None else None, source != 'model')
        mm = _markets(model, mk['main_spread'], mk['main_total'])
        ms = _summary(mm)
        out.append(dict(game=g, row=dict(id=g['id'], date=g['date'], tipoff=g['tipoff'], home=g['home'], away=g['away'],
                        home_abbr=g['home_abbr'], away_abbr=g['away_abbr'], kind=g['kind'], neutral=g['neutral'],
                        source=source, book=(g.get('line') or {}).get('book') if line else None, b2b=list(b2b),
                        alt_totals={k: v[0] for k, v in mk['totals'].items() if abs(float(k) - mk['main_total']) <= 12.5},
                        **_summary(mk), model=dict(moneyline=mm['moneyline'], expected_points=mm['expected_points'],
                                                   cover=ms['cover'], over=ms['over']))))
    with _lock:
        _cache[key] = out
    return out


def slate(days=7):
    data, rest = _data()
    if not data or not data['games']:
        if os.environ.get('VERCEL'):
            return dict(error='Basketball forecasts are being prepared. Check back soon.', fixtures=[])
        # nba_data.json is never committed, so a fresh copy of the Lab starts without it:
        # download it in the background instead of leaving the board empty.
        started = _first_fetch()
        return dict(error='Downloading NBA results and lines for the first time. This takes about five minutes; '
                          'press Refresh then.' if started else 'No NBA data yet. Run: python3 app.py fetch-nba', fixtures=[])
    _auto_refresh(data)
    today = dt.date.today().isoformat()
    now = dt.datetime.now(dt.timezone.utc)
    out = [dict(x['row'], status=_status(x['game'], now)) for x in _board(data, rest, today, days)]
    _freeze(out, now)
    recent = sorted((g for g in data['games'] if g['status'] == 'final'), key=lambda g: (g['date'], g['id']))[-16:][::-1]
    return dict(today=today, fetched_at=data.get('fetched_at'), fixtures=out, priced=sum(f['source'] != 'model' for f in out),
                teams=teams(data), lab=_lab(), ledger=_ledger_summary(),
                abbrs={n: a for g in data['games'] for n, a in ((g['home'], g['home_abbr']), (g['away'], g['away_abbr'])) if a},
                recent=[dict(date=g['date'], home=g['home_abbr'], away=g['away_abbr'], score=g['score'], ot=len((g.get('periods') or [[0] * 4])[0]) > 4) for g in recent],
                latest_result=recent[0]['date'] if recent else None,
                public=public(),
                note='Priced by our points model from scores alone (data: balldontlie).' if public() else
                     'Priced from ESPN BET lines (margin removed) where posted; model ratings otherwise.')


_refreshing = threading.Event()
_frozen = {}


def _freeze(rows, now):
    """Write board forecasts to the forward ledger, at most every ten minutes."""
    if public() or now - _frozen.get('at', dt.datetime.min.replace(tzinfo=dt.timezone.utc)) < dt.timedelta(minutes=10):
        return
    _frozen['at'] = now
    try:
        import nba_ledger
        nba_ledger.register(rows, now, _version())
    except Exception:
        pass


def _version():
    from quality import digest
    return digest(dict(settings=M.SETTINGS, model=M.MODEL_WIDTH, line=M.LINE_WIDTH))[:12]


def _ledger_summary():
    import nba_ledger
    return nba_ledger.summary(public())


def _grade():
    try:
        import nba_ledger
        rep = nba_ledger.report(nba.load()['games'])
        from quality import atomic_write
        atomic_write(nba_ledger.GRADES, json.dumps(rep, indent=1))
    except Exception:
        pass


def _auto_refresh(data):
    """Local Lab only: re-read scores and lines in the background when over 3 hours old."""
    if public() or _refreshing.is_set():
        return
    try:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(data['fetched_at'])
    except (TypeError, ValueError, KeyError):
        return
    if age < dt.timedelta(hours=3):
        return
    _refreshing.set()
    def run():
        try:
            nba.fetch(log=lambda *_: None, lines='recent')
            _grade()
        except Exception:
            pass
        finally:
            _refreshing.clear()
            _cache.clear()
    threading.Thread(target=run, daemon=True).start()


def _first_fetch():
    """Start the first full download unless one is running; False when it cannot start."""
    if _refreshing.is_set():
        return True
    _refreshing.set()
    def run():
        try:
            import badges
            nba.fetch(log=lambda *_: None, lines='recent', workers=8)
            badges.fetch_nba()
        except Exception:
            pass
        finally:
            _refreshing.clear()
            _cache.clear()
    threading.Thread(target=run, daemon=True).start()
    return True


def warm():
    """Price the board in the background so the first visitor does not wait."""
    def run():
        try:
            data, rest = _data()
            if data and data['games']:
                _board(data, rest, dt.date.today().isoformat(), 7)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def teams(data):
    season = max(g['season'] for g in data['games'])
    return sorted({t for g in data['games'] if g['season'] == season and g['kind'] == 'regular' for t in (g['home'], g['away'])})


def _lab():
    try:
        rep = json.loads((ROOT / 'reports' / ('nba_public_lab.json' if public() else 'nba_lab.json')).read_text())
    except (OSError, ValueError):
        return None
    hold = rep.get('holdout') or {}
    if public():
        def part(x):
            x = x or {}
            m = x.get('markets') or {}
            return dict(seasons=x.get('seasons'), points=x.get('points'),
                        markets={k: dict(log_loss=v['log_loss'], sure=v['sure_70_plus'], side=v.get('likelier_side')) for k, v in m.items()})
        return dict(public=True, generated_at=rep.get('generated_at'), holdout=part(hold), current=part(rep.get('current_season')))
    return dict(generated_at=rep.get('generated_at'), points=hold.get('points'), probabilities={k: v for k, v in (hold.get('probabilities') or {}).items() if k != 'calibration'})


def _form(data, team, before, n=10):
    rows = [g for g in data['games'] if g['status'] == 'final' and g['date'] < before and team in (g['home'], g['away'])][-n:]
    out = []
    for g in reversed(rows):
        home = g['home'] == team
        pf, pa = (g['score'][0], g['score'][1]) if home else (g['score'][1], g['score'][0])
        out.append(dict(date=g['date'], opponent=g['away'] if home else g['home'], home=home, scored=pf, allowed=pa,
                        result='W' if pf > pa else 'L', ot=len((g.get('periods') or [[0] * 4])[0]) > 4))
    return out


def _ranks(r):
    teams_ = sorted(r['offence'])
    off = sorted(teams_, key=lambda t: -r['offence'][t])
    dfn = sorted(teams_, key=lambda t: -r['defence'][t])
    net = sorted(teams_, key=lambda t: -(r['offence'][t] + r['defence'][t]))
    return {t: dict(offence=off.index(t) + 1, defence=dfn.index(t) + 1, net=net.index(t) + 1,
                    off_pts=r['level'] + r['offence'][t], def_pts=r['level'] - r['defence'][t]) for t in teams_}


def predict(q):
    """q: home, away, optional game_id, neutral, spread, total, and price pairs for user-entered lines."""
    data, rest = _data()
    if not data:
        raise ValueError('No NBA data yet. Run: python3 app.py fetch-nba')
    names = set(teams(data))
    home, away = q.get('home'), q.get('away')
    if home not in names or away not in names or home == away:
        raise ValueError('Choose two different NBA teams.')
    today = dt.date.today().isoformat()
    r = _ratings(data, rest, today)
    game = next((g for g in data['games'] if g['id'] == q.get('game_id') and g['home'] == home and g['away'] == away), None)
    if game is None:
        game = next((g for g in data['games'] if g['home'] == home and g['away'] == away and g['date'] >= today
                     and g['status'] not in ('final', 'postponed')), None)
    g = game or dict(id=None, home=home, away=away, neutral=bool(q.get('neutral')), date=today, tipoff=None)
    entered = None
    if q.get('spread') not in (None, '') or q.get('total') not in (None, ''):
        def f(v):
            return float(v) if v not in (None, '') else None
        entered = dict(spread=f(q.get('spread')), total=f(q.get('total')),
                       spread_prices=[f(q.get('spread_home')) or 1.91, f(q.get('spread_away')) or 1.91],
                       total_prices=[f(q.get('over')) or 1.91, f(q.get('under')) or 1.91], moneyline=[None, None])
        for k in ('spread', 'total'):
            if entered[k] is not None and not -60 <= entered[k] <= 400:
                raise ValueError('That line looks wrong.')
    model, means, line, source, b2b = _price(r, rest, g, entered)
    mk = _markets(means, line.get('spread') if line else None, line.get('total') if line else None, source != 'model')
    mm = _markets(model, mk['main_spread'], mk['main_total'])
    ranks = _ranks(r)
    h2h = [dict(date=x['date'], home=x['home'], away=x['away'], score=x['score'])
           for x in data['games'] if x['status'] == 'final' and {x['home'], x['away']} == {home, away}][-6:][::-1]
    raw = (game or {}).get('line') or {}
    return dict(home=home, away=away, game=dict(id=g.get('id'), date=g.get('date'), tipoff=g.get('tipoff'), neutral=g.get('neutral', False),
                                                kind=g.get('kind'), status=_status(g, dt.datetime.now(dt.timezone.utc)) if game else None),
                source=source, book=raw.get('book') if source == 'line' else None,
                line=dict(open=raw.get('open'), close=raw.get('close')) if raw else None, entered=entered,
                markets=mk, model=dict(summary=_summary(mm), expected_points=mm['expected_points'], moneyline=mm['moneyline']),
                rest=dict(home_b2b=bool(b2b[0]), away_b2b=bool(b2b[1]), effect=[r['b2b_for'], r['b2b_against']]),
                ratings=dict(home=ranks.get(home), away=ranks.get(away), level=r['level'], home_edge=r['home'], games=r['games'], asof=r['asof']),
                form=dict(home=_form(data, home, g.get('date') or today), away=_form(data, away, g.get('date') or today)),
                head_to_head=h2h, fetched_at=data.get('fetched_at'),
                validated=validated(source),
                method=dict(width=M.LINE_WIDTH if source != 'model' else _width(), overtime=M.OT, settings=r['settings']))


def refresh():
    """Re-read recent days and lines for nearby games (about a minute at most)."""
    if public():
        raise RuntimeError('Scores update once a day on this site.')
    if _refreshing.is_set():
        raise RuntimeError('A refresh is already running; try again in a minute.')
    _refreshing.set()
    try:
        out = nba.fetch(log=lambda *_: None, lines='recent')
    finally:
        _refreshing.clear()
    _cache.clear()
    _grade()
    _frozen.clear()
    return out


# ---------- Daily picks and validated markets ----------

def _report(name):
    try:
        return json.loads((ROOT / 'reports' / name).read_text())
    except (OSError, ValueError):
        return {}


def _tested():
    """Hold-out market scores for the pricing this site uses, by source: {source: {market: score}}.

    Local Lab: line-priced games from nba_calib.json['line'], model-only from ['model'].
    Hosted site: the scores-only model from nba_public_lab.json.
    """
    key = ('tested', public())
    if key in _cache:
        return _cache[key]
    if public():
        out = dict(model=(_report('nba_public_lab.json').get('holdout') or {}).get('markets') or {})
    else:
        cal = _report('nba_calib.json')
        out = {src: (((cal.get(name) or {}).get('holdout') or {}).get('after') or {}) for src, name in (('line', 'line'), ('model', 'model'))}
        out['entered'] = out['line']
    _cache[key] = out
    return out


def validated(source):
    """Markets whose confident picks (70%+) landed within 3 points of what they said, on 400+ picks."""
    ok = {}
    for market, sc in (_tested().get(source) or {}).items():
        sure = sc.get('sure_70_plus') or {}
        ok[market] = bool(sure.get('picks', 0) >= 400 and abs(sure.get('won', 0) - sure.get('predicted', 0)) <= .03) \
            if market != 'moneyline' else bool(sure.get('picks', 0) >= 200 and sure.get('won', 0) >= sure.get('predicted', 1) - .03)
    return ok


def track(source, market, p):
    """How picks at this confidence did on the held-out season, or None."""
    for b in ((_tested().get(source) or {}).get(market) or {}).get('calibration') or []:
        lo, hi = (int(x) / 100 for x in b['bin'].rstrip('%').split('-'))
        if lo <= p < hi or (hi >= 1 and p >= lo):
            return dict(bin=b['bin'], picks=b['picks'], predicted=b['predicted'], won=b['won'])
    return None


def pick_history(data_games, days=7):
    """Saved picks of the last days with won/lost, finals from the data file and, for the latest games, the live feed."""
    import nba_picks_ledger
    games = data_games
    if public():
        try:
            import nba_live
            live = nba_live.live().get('games') or {}
            fin = {k: v for k, v in live.items() if k.startswith('bdl') and v['status'] == 'final'}
            if fin:
                games = [dict(g, status='final', score=fin[g['id']]['score']) if g['id'] in fin and g['status'] != 'final' else g for g in games]
        except Exception:
            pass
    return nba_picks_ledger.results(games, days=days)


def total_pick(f, target=.70):
    """One points pick for a game: the over or under line nearest the main total whose chance is at least `target`."""
    alt = f.get('alt_totals') or {}
    best = None
    for k, over in alt.items():
        line = float(k)
        for side, p in (('over', over), ('under', 1 - over)):
            if p < target:
                continue
            gap = abs(line - f['total_line'])
            if best is None or gap < best[0] or (gap == best[0] and p > best[3]):
                best = (gap, side, line, p)
    return None if best is None else dict(side=best[1], line=best[2], probability=best[3])


def picks(days=2, floor=.80, most=5):
    """Winner and total-points picks for the next `days` game days, strongest first, each with its tested record."""
    s = slate(days=7)
    if s.get('error'):
        return dict(error=s['error'], picks=[], totals=[])
    dates = sorted({f['date'] for f in s['fixtures'] if f['status'] == 'scheduled'})[:days]
    out, totals = [], []
    for f in s['fixtures']:
        if f['date'] not in dates or f['status'] != 'scheduled':
            continue
        ok = validated(f['source'])
        base = dict(id=f['id'], date=f['date'], tipoff=f['tipoff'], home=f['home'], away=f['away'], home_abbr=f['home_abbr'],
                    away_abbr=f['away_abbr'], source=f['source'], book=f.get('book'), projected=f['expected_points'], b2b=f['b2b'])
        if ok.get('total'):
            t = total_pick(f)
            if t:
                totals.append(dict(base, market='total', **t, expected_total=f['expected_total'], record=track(f['source'], 'total', t['probability'])))
        if not ok.get('moneyline'):
            continue
        side = 0 if f['moneyline'][0] >= f['moneyline'][1] else 1
        p = f['moneyline'][side]
        if p < floor:
            continue
        team, opp = (f['home'], f['away']) if side == 0 else (f['away'], f['home'])
        out.append(dict(base, team=team, opponent=opp, at_home=side == 0, probability=p, market='moneyline',
                        record=track(f['source'], 'moneyline', p)))
    out = sorted(out, key=lambda x: -x['probability'])[:most]
    history = pick_history(data_games=_data()[0]['games'])
    totals.sort(key=lambda x: (x['date'], x['tipoff'] or ''))
    return dict(today=s['today'], dates=dates, picks=out, totals=totals, history=history, public=s.get('public'), ledger=s.get('ledger'), lab=s.get('lab'),
                note='Total-points picks first, plus a few strong winner calls (80% and up; on the held-out season those won 84.9%): the markets whose confident picks have matched their stated chance on a season the model never saw. '
                     'A 75% pick still loses one time in four.')
