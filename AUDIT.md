# Engineering and statistical audit — 21 September 2026

Verdict: previously an exploratory prototype; now a more reproducible research system. Still not established as industry-standard forecasting or a production service.

## Defects addressed

| Finding | Impact | Change |
|---|---|---|
| Refresh skipped downloaded URLs | Never collected new scores/corrections | Re-fetch, verify each source |
| Merge retained obsolete fixtures | Reschedules could leave duplicates | Replace validated league-season partition |
| Invalid scores became missing scores | Bad history could be treated as future fixture | Quarantine malformed partition |
| Arbitrary confidence formula | Unvalidated certainty/ranking | Remove, expose data review status |
| Sole report overwritten | No reproducible run history | Immutable run IDs and full data/code snapshots |
| Single-season 1X2 evaluation | Limited evidence | Multi-season, goal-market scores, calibration diagnostics, uncertainty |
| Duplicate UI requests/stale panels | Wrong selection/result association | Single request and stale-response guard |
| Half-goal handicaps called whole-goal | Incorrect market terminology | Correct labels |
| Same-day fixtures without times | Possible post-kickoff forecasts | Exclude same-day batch fixtures |
| Runner called autonomous agent | Overstated capability | Explicit deterministic workflow status |

## Remaining acceptance criteria

1. Reconcile dates, results, team identities, coverage and timezones against an independent authoritative source. Accessible CC0 JSON alone is not validation of the underlying facts. Missing current second-division schedules need resolution.
2. Compare fitted Poisson, Dixon–Coles and alternatives with chronological training/validation/test splits. Tune only inside training/validation folds and freeze before a new holdout. Current fixed estimator is a baseline, not an optimized production model.
3. Evaluate/finalize calibration on disjoint data with sample sizes and uncertainty per league/market. Current reliability tables do not calibrate predictions. Do not reuse these evaluated seasons as untouched holdouts after tuning.
4. Freeze forecasts before kickoff and collect prospective results. Retrospective source corrections cannot reconstruct historical knowledge perfectly.
5. Collect timestamped odds and precise settlement rules before asserting value or profitability. Include costs, margin methods, missingness and uncertainty. Quarter-goal lines and pushes are not implemented.
6. Build backup/restore, monitored scheduling, failure recovery integration tests and structured execution logs. The local HTTP server is not a hardened public service. No scheduled task is configured.
7. Evaluate the optional Jev reviewer against human evidence reviews. Its model is pinned and token usage is shown, but cost and utility have not been measured across a representative sample.

Zero budget remains the constraint. Current shots, corners, cards, injuries and player-lineup coverage remains unresolved. No betting actions, external deployment or paid services were used in this revision.
