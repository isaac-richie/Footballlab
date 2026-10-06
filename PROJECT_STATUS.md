# Football Lab — project and progress

Updated: 26 September 2026.

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

## Remaining priorities

1. Keep the prospective runner active before fixtures, grade results, and accumulate enough forward matches for a meaningful score.
2. Resolve Serie B coverage and independently reconcile results; establish licensed shot/card data coverage.
3. Compare additional model variants on rolling validation periods before freezing a new holdout; retain the current model until any challenger wins out of time.
4. Extend calibration evidence over multiple untouched periods, then harden scheduling, monitoring and multi-process concurrency.

Football-docs v0.11.1 has been reviewed as a documentation reference; no football-docs MCP server or new paid data provider is installed. See `DATA_INTEGRATION.md`.

## API configuration

Only `TYPESAFE_API_KEY` is currently needed, and only for optional JEV reviews. The existing OpenFootball data pipeline needs no API key. SportyBet, paid statistics providers and other LLM APIs are not integrated, so no unused credential fields are invented.

Edit `.env` in this folder and put a newly rotated key after `TYPESAFE_API_KEY=`. Do not paste secrets in chat, commit them, include them in screenshots or share the entire project folder with `.env` included. The file is plaintext with owner-only permissions (0600), not encrypted storage. `.gitignore` protects future Git workflows but not backups or folder sharing. The previously disclosed key has deliberately not been copied into this file.

An existing process environment value takes precedence, including an explicitly blank value. Restart after changing `.env`. Blank/missing key leaves local analytics available and JEV unavailable. A configured JEV review makes a network request and may consume provider quota; local throttling does not guarantee free usage.

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
