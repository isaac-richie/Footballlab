#!/usr/bin/env bash
# Run the row-level security and scoring tests against a throwaway local Postgres 15+.
# Usage: PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres ./run_tests.sh
set -euo pipefail
cd "$(dirname "$0")"
psql -q -c "drop database if exists beat_the_lab_test" -c "create database beat_the_lab_test"
psql -q -d beat_the_lab_test -v ON_ERROR_STOP=1 -f test_stub.sql -f schema.sql
psql -q -d beat_the_lab_test -v ON_ERROR_STOP=1 -f test_rules.sql
psql -q -c "drop database beat_the_lab_test"
