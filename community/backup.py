"""Export the league's tables to JSON (for the daily job's backup artifact).

    python3 community/backup.py backup        # writes backup/<table>.json

Uses SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. Pages through each table so
large tables are exported completely.
"""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

# Each table with a stable sort order, so paging never skips or repeats rows.
TABLES = {'profiles': 'id', 'fixtures': 'id', 'predictions': 'user_id,fixture_id',
          'groups': 'id', 'group_members': 'group_id,user_id'}
PAGE = 1000


def export(url, key, table, order, fetch=None):
    rows, start = [], 0
    while True:
        request = Request(f"{url.rstrip('/')}/rest/v1/{table}?select=*&order={order}",
                          headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Range-Unit': 'items',
                                   'Range': f'{start}-{start + PAGE - 1}'})
        page = fetch(request) if fetch else json.loads(urlopen(request, timeout=60).read())
        rows += page
        if len(page) < PAGE:
            return rows
        start += PAGE


def main():
    if sys.argv[1:] != ['backup']:
        raise SystemExit('usage: python3 community/backup.py backup')
    url, key = os.environ.get('SUPABASE_URL', '').strip(), os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url or not key:
        raise SystemExit('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.')
    out = Path('backup')
    out.mkdir(exist_ok=True)
    for table, order in TABLES.items():
        rows = export(url, key, table, order)
        (out / f'{table}.json').write_text(json.dumps(rows))
        print(table, len(rows))


if __name__ == '__main__':
    main()
