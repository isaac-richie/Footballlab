# Basketball (NBA): not finished yet

Status as of 18 November 2026. What works is described in the README, under "Basketball (NBA)". This file lists what is still open.

## Known accuracy gaps

- **Model-only spreads still run a little over-confident** (games with no line posted yet). On 18 November 2026 the model-only widths were widened from margin 14.2 / total 21.5 to 15.2 / 24.5, chosen on 2023-25 alone (`MODEL_WIDTH` in `nba_model.py` says how). On the 2025-26 hold-out, 70%+ picks now say/win: totals 73.5%/70.8% (was 74.4%/70.2%, now validated), spreads 75.5%/72.3% (was 76.0%/71.9%, still just outside the 3-point bar), combos 75.8%/73.9%. The cost is on the cautious side: moneyline 79.6%/82.0% and team totals 71.7%/75.6% (now under-confident, so team totals show the not-validated note). Summed hold-out log loss is unchanged within 0.03%. 2026-27 to date (371 spread picks) still shows spreads about 7 points over. Width alone cannot fix it: the confident misses come from games where the model's expected margin is off, which needs lineup and injury information or a posted line.
- **The model alone is weaker than the closing line**: margin RMS error 14.4 against 14.1 on 2025-26, total 18.9 against 18.2. It is about 49% against the spread and total, so it does not beat the line. The app prices from the line whenever one exists.
- **Line-priced picks are on target** on 2025-26 and 2026-27 to date (70%+ spreads said 75.5%, won 75.4%).
- **No injury, lineup or rest information** beyond back-to-backs, except what past closing lines carry into the ratings.
- **Playoffs are not modelled separately.**

## Built, collecting

- **Forward ledger** (`nba_ledger.py`): every board game is frozen before tip-off (first forecast and last before tip-off) and graded on the final score. Started 15 November 2026 with 60 games. Needs a few hundred graded games before its numbers mean much. It runs only while the local Lab is open or `python3 app.py fetch-nba` runs, and stays private (git-ignored) because it holds line-derived prices.

- **Hosted site** (15 November 2026): runs on balldontlie scores and schedule (`nba_public.py`, `nba_public.json`, committed), priced by the scores-only model (`PUBLIC_SETTINGS`, `PUBLIC_WIDTH`). Checked walk-forward on 2025-26: winner 68.3%, 70%+ winner picks said 78.4% won 80.7%, spreads 73.5%/74.4%, totals 73.6%/73.7% (`tools/nba_public_lab.py`). The daily GitHub job refreshes it, prices the board ahead of time (`reports/nba_public_board.json`, so the site opens without the 4 to 5 second pricing wait) and freezes the public forward record before the US evening games. Needs the `BALLDONTLIE_API_KEY` repository secret. balldontlie's reuse terms are not yet confirmed in writing.

- **Public forward record** (`reports/nba_public_prospective-grades.json`): moneyline, spread and main-line total, first and last forecast. On 17 November: 17 graded, 56 pending. Moneyline said 70.5% and won 76.5% on those 17, far too few to judge.

## Built 15 November 2026

- **Total-points picks**: a "Total points" tab next to Winners on the picks page. Each game gets the over or under nearest the main total that is at least 70% likely, on the model's own line (`total_pick` in `nba_app.py`). Shown only where totals passed validation.
- **VIP slip**: the three strongest winner picks, with their joint chance and true odds, and an "Add all to slip" button. The legs are treated as independent games.
- **Bet slip**: winner picks, total-points picks, the VIP slip and any cell of the Match page's combo grid can be added to the shared slip.
- **Results ticker**: an NBA ticker of recent final scores replaces the football one in basketball mode.

## Not built

- **Total-points picks and the VIP slip have no forward record.** The ledger grades the main-line total, not the picks' own lines, and nothing freezes the daily VIP three. The picks page shows the walk-forward record for each confidence band instead.
- **VIP record and the public record page** (`record.py`) stay football-only.
- **Bet builder** (pick your own legs) is football-only. NBA same-game combos come only from the fixed combo grid.
- **Half and quarter markets** (1st-half spread and total, quarter winners): quarter scores are stored, but no model uses them yet.
- **Only one sportsbook** (ESPN BET via ESPN). The Odds API path used for football (several books, best price) is not wired for NBA (`basketball_nba`).
- **Line history**: lines are back-filled from 2023-24 onward, not for 2021-22 and 2022-23.
- **Other leagues**: WNBA, EuroLeague and NCAA are not covered.
- **Local Lab first load** still prices the board on start (about 4 to 5 seconds, warmed when the server starts). Only the hosted site reads the pre-priced board.
