"""Load allowlisted local credentials without shell execution or interpolation."""
import os
from pathlib import Path

ALLOWED = ('TYPESAFE_API_KEY', 'ODDS_API_KEY', 'API_FOOTBALL_KEY', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY')


def load_environment(path=None):
    path = Path(path) if path is not None else Path(__file__).resolve().parent / '.env'
    if not path.exists():
        return
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if not separator or name.strip() not in ALLOWED:
            raise ValueError(f'Unsupported environment entry at line {number}; allowed names: {", ".join(ALLOWED)}.')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed environment quote at line {number}.')
            value = value[1:-1]
        os.environ.setdefault(name.strip(), value)
