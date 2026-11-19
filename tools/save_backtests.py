"""Save each league's backtest summary for the hosted site (run by the daily job).

The hosted server has a read-only disk, so it cannot cache /api/backtest and recomputed
it on every click (about a minute, at Vercel's limit). This writes the same result,
without the per-match predictions the page never shows, to reports/backtest/<league>.json.

    python3 tools/save_backtests.py
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from quality import atomic_write  # noqa: E402

OUT = ROOT / 'reports' / 'backtest'


def one(league_id):
    from evaluation import evaluate
    try:
        result = evaluate(app.load(), league_id)
    except ValueError as exc:
        return league_id, str(exc)
    result.pop('predictions', None)
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write(OUT / f'{league_id}.json', json.dumps(result, allow_nan=False))
    return league_id, 'ok'


if __name__ == '__main__':
    with Pool() as pool:
        for league_id, status in pool.map(one, list(app.LEAGUES)):
            print(league_id, status, flush=True)
