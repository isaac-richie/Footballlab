# Basketball (NBA): not finished yet

Status as of 15 November 2026. What works is described in the README, under "Basketball (NBA)". This file lists what is still open.

## Known accuracy gaps

- **Model-only spreads and totals run over-confident** (games with no line posted yet). On 2025-26, 70%+ picks said 76% and won 72% on spreads, 74%/70% on totals. Moneyline (80%/82%) and team totals are on target. Widths were tuned on 2023-25 for the line-informed ratings (stretch 1.15, margin 14.2, total 21.5).
- **The model alone is weaker than the closing line**: margin RMS error 14.4 against 14.1 on 2025-26, total 18.9 against 18.2. It is about 49% against the spread and total, so it does not beat the line. The app prices from the line whenever one exists.
- **Line-priced picks are on target** on 2025-26 and 2026-27 to date (70%+ spreads said 75.5%, won 75.4%).
- **No injury, lineup or rest information** beyond back-to-backs, except what past closing lines carry into the ratings.
- **Playoffs are not modelled separately.**

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
