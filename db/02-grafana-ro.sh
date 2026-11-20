#!/bin/sh
# Read-only login for Grafana. Runs once, on first init of an empty data volume.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v pw="$GRAFANA_RO_PASSWORD" <<'SQL'
CREATE ROLE grafana_ro LOGIN PASSWORD :'pw';
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
SQL
