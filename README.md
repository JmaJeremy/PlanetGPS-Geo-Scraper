# planetgps

Collects a vehicle's location history from [PlanetGPS](https://web.planetgps.com) into Postgres, for Grafana dashboards of distances, trips, routes and stops.

A cron job runs a small collector in Docker. Each run logs in to PlanetGPS, fetches every point since the newest one already stored, and inserts them. Overlapping or repeated runs are harmless.

## Setup

Requires Docker with the compose plugin.

```sh
cp .env.example .env    # then fill it in, see below
docker compose up -d db
docker compose run --rm --build collector --start 2026-06-01   # first run: backfill from this date (UTC)
```

| Variable | |
|---|---|
| `PLANETGPS_USER`, `PLANETGPS_PASSWORD` | Your PlanetGPS website login. I'd recommend creating a separate read-only user from your main account. |
| `PLANETGPS_DEVICE_ID` | Tracker ID, which you will have to find out by inspecting the web tracker, not the same as the actual "device ID" associated with your GPS unit |
| `POSTGRES_PASSWORD` | Password for the database owner, `planetgps` |
| `GRAFANA_RO_PASSWORD` | Password for `grafana_ro`, a read-only login for Grafana |
| `PG_PORT` | Host port Postgres is published on (default `5432`) |
| `PLANETGPS_SHOW_LBS` | Set to `1` to also store cell/WiFi position fixes, not just GPS |

Then schedule the collector, for example every 15 minutes:

```cron
*/15 * * * * cd /path/to/planetgps && docker compose run --rm collector >> collect.log 2>&1
```

The tracker only reports while the vehicle is moving, so a run that inserts nothing is normal.

## Grafana

Add a PostgreSQL datasource pointing at the host's `PG_PORT`, database `planetgps`, user `grafana_ro`. The container has no TLS, so set SSL mode to `disable`, and keep the port on a private network, or configure your own certs.

These are the tables and views to query:

| Name | What it holds |
|---|---|
| `locations` | One row per reported point: time, lat/lon, speed (km/h), heading, odometer (km) |
| `location_deltas` | `locations` plus `delta_km`, the distance since the previous point. The distance for any time span is `sum(delta_km)` |
| `trip_points` | `location_deltas` plus a `trip_id` for each point |
| `trips` | One row per trip: start and end time and position, duration, km, max speed |

A trip ends when the tracker goes quiet for more than 5 minutes, which usually means the vehicle is parked. To change that threshold, edit both places it appears in `db/01-schema.sql`, then re-apply the file (below).

## Maintenance

```sh
docker compose exec db psql -U planetgps planetgps                        # SQL shell
docker compose exec -T db psql -U planetgps planetgps < db/01-schema.sql  # re-apply schema/view changes
```

The scripts in `db/` run automatically only when the database volume is first created. `01-schema.sql` can be re-applied safely at any time, but `02-grafana-ro.sh` never runs again on an existing volume.

## One-off export

`planetgps_history_export.py` also works on its own, without the database. It exports a date range to CSV, GeoJSON and GPX:

```sh
pip install -r requirements.txt
python planetgps_history_export.py --user U --password P --device-id ID \
    --start 2026-06-01 --end 2026-08-31 --out history
```

## How it talks to PlanetGPS

PlanetGPS has no public API. This tool uses the same undocumented JSON endpoints the website's Playback page calls, documented at the top of `planetgps_history_export.py`, so a change to the site could break it. All times are in UTC.
