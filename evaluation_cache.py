"""Disposable, integrity-checked evaluation cache; no network or credentials."""
import datetime as dt
import hashlib
import json
import threading
from pathlib import Path
from quality import atomic_write, digest

ROOT = Path(__file__).resolve().parent
_LOCK = threading.Lock()


def cached_evaluate(data, league_id, compute, directory=None, day=None, revision=None):
    directory = Path(directory) if directory is not None else ROOT / 'reports' / 'cache'
    if revision is None:
        revision = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in ('app.py', 'model.py', 'evaluation.py', 'quality.py', 'evaluation_cache.py')}
    key = digest(dict(schema=1, data=data, league=league_id,
                      day=day or dt.date.today().isoformat(), revision=revision))
    # One file per league bounds storage; the digest remains the authority.
    path = directory / (digest(league_id) + '.json')
    # Serialize expensive evaluations in this server process, including cache misses.
    with _LOCK:
        try:
            entry = json.loads(path.read_text())
            if (entry['key'] == key and isinstance(entry['result'], dict)
                    and entry['checksum'] == digest(entry['result'])):
                return entry['result']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = compute(data, league_id)
        entry = dict(key=key, result=result, checksum=digest(result))
        try:
            atomic_write(path, json.dumps(entry, allow_nan=False))
        except OSError:
            # A read-only/full cache must not prevent a valid evaluation.
            pass
        return result
