"""Reconcile the fixture list with football-data.co.uk's results and weekly fixtures file.

OpenFootball's dates for upcoming games lag behind reschedules and carry no kickoff
time, and it has no current Serie B season at all. In the private Lab only (never
saved or published), football-data decides:

  * current-season results missing from the open feed are added;
  * upcoming fixtures take football-data's date and UK kickoff time;
  * open-feed fixtures inside football-data's window that it does not list are
    marked unconfirmed and kept out of forecasts, since their date is wrong.

Each fixture also gets a kickoff time (UTC) and a status: scheduled, live,
awaiting_result (should be over, no score yet) or finished.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from live_odds import similarity

UK = ZoneInfo('Europe/London')
MATCH_MINUTES = 115          # 90 + half-time + stoppages


def season_for(date):
    d = dt.date.fromisoformat(date)
    y = d.year if d.month >= 7 else d.year - 1
    return f'{y}-{str(y + 1)[-2:]}'


def kickoff_utc(date, time):
    if not time:
        return None
    try:
        h, m = (int(x) for x in time.split(':')[:2])
        local = dt.datetime.fromisoformat(date).replace(hour=h, minute=m, tzinfo=UK)
    except ValueError:
        return None
    return local.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def status(m, now=None):
    if m.get('goals') is not None:
        return 'finished'
    now = now or dt.datetime.now(dt.timezone.utc)
    if m.get('kickoff'):
        start = dt.datetime.fromisoformat(m['kickoff'].replace('Z', '+00:00'))
        if now < start:
            return 'scheduled'
        return 'live' if now < start + dt.timedelta(minutes=MATCH_MINUTES) else 'awaiting_result'
    today = now.date().isoformat()
    return 'scheduled' if m['date'] >= today else 'awaiting_result'


def _resolve(name, mapped, teams):
    """Dataset name for a football-data team: the learned mapping, a close name, or as is."""
    if mapped:
        return mapped
    best = max(teams, key=lambda t: similarity(name, t), default=None)
    return best if best and similarity(name, best) >= 0.72 else name


def reconcile(data, market, today=None, live_cache=None):
    today = today or dt.date.today().isoformat()
    matches = data['matches']
    by_league = {}
    for m in matches:
        by_league.setdefault(m['league_id'], []).append(m)
    current = season_for(today)
    added = moved = unconfirmed = 0
    for league_id, rows in by_league.items():
        teams = sorted({t for m in rows if m['date'] >= str(int(today[:4]) - 1) for t in (m['home'], m['away'])})
        recs = [r for r in market.get('records', []) if r['league_id'] == league_id
                and (r.get('upcoming') or season_for(r['date']) == current)]
        if not recs:
            continue
        pairs = {}
        for m in rows:
            pairs.setdefault((m['home'], m['away']), []).append(m)
        for r in sorted(recs, key=lambda r: (not r.get('upcoming'), r['date'])):
            home, away = _resolve(r['fd_home'], r.get('home'), teams), _resolve(r['fd_away'], r.get('away'), teams)
            day = dt.date.fromisoformat(r['date'])
            near = [m for m in pairs.get((home, away), []) if abs((dt.date.fromisoformat(m['date']) - day).days) <= 28
                    and (m['goals'] is None or abs((dt.date.fromisoformat(m['date']) - day).days) <= 1)]
            m = min(near, key=lambda m: abs((dt.date.fromisoformat(m['date']) - day).days), default=None)
            if m is None:
                m = dict(league_id=league_id, league=rows[0].get('league'), season=season_for(r['date']), date=r['date'],
                         home=home, away=away, goals=None, ht=None, schedule_source='football-data')
                matches.append(m); pairs.setdefault((home, away), []).append(m); added += 1
            if m['date'] != r['date']:
                m['date'] = r['date']; moved += 1
            if r.get('goals') and m['goals'] is None and not r.get('upcoming'):
                m['goals'], m['ht'], m['goals_source'] = list(r['goals']), r.get('ht'), 'football-data'
            m['kickoff'] = kickoff_utc(r['date'], r.get('time')) or m.get('kickoff')
            m['confirmed'] = True
            if r.get('odds'):
                m['_fd'] = r               # prices for clubs the name map has not learned yet
        # Anything the open feed dates inside football-data's window but football-data
        # does not list has a stale date.
        window = [r['date'] for r in recs if r.get('upcoming')]
        if window:
            lo, hi = min(window), max(window)
            for m in rows:
                if m['goals'] is None and lo <= m['date'] <= hi and not m.get('confirmed'):
                    m['unconfirmed'] = True; unconfirmed += 1
    # Exact kickoff from the live odds feed, when present.
    for league_id, entry in (live_cache or {}).get('leagues', {}).items():
        for k, v in entry.get('odds', {}).items():
            date, home, away = k.split('|')
            for m in by_league.get(league_id, []):
                if m['home'] == home and m['away'] == away and m['date'] == date and v.get('commence_time'):
                    m['kickoff'] = v['commence_time']
    # Leagues whose current season now comes from football-data get a freshness record.
    for league_id in {m['league_id'] for m in matches if m.get('schedule_source') == 'football-data' and m['season'] == current}:
        data.setdefault('sources', []).append(dict(url=f'football-data:{league_id}/{current}/', league_id=league_id,
                                                   checked_at=market.get('fetched_at'), license=market.get('license')))
    matches.sort(key=lambda m: (m['date'], m.get('kickoff') or ''))
    data['schedule'] = dict(added=added, moved=moved, unconfirmed=unconfirmed)
    return data['schedule']
