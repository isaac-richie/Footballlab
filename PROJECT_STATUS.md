# Football Lab — project and progress

Updated: 19 November 2026 (earlier sections kept as written).

## What we are building

A solo, zero-budget football probability research system: historical data ingestion, statistical forecasts, auditable decisions, optional TypeSafe JEV evidence review and a local dashboard. Mathematics expresses uncertainty; it does not establish guaranteed outcomes or bookmaker advantage.

Target leagues: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Serie B and 2. Bundesliga. Availability and freshness must be checked per league; listing a league is not proof of complete coverage.

## Implemented

- OpenFootball results ingestion plus a documented OpenLigaDB fallback for 2. Bundesliga, with partition validation, source-specific license metadata, hashes and raw snapshots.
- Time-weighted regularized Poisson attack/defence model and Dixon–Coles correction; same-day/future results excluded from forecast history.
- Match-result, scoreline, goal-total, BTTS and related goal probabilities.
- Chronological historical evaluation, baseline comparisons, Brier/log loss, calibration diagnostics and date-block bootstrap intervals.
- Temporal calibration experiment: fit probability temperature on earlier seasons, report performance only on the latest untouched season; calibration is not applied to live forecasts.
- Integrity-checked historical evaluation cache, keyed by data, date and code; duplicate computation protection within one server process.
- Dashboard with motion controls, match briefing, recent form, scoring records, evidence limitations and manual odds comparison.
- Deterministic research gates and optional advisory JEV review. Missing credentials never fabricate a review.
- CLI research runner with reproducible run records. It runs when invoked; no background scheduler is configured.
- Prospective ledger and result grader for fixtures registered at least a calendar day before play; first overall and first research-eligible forecasts are preserved separately.
- Supplemental statistics importer and gated shot/red-card estimates. Adequate data is not yet established.
- Local `.env` loading at server/runner startup, plus a shareable blank `.env.example`.

## Measured progress

The previous local EPL cache benchmark evaluated 1,140 matches: cold 19.33 seconds, warm 0.054 seconds, identical outputs. This is a single local timing, not a production load test. Reported model accuracy was about 51.75%, log loss 0.98918 and Brier 0.58950 on that retrospective evaluation; it does not establish forward accuracy. Thirty tests passed before the environment setup; configuration tests are added with this update.

The 26 September refresh verified 38 source partitions and ingested 1,836 2. Bundesliga matches across seasons 2021/22–2026/27 from OpenLigaDB. The current season now has 306 fixtures, of which 54 have full-time scores. Four Serie B partitions remain unavailable from the configured OpenFootball JSON path (three historical and the current season). Football-Data lists Serie B CSVs, but reuse terms remain unverified, so those files were not imported. The overall data file now records per-source licenses; OpenLigaDB match data is marked ODbL-1.0.

The 26 September runner logged 172 fixtures through 26 October: 103 are research-eligible and 69 remain review-required. All 172 await results. A 30-day batch forecast was made with JEV disabled, so it used no external review calls. The full state is `review_required` because Serie B coverage is absent.

The refreshed retrospective report now covers 6,153 matches in six leagues; Serie B is excluded for insufficient continuous history. Dixon–Coles had lower 1X2 log loss than plain Poisson in three leagues and higher loss in three. It beat the expanding league-frequency baseline in all six. A separate temperature-scaling experiment trained on earlier selected seasons and evaluated on 2025/26 changed held-out log loss only modestly; every paired date-block 95% interval included no effect. Calibration therefore remains off in live predictions, and no model promotion is supported yet.

## Result feed stall (18 November 2026)

OpenFootball's auto-update stopped on 22 September 2026. La Liga, Serie A, Ligue 1, Eredivisie and Primeira Liga have no scores after 20 September in `data.json`, so their forward forecasts (192 at 17 November) cannot be graded and their ratings miss two months of form. Bundesliga and Premier League are unaffected (OpenLigaDB `bl1` and `pl` fill them). No open replacement was found: OpenLigaDB's `la1` feed currently mixes Dutch clubs into La Liga, `ERE` has no results, and there is no Serie A, Ligue 1 or Portugal feed. API-Football's free plan reaches only yesterday to tomorrow. The local Lab fills the gaps in memory from football-data.co.uk, whose reuse terms remain unverified, so those scores are not committed.

## Goal-line calibration (checked 19 November 2026)

Walk-forward over 7,988 matches in eight leagues (2023-24 to 2025-26, refit before every match date), the goal lines are calibrated within 2 points on every line, on the tuning seasons and the 2025-26 hold-out alike. VIP-style picks run slightly cautious, not over-confident: Over 1.5 at 78%+ said 82.4% and won 83.7% (2025-26: 81.8% / 82.8%); Over 2.5 at 65%+ said 68.7% and won 74.5% (2025-26: 69.7% / 74.3%). The six-week replay's 85.9% / 83.0% was 177 picks. There is a small, consistent lean towards too many 0-0s and slightly too few goals (+1 to +1.7 points on Over 0.5 to Over 2.5), in line with the 1X2 draw shift; it was left alone because the published picks err on the safe side and the gain would come at the cost of 1X2 accuracy.

## Hosted site and daily job (November 2026)

The site runs at football-lab-ten.vercel.app from the committed open data. A GitHub Actions job (`.github/workflows/daily.yml`) runs every morning: it refreshes results and fixtures, freezes and grades forecasts, saves the football VIP slip before kickoff, saves backtest summaries for the Record page (`tools/save_backtests.py`, because the hosted disk is read-only and a live backtest took about a minute), refreshes NBA data from balldontlie, prices the NBA board, saves the NBA picks and grades them, and commits everything. GitHub has been starting the 05:30 UTC run up to nine hours late; it still runs before the evening games.

## Football VIP picks (updated 20 November 2026)

Rule, one goal pick per game: Over 2.5 at 65%+, else Over 1.5 at 78%+, else Under 3.5 at 70%+ (`record.VIP_PRIORITY`). Each league's places (at most six) fill in that order, Over 2.5 first (`record.tier`), so qualifying Over 2.5 picks are not crowded out by 80%+ Over 1.5. On top come up to three favourites to win at 75%+, from any game, including one that already has a goal pick (`record.vip_favourites`). Leagues: Premier League, La Liga, Bundesliga, Serie A, Eredivisie, Primeira Liga and 2. Bundesliga, each only while its results are current (`league_fresh`). Ligue 1 (said 77.0%, won 73.2%) and Serie B are left out. The VIP page leads with a "Goals pick of the day": the slip's strongest Over 2.5.

The check (`tools/goal_lines_check.py`, `reports/goal_lines_check.json`): every finished match in nine leagues since August 2024 forecast with the production model as of its own matchday; the rule was set on 2024-25. 2025-26: 2,748 picks, said 77.6%, won 78.5% (overs 81.3%, unders 75.9%). 2026-27 to date: 523 picks, won 80.3%. Under 2.5 failed (60%+ said 62-63%, won 51-55%) and is never picked. Raising Over 1.5 to 80% made the combined rule slightly worse (77.9% against 78.5%) and was not adopted. Favourites at 75%+ won 84.9% pooled over three seasons, against 80.2% at 70%+.

A private check against football-data.co.uk Over/Under 2.5 prices (not published; reuse terms unverified) found Over 2.5 at 65%+ about break-even to slightly positive at the best available price (2024-25 +9.6%, 2025-26 +1.3%, 2026-27 +0.1% per unit), while Over 2.5 at 60%+ lost 3-9% and Under 2.5 lost 8-25%.

The saved VIP record started on 17 November. The totals count each game's goal pick once and its winner pick once, under the first of each published (a slip covers three days, so a game can sit on several slips). The Record page shows Overs, Unders and To win tallies, the check above, the latest finished slip, a share card and a CSV of every saved pick (`/api/vip/export.csv`; NBA: `/api/nba/export.csv`).

## Track record and model health (20 November 2026)

`#track` shows both sports on one page: the saved-before-kickoff records, the long-run checks and a model health section. `model_health.py` runs in the daily job and compares "said" with "won" on the saved picks per sport and pick type, overall and over the last 28 days: collecting under 100 settled picks, then ok (within 3 points), watch (3-5 below), alert (5+ below or z <= -2.5) or cautious (5+ above). Report: `reports/model_health.json`, `/api/health`.

## Data accounts (20 November 2026)

- **API-Football** (Pro plan until 19 December 2026, 7,500 requests a day; key in `.env`, Vercel and the GitHub secret). On 20 November `apifootball_results.py` filled 231 missing results since 20 September (La Liga 47, Serie A 60, Ligue 1 44, Eredivisie 45, Primeira Liga 35) and the daily job now keeps those leagues current; football live scores work again. The earlier free account was suspended. About 1,470 requests had already been used on the new key before the first fill: check the dashboard for other users of the key. Pro also includes bookmaker odds (Bet365, Pinnacle and others), not yet used.
- **balldontlie** (free plan) supplies NBA scores, schedule and live scores; ALL-STAR would add injuries and player stats.
- **TypeSafe JEV** works on the hosted site (checked 20 November); the local `.env` key is empty, so it is off locally.

## Remaining priorities

1. Keep the prospective runner active before fixtures, grade results, and accumulate enough forward matches for a meaningful score.
2. Resolve Serie B coverage and independently reconcile results; establish licensed shot/card data coverage.
3. Compare additional model variants on rolling validation periods before freezing a new holdout; retain the current model until any challenger wins out of time.
4. Extend calibration evidence over multiple untouched periods, then harden scheduling, monitoring and multi-process concurrency.

Football-docs v0.11.1 has been reviewed as a documentation reference; no football-docs MCP server or new paid data provider is installed. See `DATA_INTEGRATION.md`.

## API configuration

Keys live in `.env` locally (git-ignored, mode 0600), in Vercel's environment variables for the hosted site, and in GitHub's repository secrets for the daily job. Never paste them in chat or commit them.

| Key | Used for | Where it must be set |
|---|---|---|
| `BALLDONTLIE_API_KEY` | NBA scores, schedule, live scores | `.env`, Vercel, GitHub secret |
| `API_FOOTBALL_KEY` | football live scores, filling missing results, lineups, odds | `.env`, Vercel, GitHub secret (Pro plan from 20 November) |
| `ODDS_API_KEY` | bookmaker odds (local Lab only; the hosted site shows none) | `.env` |
| `TYPESAFE_API_KEY` | optional JEV reviews | `.env` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | community league | `.env`, GitHub secrets |

Restart the local server after changing `.env`; redeploy on Vercel after changing its variables.

## Run from this folder

```sh
python3 app.py serve
```

Open http://127.0.0.1:8765/. The server binds only to this computer. Stop the existing process before starting another on the same port.

```sh
python3 -m unittest discover -v
python3 app.py backtest
python3 agent.py --days 7
```

`python3 app.py refresh` fetches current source files. Tests do not automatically load `.env`; no paid API check is needed for configuration tests.

## Main files

`app.py`: local HTTP server and forecasts; `model.py`: model fitting; `analysis.py`: descriptive briefing; `evaluation.py` / `evaluation_cache.py`: backtesting; `quality.py`: data validation; `decision.py`: research policy; `jev_reviewer.py`: JEV adapter; `config.py`: local environment loading; `agent.py`: CLI runner; `index.html`: dashboard; `reports/` and `snapshots/`: research artifacts.

## Basketball (NBA), added November 2026

Updated: 15 November 2026. Open work is listed in `NBA_TODO.md`; the method is in the README under "Basketball (NBA)".

- A Football / Basketball switch opens NBA Fixtures (next seven days) and Match views on the local Lab. `nba.py` reads results, quarter scores and one sportsbook's lines from ESPN's public feeds; `nba_model.py` fits team ratings and builds one final-score grid per game; `nba_app.py` serves the board and match pages.
- The data file (`nba_data.json`) is never committed because the feeds have no published reuse terms. The local server downloads it by itself when it is missing. The hosted site runs on balldontlie instead (see `NBA_TODO.md`).
- Ratings now learn mostly from past closing lines (70%) and partly from scores. Walk-forward on the 2025-26 hold-out the ratings alone miss the margin by 14.4 points against 14.1 for the closing line. They do not beat the line against the spread or total, so posted lines price the game and the ratings fill in where no line exists yet.
- Line-priced probabilities are well calibrated on 2025-26 and on 2026-27 to date (70%+ spread picks said 75.5%, won 75.4%).
- All NBA accuracy is backtested. There is no forward ledger for NBA yet; that is the next piece of work.
