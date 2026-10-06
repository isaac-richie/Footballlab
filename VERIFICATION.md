# Initial verification — 21 September 2026

## Revision 2 verification

11 automated tests passed, including refresh of already-known sources, preservation of failed partitions, total-failure file preservation, malformed-score rejection, league isolation, future-data exclusion, probability invariants and calibration arithmetic. HTTP malformed-object check returned 400. Live source refresh downloaded/verified 37 partitions and reported five 404 gaps.

All-league retrospective evaluation covered 6,153 fixtures across six eligible leagues, up to three seasons each. All six improved 1X2 log loss over expanding league frequencies. Serie B had no eligible completed season with 300 earlier training matches and was explicitly excluded. These comparisons do not establish profitability, independent data accuracy or calibrated probabilities.

Premier League aggregate: model log loss 0.9965 versus baseline 1.0736; paired date-block difference -0.0771, approximate 95% interval [-0.0938, -0.0598]. Goal totals are less convincing: over 4.5 and over 5.5 did not outperform their binary frequency baselines on Brier score. Per-season breakdowns and calibration tables are in reports/validation.json and the dashboard.

The revised 30-day runner completed 96 fixture analyses with overall status review_required. Reports include current coverage warnings, full data/code snapshots and an immutable run ID; no artificial confidence score remains.

Browser verified prediction table, review status, goal-market output, three-season evaluation and stale-result clearing on league switch. Production readiness and Jev integration are not claimed. Earlier sections below are historical notes, superseded where this revision differs.

Six OpenFootball season files downloaded without errors: 2,280 fixture/result records, of which 1,940 have completed scores dated before 21 September 2026. Latest included result: 14 September 2026. These are source records, not an independent audit of match results.

Chronological evaluation: 380 matches, 2025/26 season.

| Metric | Goal model | League frequency baseline |
|---|---:|---:|
| Log loss (lower better) | 1.031660 | 1.084006 |
| Multiclass Brier sum (lower better) | 0.618902 | 0.655991 |
| Most-likely outcome accuracy | 49.21% | 42.63% |

Four automated tests passed: probability normalization/symmetry/BTTS identity, exclusion of same-day/future results, odds normalization and invalid-input rejection, prediction invariance to future-score edits.

Browser verified: dashboard loads local data; fixture selection populates teams; manual 1X2 odds entry generates forecast, scorelines and margin-adjusted comparisons. For the observed Arsenal–Leeds fixture, using inspected SportyBet prices 1.39 / 5.13 / 8.02 yielded model probabilities approximately 68.2% / 19.2% / 12.5%. This is a timestamped research example, not a recommendation or a maintained price feed.

No Jev calls, paid APIs, account registration or automated SportyBet collection were used. Profitability, calibration, other-league coverage and advanced-statistics inputs remain unverified/unimplemented.

## Seven-league expansion

Verified source availability for the current 2025/26 season: Premier League and La Liga 380 fixtures each; Serie A and Serie B 380 each; Bundesliga, 2. Bundesliga and Ligue 1 306 each. The local dataset now contains 12,960 records and keeps each competition isolated for training and evaluation.

The interface was verified by switching to La Liga and calculating Athletic Club v CA Osasuna: 54.8% / 25.3% / 19.9% home/draw/away. API smoke checks returned historical result counts for all seven selectors. Serie B has 696 completed historical results; 2. Bundesliga has 1,323. The source has no Serie B file for 2021/22–2023/24 and no 2026/27 second-division fixture files yet; those gaps appear in the dashboard refresh status.
