-- Idempotent: re-apply after edits with
--   docker compose exec -T db psql -U planetgps planetgps < db/01-schema.sql

CREATE TABLE IF NOT EXISTS locations (
    device_id   bigint           NOT NULL,
    location_id bigint           NOT NULL,
    ts          timestamptz      NOT NULL,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    speed_kmh   real,
    course      smallint,
    odometer_km double precision,   -- device's cumulative odometer (km)
    data_type   smallint,           -- 1 = GPS; others are cell/WiFi (LBS) fixes
    ct          text,
    PRIMARY KEY (device_id, location_id)
);
CREATE INDEX IF NOT EXISTS locations_device_ts ON locations (device_id, ts);

-- Per-point deltas. Distance over any span = sum(delta_km).
-- greatest(0, ..) guards against odometer resets.
CREATE OR REPLACE VIEW location_deltas AS
SELECT l.*,
       coalesce(greatest(0, odometer_km - lag(odometer_km) OVER w), 0) AS delta_km,
       ts - lag(ts) OVER w AS gap
FROM locations l
WINDOW w AS (PARTITION BY device_id ORDER BY ts);

-- A new trip starts after a reporting gap > 5 min (the tracker goes quiet when parked).
-- shortcut: views recompute over all history per query; fine for years of one car,
-- switch to a materialized view refreshed by collect.py if dashboards get slow.
CREATE OR REPLACE VIEW trip_points AS
SELECT d.*,
       (gap IS NULL OR gap > interval '5 minutes') AS trip_start,
       sum(CASE WHEN gap IS NULL OR gap > interval '5 minutes' THEN 1 ELSE 0 END)
           OVER (PARTITION BY device_id ORDER BY ts) AS trip_id
FROM location_deltas d;

CREATE OR REPLACE VIEW trips AS
SELECT device_id,
       trip_id,
       min(ts)                                        AS start_ts,
       max(ts)                                        AS end_ts,
       max(ts) - min(ts)                              AS duration,
       sum(delta_km) FILTER (WHERE NOT trip_start)    AS km,
       max(speed_kmh)                                 AS max_speed_kmh,
       (array_agg(lat ORDER BY ts))[1]                AS start_lat,
       (array_agg(lon ORDER BY ts))[1]                AS start_lon,
       (array_agg(lat ORDER BY ts DESC))[1]           AS end_lat,
       (array_agg(lon ORDER BY ts DESC))[1]           AS end_lon,
       count(*)                                       AS points
FROM trip_points
GROUP BY device_id, trip_id;
