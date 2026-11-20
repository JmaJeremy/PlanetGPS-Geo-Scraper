#!/usr/bin/env python3
"""
Incremental collector: fetch new PlanetGPS points since the newest stored one
and insert them into Postgres. Meant to be run from cron; safe to re-run.

Env: DATABASE_URL, PLANETGPS_USER, PLANETGPS_PASSWORD, PLANETGPS_DEVICE_ID,
     optional PLANETGPS_SHOW_LBS=1
First run on an empty DB needs --start (UTC 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM').
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg
import requests

from planetgps_history_export import UA, fetch, login

INSERT = """
INSERT INTO locations (device_id, location_id, ts, lat, lon, speed_kmh, course,
                       odometer_km, data_type, ct)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
"""


def row(device_id, p):
    ts = datetime.strptime(p["deviceUtcDate"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (device_id, int(p["locationID"]), ts, float(p["latitude"]), float(p["longitude"]),
            float(p["speed"]), int(p["course"]), float(p["distance"]), int(p["dataType"]), p.get("ct"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="backfill from this UTC time (default: newest stored point)")
    a = ap.parse_args()
    env = os.environ
    device_id = int(env["PLANETGPS_DEVICE_ID"])

    with psycopg.connect(env["DATABASE_URL"]) as db:
        newest = db.execute("SELECT max(ts) FROM locations WHERE device_id = %s",
                            (device_id,)).fetchone()[0]
        if a.start:
            start = a.start if " " in a.start else a.start + " 00:00"
        elif newest:
            # minute precision overlap is absorbed by ON CONFLICT
            start = newest.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        else:
            sys.exit("Empty database: run once with --start YYYY-MM-DD to backfill")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        s = requests.Session()
        s.headers["User-Agent"] = UA
        login(s, env["PLANETGPS_USER"], env["PLANETGPS_PASSWORD"], 0)
        points = fetch(s, device_id, start, end, int(env.get("PLANETGPS_SHOW_LBS", 0)))

        with db.cursor() as cur:
            before = db.execute("SELECT count(*) FROM locations").fetchone()[0]
            cur.executemany(INSERT, [row(device_id, p) for p in points])
            added = db.execute("SELECT count(*) FROM locations").fetchone()[0] - before
    print(f"{start} -> {end}: fetched {len(points)}, inserted {added}")


if __name__ == "__main__":
    main()
