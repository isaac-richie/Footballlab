# Basketball (NBA): not finished yet

Status as of 19 November 2026. What works is described in the README, under "Basketball (NBA)". This file lists what is still open.

## Known accuracy gaps

- **Where the model-only spread misses sit (checked 19 November 2026).** Split by days into the season, 70%+ model-only spread picks were on target early in past seasons (first 30 days: 2023-25 -1.1 points, 2025-26 +0.9) and over-confident late (after day 60: -2.4 and -4.8), when rest, injuries and tanking make games noisier. 2026-27's -7.0 (371 picks, first 30 days) is about three standard errors and was not tuned on. Widening model-only widths after day 60 (x1.05 to x1.2, chosen on 2023-25) cost summed log loss in every case, barely moved the 2025-26 spreads (-4.8 to -4.3 at x1.1) and made moneyline and team totals more cautious, so it was not adopted. The fix needs lineup and injury information, or a posted line.
- **Model-only spreads still run a little over-confident** (games with no line posted yet). On 18 November 2026 the model-only widths were widened from margin 14.2 / total 21.5 to 15.2 / 24.5, chosen on 2023-25 alone (`MODEL_WIDTH` in `nba_model.py` says how). On the 2025-26 hold-out, 70%+ picks now say/win: totals 73.5%/70.8% (was 74.4%/70.2%, now validated), spreads 75.5%/72.3% (was 76.0%/71.9%, still just outside the 3-point bar), combos 75.8%/73.9%. The cost is on the cautious side: moneyline 79.6%/82.0% and team totals 71.7%/75.6% (now under-confident, so team totals show the not-validated note). Summed hold-out log loss is unchanged within 0.03%. 2026-27 to date (371 spread picks) still shows spreads about 7 points over. Width alone cannot fix it: the confident misses come from games where the model's expected margin is off, which needs lineup and injury information or a posted line.
- **The model alone is weaker than the closing line**: margin RMS error 14.4 against 14.1 on 2025-26, total 18.9 against 18.2. It is about 49% against the spread and total, so it does not beat the line. The app prices from the line whenever one exists.
- **Line-priced picks are on target** on 2025-26 and 2026-27 to date (70%+ spreads said 75.5%, won 75.4%).
- **No injury, lineup or rest information** beyond back-to-backs, except what past closing lines carry into the ratings.
- **Playoffs are not modelled separately.**

## Built, collecting

- **Forward ledger** (`nba_ledger.py`): every board game is frozen before tip-off (first forecast and last before tip-off) and graded on the final score. Started 15 November 2026 with 60 games. Needs a few hundred graded games before its numbers mean much. It runs only while the local Lab is open or `python3 app.py fetch-nba` runs, and stays private (git-ignored) because it holds line-derived prices.

- **Hosted site** (15 November 2026): runs on balldontlie scores and schedule (`nba_public.py`, `nba_public.json`, committed), priced by the scores-only model (`PUBLIC_SETTINGS`, `PUBLIC_WIDTH`). Checked walk-forward on 2025-26: winner 68.3%, 70%+ winner picks said 78.4% won 80.7%, spreads 73.5%/74.4%, totals 73.6%/73.7% (`tools/nba_public_lab.py`). The daily GitHub job refreshes it, prices the board ahead of time (`reports/nba_public_board.json`, so the site opens without the 4 to 5 second pricing wait) and freezes the public forward record before the US evening games. Needs the `BALLDONTLIE_API_KEY` repository secret. balldontlie's reuse terms are not yet confirmed in writing.

- **Public forward record** (`reports/nba_public_prospective-grades.json`): moneyline, spread and main-line total, first and last forecast. On 17 November: 17 graded, 56 pending. Moneyline said 70.5% and won 76.5% on those 17, far too few to judge.

## Built 15-19 November 2026

- **Picks page, over/under first** (19 November). The page opens on Over / Under: each game's over or under nearest the main total that is at least 70% likely, on the model's own line (`total_pick` in `nba_app.py`). The To win tab lists only a few strong calls: 72% and up, at most five (`picks(floor=.72, most=5)`). Winner picks before 19 November used a 60% bar.
- **Saved picks and Results** (`nba_picks_ledger.py`, `reports/nba_public_picks/`, committed). The daily job saves every pick on the page before tip-off (one file per game, never rewritten after tip-off) and the Results tab and the Record page mark each won or lost from the final scores, using the live feed for yesterday's games before the next morning's update. Only the latest finished day is listed; the running totals cover every day. 15-18 November were rebuilt from the forward ledger's frozen forecasts with the same rules and are marked rebuilt. Record on 19 November: over/under 25-9 (overs 8-5, unders 17-4), winners 16-9.
- **VIP slip**: the three strongest over/under calls of the next game day, plus the one or two surest winners (80%+) from other games, with the joint chance and an "Add all to slip" button. The football VIP ticket also carries the NBA picks (`nba_vip.py`).
- **Live scores** (`nba_live.py`): balldontlie's games list, cached a minute in the process and at the CDN, so about one request a minute however many people watch.
- **Fast first load**: the daily job prices the board (`reports/nba_public_board.json`), so the hosted site opens in about a second.
- **Bet slip**: picks, the VIP slip and any cell of the Match page's combo grid can be added to the shared slip. **Results ticker** of recent finals in basketball mode. Hardwood court background and TheSportsDB team logos on the hosted site.

## Not built

- **Injuries and who played.** The biggest accuracy gap. balldontlie ALL-STAR ($9.99 a month) has player injuries and per-game player stats; the plan is to test a who-played adjustment on 2025-26 before switching anything on.
- **Spreads are not offered as picks** (shown on the match page only), and team totals and combos have no saved record.
- **Bet builder** (pick your own legs) is football-only. NBA same-game combos come only from the fixed combo grid.
- **Half and quarter markets** (1st-half spread and total, quarter winners): quarter scores are stored, but no model uses them yet.
- **Only one sportsbook** (ESPN BET via ESPN) on the local Lab; the hosted site shows no odds by design.
- **Line history**: lines are back-filled from 2023-24 onward, not for 2021-22 and 2022-23.
- **Other leagues**: WNBA, EuroLeague and NCAA are not covered.
- **Local Lab first load** still prices the board on start (about 4 to 5 seconds). Only the hosted site reads the pre-priced board.
