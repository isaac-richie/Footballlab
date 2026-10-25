"""Data validation, provenance and explicit research-readiness checks."""
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_ROOT = Path(__file__).resolve().parent


def atomic_write(path, text):
    path = Path(path)
    # Serverless hosts (Vercel) only allow writes under /tmp: caches and logs go there.
    if os.environ.get('VERCEL') and path.resolve().is_relative_to(_ROOT):
        path = Path('/tmp/football-lab') / path.resolve().relative_to(_ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


# The same club appears under different names across OpenFootball seasons.
# Without this the model splits one club's history into two "teams".
# Verified by disjoint seasons and identical football-data.co.uk identities.
TEAM_ALIASES = {
    'fr.1': {'AS Monaco': 'AS Monaco FC', 'Paris Saint-Germain': 'Paris Saint-Germain FC',
             'Stade Rennais': 'Stade Rennais FC 1901', 'RC Lens': 'Racing Club de Lens',
             'RC Strasbourg': 'RC Strasbourg Alsace', 'Olympique Marseille': 'Olympique de Marseille',
             'ESTAC Troyes': 'ES Troyes AC'},
}


def canonical_team(league_id, name):
    return TEAM_ALIASES.get(league_id, {}).get(name, name)


def canonicalize(matches):
    """Apply aliases in place; returns how many team fields changed."""
    changed = 0
    for m in matches:
        for side in ('home', 'away'):
            name = canonical_team(m['league_id'], m[side])
            changed += name != m[side]
            m[side] = name
    return changed


def valid_halftime(ht, ft):
    """Half-time scores are auxiliary: an implausible one is dropped, not trusted."""
    if (ft is None or not isinstance(ht, list) or len(ht) != 2 or
            not all(type(g) is int and 0 <= g for g in ht) or ht[0] > ft[0] or ht[1] > ft[1]):
        return None
    return ht


def normalize(raw, league_id, league_name, season):
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get('matches'), list) or not payload['matches']:
        raise ValueError('Missing or empty match list')
    rows, seen = [], set()
    for item in payload['matches']:
        date = dt.date.fromisoformat(item['date']).isoformat()
        home, away = item['team1'], item['team2']
        if not all(isinstance(t, str) and t.strip() for t in (home, away)) or home == away:
            raise ValueError('Invalid teams')
        home, away = canonical_team(league_id, home), canonical_team(league_id, away)
        key = (date, home, away)
        if key in seen:
            raise ValueError('Duplicate fixture')
        seen.add(key)
        score = item.get('score')
        ht = None
        if isinstance(score, dict):
            score, ht = score.get('ft'), score.get('ht')
        if score is not None and not (isinstance(score, list) and len(score) == 2 and
                                     all(type(g) is int and 0 <= g <= 30 for g in score)):
            raise ValueError('Invalid full-time score; source quarantined')
        rows.append(dict(date=date, home=home, away=away, goals=score, ht=valid_halftime(ht, score),
                         league_id=league_id, league=league_name, season=season))
    return rows


def normalize_openligadb(raw, league_id, league_name, season):
    """Normalize OpenLigaDB's match API while preserving missing scores as None."""
    payload = json.loads(raw)
    if not isinstance(payload, list) or not payload:
        raise ValueError('Missing or empty OpenLigaDB match list')
    rows, seen = [], set()
    for item in payload:
        date = dt.datetime.fromisoformat(item['matchDateTime']).date().isoformat()
        home, away = item['team1']['teamName'], item['team2']['teamName']
        if not all(isinstance(t, str) and t.strip() for t in (home, away)) or home == away:
            raise ValueError('Invalid OpenLigaDB teams')
        key = (date, home, away)
        if key in seen:
            raise ValueError('Duplicate OpenLigaDB fixture')
        seen.add(key)
        score = ht = None
        results = item.get('matchResults') or []
        final = [result for result in results if result.get('resultTypeKind') == 'After90Minutes']
        if final:
            result = max(final, key=lambda value: value.get('resultOrderID', 0))
            score = [result.get('pointsTeam1'), result.get('pointsTeam2')]
            if not all(type(goal) is int and 0 <= goal <= 30 for goal in score):
                raise ValueError('Invalid OpenLigaDB full-time score; source quarantined')
            half = [result for result in results if result.get('resultTypeKind') == 'HalfTime']
            if half:
                ht = valid_halftime([half[0].get('pointsTeam1'), half[0].get('pointsTeam2')], score)
        rows.append(dict(date=date, home=home, away=away, goals=score, ht=ht,
                         league_id=league_id, league=league_name, season=season))
    return rows


def coverage(data, league_id, asof):
    today = dt.date.fromisoformat(asof)
    rows = [m for m in data['matches'] if m['league_id'] == league_id]
    past = [m for m in rows if m['date'] < asof]
    completed = [m for m in past if m['goals'] is not None]
    year = today.year if today.month >= 7 else today.year - 1
    season = f'{year}-{str(year+1)[-2:]}'
    current = [m for m in rows if m['season'] == season]
    problems = []
    if not current:
        problems.append('Current-season fixtures missing')
    if not completed or (today - dt.date.fromisoformat(max(m['date'] for m in completed))).days > 30:
        problems.append('Completed results are missing or more than 30 days old')
    # Results can lag a few days; after two weeks with no score anywhere the game was
    # almost certainly postponed, which says nothing about the quality of the data.
    age = lambda m: (today - dt.date.fromisoformat(m['date'])).days
    unplayed = [m for m in current if m['date'] < asof and m['goals'] is None]
    missing = sum(2 < age(m) <= 14 for m in unplayed)
    postponed = sum(age(m) > 14 for m in unplayed)
    if missing:
        problems.append(f'{missing} recent current-season fixtures have no result yet')
    # OpenLigaDB addresses end in the start year (…/bl2/2026) rather than the season.
    sources = [s for s in data.get('sources', []) if s.get('league_id') == league_id and
               (f'/{season}/' in s['url'] or s['url'].rstrip('/').endswith(f'/{year}'))]
    checked = max((s.get('checked_at', '') for s in sources), default='')
    if not checked:
        problems.append('Current source freshness unverified')
    elif (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(checked)).total_seconds() > 48 * 3600:
        problems.append('Current source has not been verified within 48 hours')
    return dict(league_id=league_id, season=season, records=len(rows), completed=len(completed),
                upcoming=sum(m['date'] >= asof and m['goals'] is None for m in rows),
                latest_result=max((m['date'] for m in completed), default=None),
                current_records=len(current), unresolved_past=missing, likely_postponed=postponed, source_checked_at=checked or None,
                status='review_required' if problems else 'research_only', issues=problems)
