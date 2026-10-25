"""Real club badges for the private Lab, from TheSportsDB's free API.

Club badges are trademarks: they are cached locally (reports/badges/, git-ignored)
and shown only in the Lab, never in the public community site, which keeps the
kit-colour crests. Fetch once with:

    python3 app.py fetch-badges

The free key allows about 30 requests a minute, so lookups are paced. Each match
is recorded with TheSportsDB's team name so a wrong pairing is easy to spot.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from quality import atomic_write
from live_odds import similarity

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'reports' / 'badges'
INDEX = DIR / 'index.json'
API = 'https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t='
COUNTRY = {'en.1': 'England', 'es.1': 'Spain', 'it.1': 'Italy', 'de.1': 'Germany', 'fr.1': 'France', 'it.2': 'Italy', 'de.2': 'Germany'}
# Names TheSportsDB knows differently from our dataset.
ALIASES = {'FC Internazionale Milano': 'Inter Milan', 'FC Bayern München': 'Bayern Munich', 'Club Atlético de Madrid': 'Atletico Madrid',
           'Paris Saint-Germain FC': 'Paris SG', 'Borussia Mönchengladbach': 'Monchengladbach', 'RCD Espanyol de Barcelona': 'Espanyol',
           'Real Betis Balompié': 'Real Betis', 'Rayo Vallecano de Madrid': 'Rayo Vallecano', 'Olympique Lyonnais': 'Lyon',
           'Olympique de Marseille': 'Marseille', 'Stade Rennais FC 1901': 'Rennes', 'Racing Club de Lens': 'Lens',
           'RC Strasbourg Alsace': 'Strasbourg', 'Brighton & Hove Albion FC': 'Brighton', 'Wolverhampton Wanderers FC': 'Wolves',
           'Athletic Club': 'Athletic Bilbao', 'Hamburger SV': 'Hamburg', 'RB Leipzig': 'RB Leipzig', 'SSC Napoli': 'Napoli', 'AS Monaco FC': 'Monaco', '1. FSV Mainz 05': 'Mainz', 'Brighton & Hove Albion FC': 'Brighton', 'Nottingham Forest FC': 'Nottingham Forest',
           'DSC Arminia Bielefeld': 'Arminia Bielefeld', 'Real Sociedad de Fútbol': 'Real Sociedad',
           'Angers SCO': 'Angers', 'Paris Saint-Germain FC': 'Paris SG', 'AC Milan': 'AC Milan', 'ACF Fiorentina': 'Fiorentina',
           'Mantova 1911 SSD': 'Mantova', 'Verona': 'Hellas Verona'}
# Clubs the free name search cannot find (it returns one team: a women's or netball side).
TEAM_IDS = {'Brighton & Hove Albion FC': '133619', 'Nottingham Forest FC': '133720', 'Paris Saint-Germain FC': '133714'}
LOOKUP = 'https://www.thesportsdb.com/api/v1/json/123/lookupteam.php?id='
NOISE = r'\b(FC|CF|AFC|SC|AC|SSC|AS|RC|OGC|VfB|VfL|TSG|FSV|SV|US|UD|CD|RCD|SD|Calcio|Club|de|1\.|\d{4})\b'


def query_for(name):
    if name in ALIASES:
        return ALIASES[name]
    cleaned = re.sub(r'^1\.\s*', '', name)             # "1. FC Köln" -> "FC Köln"
    return re.sub(r'\s+', ' ', re.sub(NOISE, ' ', cleaned)).strip() or name


def load_index():
    try:
        return json.loads(INDEX.read_text())
    except (OSError, ValueError):
        return {}


def _get(url, timeout=20):
    with urlopen(Request(url, headers={'User-Agent': 'football-lab (private use)'}), timeout=timeout) as r:
        return r.read()


def _lookup(query, log, waits=(65, 130)):
    """Search TheSportsDB, backing off when the free key's rate limit is hit."""
    for wait in waits + (None,):
        try:
            return json.loads(_get(API + quote(query))).get('teams')
        except HTTPError as exc:
            if exc.code != 429 or wait is None:
                raise
            log(f'rate limited, waiting {wait}s'); time.sleep(wait)


def best_match(name, league_id, teams):
    country = COUNTRY.get(league_id)
    scored = []
    for t in teams or []:
        if t.get('strSport') != 'Soccer' or not t.get('strBadge'):
            continue
        names = [t.get('strTeam') or ''] + [a.strip() for a in (t.get('strTeamAlternate') or '').split(',') if a.strip()]
        sim = max(max(similarity(name, n), similarity(query_for(name), n)) for n in names)
        if country and t.get('strCountry') == country:
            sim += 0.15
        if t.get('strGender') and t['strGender'] != 'Male':
            sim -= 0.5
        if re.search(r'\b(B|C|II|U\d\d|Reserves?|Youth|Women|Femenino|Feminile|Frauen)\b$', t.get('strTeam') or ''):
            sim -= 0.5                      # reserve, youth and women's sides share the club name
        scored.append((sim, t))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] >= 0.75 else None


def fetch(teams, pause=3, log=print):
    """teams: iterable of (league_id, name). Skips clubs already cached."""
    DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()
    # Saudi fixtures already carry each club's badge link from TheSportsDB.
    import saudi
    known = {}
    for m in saudi.load().get('matches', []):
        for name, url in zip((m['home'], m['away']), m.get('badges') or ()):
            if url:
                known[name] = url
    todo = [(lg, n) for lg, n in teams if n not in index or index[n].get('missing')]   # retry misses
    for lg, n in [t for t in todo if t[1] in known]:
        try:
            file = hashlib.sha1(n.encode()).hexdigest()[:12] + '.png'
            (DIR / file).write_bytes(_get(known[n] + '/small'))
            index[n] = {'file': file, 'matched': n, 'source': known[n]}
            todo.remove((lg, n))
        except Exception as exc:
            log(f'{n}: badge download failed ({exc})')
    atomic_write(INDEX, json.dumps(index, indent=1, ensure_ascii=False))
    for i, (league_id, name) in enumerate(todo, 1):
        try:
            found = (json.loads(_get(LOOKUP + TEAM_IDS[name])).get('teams') if name in TEAM_IDS
                     else _lookup(query_for(name), log))
        except Exception as exc:
            log(f'{i}/{len(todo)} {name}: lookup failed ({exc})'); time.sleep(pause); continue
        team = found[0] if name in TEAM_IDS and found else best_match(name, league_id, found)
        if not team:
            index[name] = {'missing': True, 'query': query_for(name)}
            log(f'{i}/{len(todo)} {name}: no confident match')
        else:
            url = team['strBadge'] + '/small'
            file = hashlib.sha1(name.encode()).hexdigest()[:12] + '.png'
            try:
                (DIR / file).write_bytes(_get(url))
                index[name] = {'file': file, 'matched': team['strTeam'], 'source': url}
                log(f'{i}/{len(todo)} {name} -> {team["strTeam"]}')
            except Exception as exc:
                log(f'{i}/{len(todo)} {name}: download failed ({exc})')
        atomic_write(INDEX, json.dumps(index, indent=1, ensure_ascii=False))
        time.sleep(pause)
    return index


def urls():
    """Badge URLs the Lab can show: {dataset team name: '/badge/<file>'}."""
    return {n: '/badge/' + v['file'] for n, v in load_index().items() if v.get('file') and (DIR / v['file']).exists()}
