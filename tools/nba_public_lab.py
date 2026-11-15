"""Walk-forward check of the hosted site's NBA model (scores only, balldontlie data).

Every game day is predicted from earlier games only, with PUBLIC_SETTINGS. The widths
(PUBLIC_WIDTH: margin stretch, margin and total spread) are searched on 2024-25 and
reported once on 2025-26 and on the season in progress. No bookmaker line is used
anywhere: spreads and totals are graded around the model's own main lines, plus
alternate lines either side, so they test the shape of the distribution.

    python3 tools/nba_public_lab.py           # search widths, then report
    python3 tools/nba_public_lab.py --check   # current PUBLIC_WIDTH only
"""
import datetime as dt
import itertools
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import nba_model as M  # noqa: E402
import nba_public  # noqa: E402
from nba_calib import picks, score  # noqa: E402
from nba_lab import predict_seasons, rmse  # noqa: E402
from quality import atomic_write  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TUNE, HOLD = (2025,), (2026,)
_RECS = []


def records():
    games = nba_public.load()['games']
    rest = M.back_to_back([g for g in games if g['status'] != 'postponed'])
    seasons = sorted({g['season'] for g in games})
    recs = predict_seasons(games, [s for s in seasons if s >= min(TUNE)], M.PUBLIC_SETTINGS, rest)
    for r in recs:
        e = r['model'][0] - r['model'][1]
        t = sum(r['model']) + M._ot_points(*r['model'])
        # The model's own main lines stand in for a bookmaker's: half-point lines, no pushes.
        r['line'] = dict(close=dict(spread=-(math.floor(e) + .5), total=math.floor(t) + .5))
    return recs


def _grade(args):
    width, seasons = args
    rows = []
    for r in _RECS:
        if r['season'] in seasons:
            rows += picks(r, width, 'model')
    return score(rows)


def _init(recs):
    global _RECS
    _RECS = recs


def points(recs):
    if not recs:
        return None
    win = sum((r['final'][0] > r['final'][1]) == (r['model'][0] > r['model'][1]) for r in recs) / len(recs)
    return dict(games=len(recs), winner_accuracy=win,
                margin_rmse=rmse([r['final'][0] - r['final'][1] - (r['model'][0] - r['model'][1]) for r in recs]),
                total_rmse=rmse([sum(r['final']) - sum(r['model']) - M._ot_points(*r['model']) for r in recs]))


def main():
    recs = records()
    check = '--check' in sys.argv
    current = tuple(s for s in sorted({r['season'] for r in recs}) if s > max(HOLD))
    best = dict(M.PUBLIC_WIDTH)
    search = []
    with Pool(initializer=_init, initargs=(recs,)) as pool:
        if not check:
            grid = [dict(best, stretch=s, margin=m, total=t) for s, m, t in
                    itertools.product((1.0, 1.1, 1.2, 1.3), (14.2, 15.2, 16.2, 17.2), (18.5, 19.5, 21.5))]
            scores = pool.map(_grade, [(w, TUNE) for w in grid])
            loss = [sum(s[f]['log_loss'] for f in ('moneyline', 'spread', 'total', 'team_total', 'combo') if f in s) for s in scores]
            search = sorted(({**w, 'loss': round(x, 5)} for w, x in zip(grid, loss)), key=lambda x: x['loss'])[:8]
            best = {k: v for k, v in search[0].items() if k != 'loss'}
            print('chosen', best, flush=True)
        out = dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), settings=M.PUBLIC_SETTINGS, width=best, search=search,
                   method=__doc__.strip().split('\n\n')[0])
        for name, seasons in (('tuning', TUNE), ('holdout', HOLD), ('current_season', current)):
            sub = [r for r in recs if r['season'] in seasons]
            out[name] = dict(seasons=list(seasons), points=points(sub), markets=pool.apply(_grade, ((best, seasons),)) if sub else None)
            p, m = out[name]['points'], out[name]['markets'] or {}
            if p:
                print(name, {k: round(v, 3) for k, v in p.items()}, {f: (m[f]['log_loss'], m[f]['sure_70_plus']) for f in m}, flush=True)
    atomic_write(ROOT / 'reports' / 'nba_public_lab.json', json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
