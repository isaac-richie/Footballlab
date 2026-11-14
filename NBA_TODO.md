# Basketball (NBA): not finished yet

Status as of 14 November 2026. What works is described in the README, under "Basketball (NBA)". This file lists what is still open.

## In progress

- **Model-only calibration.** Games with no bookmaker line yet are priced from team ratings alone, with `MODEL_WIDTH` still at its first guesses (`stretch` 1.0). On 2025-26 the ratings were under-confident on favourites: picks they called 84% won 89%. `python3 tools/nba_calib.py --only model` is tuning a margin stretch plus the margin, total, link and slope widths on 2023-25. The chosen values still need to go into `nba_model.py`, then a hold-out check on 2025-26.

## Known accuracy gaps

- **Line-priced spreads and moneyline run slightly over-confident** on 2025-26 (70%+ picks: spreads said 75.8%, won 74.2%; moneyline said 81.6%, won 79.8%). Totals and combos are on target. Margin width 12.5 was kept as the cautious choice; a margin sd that varies by season or by team might close the rest.
- **The model alone is weaker than the closing line**: margin RMS error 14.6 against 14.1, total 19.0 against 18.2. The app prices from the line whenever one exists. Nothing yet beats the line.
- **No injury, lineup or rest information** beyond back-to-backs. Star absences move NBA lines a lot, and the ratings only see them through results.
- **Playoffs are not modelled separately** (slower pace, shorter rotations). They are fitted together with regular-season games.

## Not built

- **Hosted site**: ESPN data has no published reuse terms, so `nba_data.json` is not committed or deployed. The hosted Lab shows "Basketball forecasts are not available here yet". Basketball works on the local Lab only.
- **VIP picks and the public record** stay football-only until NBA picks build a forward record.
- **No forward (prospective) ledger** for NBA forecasts yet, so all accuracy so far is backtested.
- **Bet slip and bet builder** do not take NBA picks.
- **Half and quarter markets** (1st-half spread and total, quarter winners): quarter scores are stored, but no model uses them yet.
- **Only one sportsbook** (ESPN BET via ESPN). The Odds API path used for football (several books, best price) is not wired for NBA (`basketball_nba`).
- **Line history**: lines are back-filled from 2023-24 onward, not for 2021-22 and 2022-23.
- **Results ticker** is hidden in basketball mode.
- **Other leagues**: WNBA, EuroLeague and NCAA are not covered.
- **First load**: the board takes about 4 to 5 seconds to price before it is cached (warmed when the server starts).
- **PROJECT_STATUS.md** has not been updated for basketball.
