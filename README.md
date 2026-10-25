# Football Lab — zero-budget prototype

## Revision 2 audit (current behavior)

This is a deterministic research workflow with an optional JEV reviewer; no autonomous LLM orchestration or scheduler is active. See `PROJECT_STATUS.md` for current progress and setup. The old 'confidence' formula has been removed. Nothing here establishes production readiness or bookmaker advantage.

Refresh now re-fetches ALL known league-season files, validates them before replacing complete partitions, preserves failed partitions and stores per-source verification times and content-addressed raw snapshots. Invalid scores and duplicates are rejected. Source shrinkage over 10% is flagged for review. A fetch timestamp alone is not evidence that all sources are fresh.

The runner excludes same-day fixtures because kickoff times are unavailable. It records data review statuses, immutable run IDs and full input/code snapshots in `reports/`. No automatic recommendation ranking or artificial confidence number remains. The CLI uses a file lock against overlapping runs (macOS/Linux).

Run `python3 validate.py` for all-league evaluation, saved as `reports/validation.json`. Up to three completed seasons are evaluated with earlier dates only, using fixed parameters. Includes per-season log loss, Brier, accuracy, goal-total/BTTS Brier, calibration bins and paired date-block bootstrap intervals. It also fits a single temperature on earlier prequential predictions and evaluates it on the latest untouched season. This remains a diagnostic: the adjustment is not applied to live forecasts unless it shows reliable out-of-time improvement. Source corrections remain a hindsight limitation. Bootstrap intervals do not capture every temporal/team dependency or multiple comparisons.

Readiness gates flag missing current season, unverified source or source checked over 48h ago, results older than 30 days, unresolved past fixtures and thin recent team history. These are heuristic review thresholds, not learned confidence. Passing yields `research_only`, not approval for betting.

The dashboard now makes one prediction request and discards results from old selections. Handicap lines ±0.5/±1.5 are **half-goal** lines, not whole-goal lines. Expected goals are model means, not shot-based xG. Model version `poisson-attack-defence-dixon-coles-1.0` fits a regularized, time-weighted Poisson attack/defence model using a fixed 365-day half-life and L2 penalty; it is refit only on earlier results. A bounded, time-weighted Dixon–Coles low-score dependence parameter is fitted from the same earlier history. Probability calibration is not yet fitted.

## Dashboard and extended markets

The dashboard has three views. **Fixtures** forecasts every upcoming fixture in a league from one fit at today's cutoff (`/api/slate`), sortable by date, home/away probability, over 2.5 or BTTS. **Match** shows the full breakdown in tabs: overview (1X2, double chance, draw no bet, goals, first scorer, likely scores, odds comparison), goals (total ladder, exact totals, goal ranges, odd/even, team totals and exact goals), handicaps (Asian handicap and Asian totals in quarter steps with win/half/push settlement and fair odds), half-time (HT result, HT/FT grid, goals per half, highest-scoring half, scoring or winning in both halves), combos (result and BTTS, result and total, BTTS and total, winning margin) and a correct-score heatmap. **Performance** holds the forward tracker and backtest. Dark and light themes follow the system setting, with a toggle.

`markets.py` derives all extended markets from the same Dixon-Coles score grid as the 1X2 forecast, so combination markets keep the correlation between outcomes. Half-time markets add one fitted input: the time-weighted share of each side's goals scored before half-time, estimated only from earlier matches with half-time scores (at least 200 required). Halves are modelled as independent Poisson splits, so their full-time totals omit the low-score correction. None of the extended markets has been evaluated out of time yet.

Half-time scores are now kept during ingestion when present and consistent with the full-time score. `python3 app.py backfill-halftime` attaches them to existing data offline from the stored raw snapshots, accepting only snapshots whose full-time score matches.

## Model 2.0: exact ratings, calibration and better margin removal (October 2026)

`python3 tools/accuracy_lab.py` predicts every week of 2023-24 to 2026-27 in all eight leagues from fits on earlier results only. Settings are chosen on 2023-25 and scored once on 2025-27 (3,330 matches), so the holdout is not flattered by the search. Summary in `reports/accuracy_lab.json`; per-match records stay local (they contain football-data prices).

| 2025-27 holdout, 1X2 | Previous model | Model 2.0 |
|---|---|---|
| All 8 leagues: log loss | 0.9975 | **0.9873** |
| All 8 leagues: Brier | 0.5951 | 0.5888 |
| All 8 leagues: hit rate | 51.2% | 52.0% |
| 7 priced leagues: log loss | 1.0075 | 0.9968 |
| Saudi (no prices): log loss | 0.9239 | 0.9185 |

Every league improved, from Serie B (1.0425 to 1.0387) to La Liga (0.9788 to 0.9621). For reference, opening bookmaker prices score 0.9902 on the priced leagues, and the app still prices from them wherever they exist. The model is what you see for the rest.

What changed:

- **Solved exactly.** The old fit stopped after 50 Adam steps and pinned one club (alphabetically last) at the league average. That overstated goal levels by about 10% at short half-lives. Block Newton, with an exact centring step, now solves the same penalised likelihood to convergence in under ten rounds (about 0.04 s), and every club is free.
- **Retuned.** Ridge 0.025 → 0.005, market targets 75% → 90%, half-life 90 → 60 days. Leagues without prices use scorelines with a 365-day half-life and ridge 0.01 (`market_ratings.fit` decides per league).
- **Calibrated.** Temperature 0.91 and a draw shift of +0.12 apply to the model's own 1X2 (0.94 and +0.09 without prices). The whole score grid is rescaled per result, so every derived market stays consistent. Bookmaker-priced numbers are not touched.
- **Power margin removal** replaces proportional removal for all bookmaker prices. It was better by about 0.001 log loss on opening and closing prices, average and Pinnacle.
- **More history.** Serie B 2021-24 (1,140 matches) is filled from football-data in memory, using football-data's own names for clubs the open feed never had. The Saudi Pro League 2021-22 to date comes from TheSportsDB (`python3 app.py fetch-saudi`).

Tested and not adopted:

- A learned promoted/relegated-club prior (`model.newcomers`) gained at most 0.0002 on the tuning seasons and lost on the holdout in every round.
- Blending the model into opening prices got a fitted model weight of 0.
- Pinnacle beats the bookmaker average by only 0.0004.

## Market pricing (accuracy work, October 2026)

Benchmark (`reports/benchmark.json`, `python3 experiments.py`): over 6,153 matches in six leagues (2023-24 to 2025-26, weekly refits on earlier results only), the score model's 1X2 log loss was 1.0011 against 0.9768 for opening bookmaker odds and 0.9751 for closing odds. Tuning half-life, shrinkage and a shots-on-target signal moved it by at most 0.002. A model/market blend fitted on 2023-24 put zero weight on the model, so on unseen seasons the model added nothing to opening prices.

So `predict` now prices from the sharpest available source: odds you enter, then live odds (The Odds API, `ODDS_API_KEY` in `.env`), then football-data.co.uk prices, then the model. `implied.py` solves home/away goal rates from margin-free 1X2 and over/under 2.5 prices, and every market is derived from those rates. On the same matches, market-implied rates beat model rates on correct score, BTTS, over 3.5, winning margin, half-time result and HT/FT by 1.3 to 2.3% log loss. The model's own view stays visible for comparison.

`odds_data.py` imports football-data.co.uk results, odds and match statistics into `market_data.json`, separate from the CC0/ODbL results file. Their reuse terms are unverified: private research only, do not redistribute. Team names are mapped by fixture agreement; this exposed seven Ligue 1 clubs whose OpenFootball names changed between seasons, now unified by `TEAM_ALIASES` in `quality.py`. Corners, cards and shots-on-target team models did not beat league frequencies out of time, so those markets show league frequencies plus team averages.

```sh
python3 app.py refresh-odds   # football-data CSVs, plus live odds when ODDS_API_KEY is set
python3 experiments.py        # re-run the model variant benchmark
```

## Season simulator, bet builder and odds movement

**Season** (`/api/season`, `simulate.py`) plays out every remaining current-season fixture 5,000 times from the same goal rates the app shows (bookmaker-implied where prices exist). Each run shifts every team's strength at random (sd 0.10 on the log scale) so long-range uncertainty is not understated. It reports projected points with an 80% range, title, top-4 or promotion, play-off and relegation chances, and the full finishing-position distribution. Ties use points, goal difference and goals scored; head-to-head rules are not applied. Projections are only as current as the results data.

**Bet builder** prices same-match combinations on the full 0-10 score grid, so correlated legs (for example a home win with over 2.5) are priced correctly rather than multiplied. Combinations go to a slip that prices accumulators across matches (treated as independent) and compares any offered price with the fair price. The slip is stored in the browser only.

**Odds movement**: each live-odds refresh appends a snapshot to `reports/odds_history/`. Fixtures show the change in margin-free home probability since the first snapshot, flagged as sharp at 3 points or more, and the Odds tab draws the price path. Past fixtures show football-data opening-to-closing moves.

## Pitch view

Each match has a **Pitch** tab drawn to scale (105 x 68 m). Without extra data it shows the match picture from the app's own numbers: xG arrows sized by expected goals, the most likely score, and each side's recent shots-on-target and corner averages by the box they attack. With `API_FOOTBALL_KEY` in `.env` (free plan, about 100 requests a day) `lineups.py` adds formations, starting XIs in kit colours, benches, coaches, injuries, venue and referee. Confirmed lineups usually appear under an hour before kickoff; until then each team's last-used XI is shown, labelled as probable. Responses are cached and capped at 90 requests a day. This data is private and is not sent to the community league. On phones the pitch turns portrait with text kept upright.

## Typed research decisions

`decision.py` is a deterministic, auditable policy layer. Its only possible actions are `withhold` and `research_candidate`; it never issues a staking instruction or a confidence score. `review_required` data, missing odds, low probability, a small fair-market gap, or a low model expected return all force `withhold`. Every check and threshold is returned in the API response and dashboard.

## Forward forecast grading

Run `python3 agent.py --days 30` to freeze the first forecast for each upcoming fixture in `reports/prospective/`. The first forecast made with `research_only` data quality is separately frozen under `reports/prospective/eligible/`. Registration requires the run date to precede the fixture date because the source does not provide verified kickoff times. A later run updates `reports/prospective-grades.json` from available results; `python3 prospective.py grade` grades without generating new forecasts. The original forecasts are never overwritten. Grades may change after an upstream result correction, and a rescheduled fixture receives a different identity. No forward accuracy claim is available until enough matches are graded.

Historical evaluations now report plain Poisson alongside the Dixon–Coles correction for the same fitted goal rates and match dates. This ablation is diagnostic; it does not select a winner or tune parameters on evaluated seasons.

## Jev reviewer (optional)

When `TYPESAFE_API_KEY` is present in the process that starts the local server, `jev_reviewer.py` calls the native TypeSafe System One endpoint using the pinned `jev-1.13.0` model. It asks two bounded questions: whether the record needs human review (`noul`) and whether the evidence state is sufficient or needs review (`choice`). The dashboard records the returned model version and token usage.

The server and CLI runner load `TYPESAFE_API_KEY` from the local `.env` at startup, without overriding an existing process environment variable. The file is plaintext, owner-only and Git-ignored, not an encrypted vault. Keys are never sent to the browser or added to reports. JEV is advisory only. Set a rotated key in `.env` locally and restart. Alternatively supply it through your process environment:

```sh
python3 app.py serve
```

The app includes a conservative in-process JEV circuit breaker: 60 calls/minute and four calls/second, far below the provider's published ceiling. It returns `throttled` rather than retrying a user request. This is an interactive single-process guard, not a distributed production quota system.

The notes below describe the initial prototype where not superseded by this revision. See `AUDIT.md` for remaining acceptance criteria.

Local research app covering Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Serie B and 2. Bundesliga. Python 3.10+; no packages, keys, paid APIs or accounts required.

Run these commands from this folder:

```sh
python3 app.py refresh
python3 app.py serve
```

Open http://127.0.0.1:8765. The bundled data snapshot also allows offline use: skip refresh.
The data snapshot records a license and source for each imported partition. The 2. Bundesliga feed comes from OpenLigaDB and is under ODbL-1.0; attribution and share-alike terms apply if redistributing its database or derivatives. Other OpenFootball partitions remain CC0. Do not treat the combined snapshot as entirely CC0.
Select two teams, set an analysis date, and optionally enter all three SportyBet decimal match-result odds. The prediction response includes totals, team-goal totals, clean sheets, win-to-nil and half-goal handicap covers. Use today's date when forecasting an upcoming match. Results from the analysis date itself are excluded. Enter a new set of odds for each match; odds are not persisted.

```sh
python3 -m unittest -v
python3 app.py backtest
python3 agent.py --days 7
```

## Optional shots and red-card data

The bundled goal source does not contain those fields, so the dashboard withholds those market estimates by default. It will not scrape a bookmaker or re-label another site's data. To add data you are permitted to use, copy [stats-template.csv](stats-template.csv), preserve the exact league/team/date values from the app, give every row a meaningful `source` label, and run:

```sh
python3 app.py import-stats your-stats.csv
```

Every row must exactly match a completed fixture in the goal dataset; malformed, implausible or unmatched rows are rejected. Shot markets need at least 200 validated records before the forecast date; red-card markets need 300. These are independent Poisson count estimates and remain research-only until chronologically evaluated.

## Data and provenance

Source: https://github.com/openfootball/football.json, CC0-1.0 (LICENSE.md in source repository).
Refresh fetches all seven league JSON feeds for 2021/22 through the current calendar year's starting season. It records source URLs, retrieval time, response SHA-256 hashes and failures in data.json. It retries temporary download failures and preserves already downloaded records if a source becomes unavailable. Raw match times are omitted because timezone semantics have not been verified. Future-dated scores never enter today's model.

Coverage: dates, team names, full-time goals, fixtures. No promised completeness or independent verification of results. Optional manually imported sources can add total shots and red cards after exact fixture validation. Injuries, lineups and shot-based xG are not implemented.

## Model

Poisson goals with a fitted league baseline, home advantage, team attack and team defence. Observations have a 365-day half-life. A pre-specified L2 penalty shrinks team effects toward zero (the league baseline), which is particularly important for promoted teams and thin histories. The deterministic optimizer uses no third-party package. A bounded, time-weighted Dixon–Coles correction adjusts the four low score cells (0–0, 0–1, 1–0, 1–1) and is re-estimated only from prior results. Expected goals are clipped to 0.05–6, and score probabilities use 0–25 goals with normalization. The parameters are fit to past match scores, but the modelling choices are not tuned or proven. It does not account for tactical shifts, player availability or lineup changes.

Fair decimal odds = 1 / model probability. Market implied probabilities = (1 / decimal odds), normalized across all three outcomes to remove margin proportionally. Gap = model probability minus normalized market probability. Expected return = model probability × offered decimal odds − 1. A positive result is conditional on the uncalibrated model, not an established edge.

Backtest: up to three recent completed seasons with at least 300 earlier matches, expanding history by date. The exact forecast model is refit once per match date; predictions exclude same-day/later results. Compares log loss, multiclass Brier (sum across three outcomes) and accuracy with expanding league frequencies. This is a research comparison, not a bookmaker-profit backtest. Source corrections available today may differ from what was known historically; strict time cutoffs cannot resolve that provenance limitation. No calibration claim is made.

## Build status

- Implemented: seven league selector, refresh, cached data, goal probabilities, manual odds comparison, per-league chronological evaluation, local dashboard, and `agent.py`.
- `agent.py` is a runnable local agent: it scans supplied upcoming fixtures and writes `reports/latest.json` and `reports/latest.md`. Add `--refresh` when it should fetch missing public source files before analysis.
- Not implemented: automated odds collection, weekly scheduling, fully verified multi-league coverage or advanced statistics.
- JEV is connected as an optional typed evidence reviewer. It does not set match probabilities or override the deterministic research policy; its added value has not been evaluated.
- SportyBet browser access worked in initial inspection, but direct homepage/fixture requests returned 403. No automated collector is bundled.
- Football-Data.co.uk was inspected but not imported: its current page explicitly restricts automated/AI data-training use. Source: https://football-data.co.uk/data.php.

Next priorities: validate result coverage against a second source; evaluate calibration over multiple chronological seasons; find open shot/card data; verify official Jev documentation and free access. Add other leagues only after checking their histories and missingness.
