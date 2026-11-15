"""Live NBA scores for the board, from balldontlie's games list (free plan).

One request covers every game on the US dates of "today" (yesterday and today in
US time, so late games still show). The answer is cached for a minute in the
process and, on Vercel, at the CDN (the route sends s-maxage), so the request rate
stays at about one a minute however many people are watching: inside the free
plan's 5 a minute. The forward record is still graded by the daily job only.
"""
import datetime as dt
import os
import threading
import time

import nba_public

TTL = 60
_cache = dict(at=0.0, value=None)
_lock = threading.Lock()


def _state(e):
    state = e.get('status_state') or ''
    if e.get('postponed'):
        return 'postponed'
    if state == 'final' or e.get('status') == 'Final':
        return 'final'
    if state == 'in' or (e.get('period') or 0) > 0:
        return 'live'
    return 'scheduled'


def _clock(e):
    period, t = e.get('period') or 0, (e.get('time') or '').strip()
    if not period:
        return ''
    name = f'Q{period}' if period <= 4 else f'OT{period - 4}' if period > 5 else 'OT'
    if t.lower() in ('half', 'halftime'):
        return 'Half'
    return f'{name} {t}'.strip() if t and t.lower() != 'final' else name


def snapshot(events, now=None):
    """{key: live row} for balldontlie events; keys are the board ids and date|home abbr."""
    out = {}
    for e in events:
        g = nba_public.to_game(e)
        if not g:
            continue
        state = _state(e)
        if state == 'scheduled':
            continue
        row = dict(status=state, score=[e.get('home_team_score') or 0, e.get('visitor_team_score') or 0],
                   clock='Final' if state == 'final' else _clock(e) if state == 'live' else 'Postponed')
        out[g['id']] = row
        out[f"{g['date']}|{g['home_abbr']}"] = row
    return out


def live(key=None, now=None):
    key = key or os.environ.get('BALLDONTLIE_API_KEY', '').strip()
    if not key:
        return dict(games={}, error='no key')
    with _lock:
        if _cache['value'] is not None and time.monotonic() - _cache['at'] < TTL:
            return _cache['value']
        now = now or dt.datetime.now(dt.timezone.utc)
        us = (now - dt.timedelta(hours=5)).date()          # US Eastern date, near enough
        dates = [(us - dt.timedelta(days=1)).isoformat(), us.isoformat()]
        try:
            page = nba_public._get({'dates[]': dates, 'per_page': 100}, key, tries=2)
            value = dict(games=snapshot(page.get('data', [])), fetched_at=now.isoformat(), ttl=TTL)
        except Exception as exc:                               # keep serving the last good answer
            value = _cache['value'] or dict(games={}, error=str(exc)[:200])
        _cache.update(at=time.monotonic(), value=value)
        return value
