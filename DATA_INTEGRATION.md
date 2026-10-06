# Data integration policy

Reference reviewed: [football-docs v0.11.1](https://github.com/withqwerty/football-docs/releases/tag/v0.11.1).
This is a documentation reference, not a match-data subscription or a running ingestion agent. No MCP server has been installed by this change.

The release corrects Driblab schema differences observed against the live API, including different field naming and grouping between team, player and game records. Our practical takeaway: documentation alone cannot validate an adapter.

For this zero-budget build, keep the existing OpenFootball results pipeline where it has coverage. Do not add paid providers or scrape undocumented endpoints to fill gaps. Investigate openly licensed event datasets separately; verify actual league/season coverage and usage terms before importing. Documentation/package licenses do not grant rights to provider data.

The 2. Bundesliga fallback uses the documented OpenLigaDB JSON API (`getmatchdata/bl2/{season-year}`). The provider identifies its match data as Open Database License v1.0. Each fetched season is retained with its own URL, hash, timestamp and license metadata; the overall data file therefore records `license: per-source`. This is a source-level coverage repair, not a new predictive feature. The 2026/27 endpoint returned 306 fixtures in the source check; fixture count, scores and date normalization are validated before replacing a season partition.

Football-Data.co.uk lists Serie B CSV files and publishes field definitions, but the public pages reviewed do not establish a redistribution license. Do not ingest those files until reuse terms are confirmed. The current OpenFootball Italy repository has not yet published a 2026/27 Serie B file. The official Lega B calendar remains a manual cross-check, not an automated feed.

Every new adapter must pass these gates before entering forecasts:

1. Record the upstream source, terms, retrieval time and raw-content hash.
2. Verify league, season and field coverage using real samples, not marketing counts.
3. Map stable fixture/team identities and reject ambiguous matches.
4. Test schema variations, missing values, duplicates, corrections, authentication failures and rate limits using offline fixtures.
5. Preserve missing observations as missing, never zero. Quarantine malformed partitions.
6. Establish when each feature was available before kickoff. Current corrected historical data is not proof of a pre-match information set.
7. Compare chronological out-of-sample log loss, Brier score and calibration with the existing baseline before promoting features.

Priority: reliable results and immutable pre-match forecast logging first; shots/cards only after adequate licensed coverage. No accuracy improvement is claimed from adopting this reference.

# Evaluation performance

Historical evaluations now use a disposable disk cache under `reports/cache`, one file per requested supported league. Identity covers the complete input data, league, local calendar day and source hashes of app/model/evaluation/quality/cache code. Results are checksum-checked and written atomically. Corrupt entries are recomputed; storage failures do not discard a successful calculation. Concurrent evaluations are serialized within one Python process. This is not a cross-process lock or a production job queue.

Daily empirical goal-market baselines are shared across fixtures on the same date. Model fitting, probability formulas and evaluation cutoffs are unchanged. Cache hits improve response time, not forecast accuracy. A cold evaluation still refits the model; no compute-heavy external services or paid API calls are required.
