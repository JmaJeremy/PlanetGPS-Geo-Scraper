#!/usr/bin/env python3
"""
Download full PlanetGPS location history (with timestamps, speed, heading)
via the JSON endpoint behind the Playback page.

Endpoint (reverse-engineered from /JS/Playback.js):
  POST /Ajax/DevicesAjax.asmx/GetDevicesHistory
  Content-Type: application/json
  body: {DeviceID:1782533,Start:'YYYY-MM-DD HH:MM',End:'YYYY-MM-DD HH:MM',
         TimeZone:'0:00',ShowLBS:0}
  -> {"d": "{devices:[{deviceUtcDate,latitude,longitude,speed,course,
                        dataType,ct,distance,locationID}, ...],
              lastLocationID, lastDeviceUtcDate}"}
  `d` is a JS object literal (unquoted keys), not strict JSON.
  Times come back in the TimeZone you pass; '0:00' = true UTC.
  Each call returns ~5,000 points max, so we page by restarting from the
  last returned timestamp and de-duplicating.

Auth: same session cookie as the website. Either log in with
--user/--password (POST /Ajax/UsersAjax.asmx/Login) or pass --cookie
copied from a logged-in browser.

  pip install requests
  python planetgps_history_export.py --user U --password P \
      --device-id 1234567 --start "2026-06-01" --end "2026-08-31" --out history
Writes <out>.csv, <out>.geojson and <out>.gpx
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timedelta

import requests

BASE = "https://web.planetgps.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
FIELDS = ["deviceUtcDate", "latitude", "longitude", "speed", "course",
          "dataType", "distance", "ct", "locationID"]


def js_obj(s: str):
    """Parse the JS object literal the server returns (unquoted keys)."""
    try:
        return json.loads(s)
    except ValueError:
        return json.loads(re.sub(r'([{,])\s*([A-Za-z_]\w*)\s*:', r'\1"\2":', s))


def login(s, user, pw, gmt):
    r = s.post(f"{BASE}/Ajax/UsersAjax.asmx/Login",
               json={"Name": user, "Pass": pw, "LoginType": 0, "GMT": gmt}, timeout=20)
    r.raise_for_status()
    d = r.json().get("d", "")
    info = dict(re.findall(r"""['"]?(\w+)['"]?\s*:\s*['"]([^'"]*)['"]""", d or ""))
    if str(info.get("state")) != "2000":
        sys.exit(f"Login failed: {d!r}")
    if info.get("url"):
        s.get(requests.compat.urljoin(BASE + "/", info["url"]), timeout=20)


def history(s, device_id, start, end, show_lbs=0):
    body = (f"{{DeviceID:{int(device_id)},Start:'{start}',End:'{end}',"
            f"TimeZone:'0:00',ShowLBS:{int(show_lbs)}}}")
    r = s.post(f"{BASE}/Ajax/DevicesAjax.asmx/GetDevicesHistory", data=body,
               headers={"Content-Type": "application/json; charset=utf-8"}, timeout=120)
    r.raise_for_status()
    d = r.json().get("d", "")
    return js_obj(d)["devices"] if d else []


def fetch(s, device_id, start, end, show_lbs=0, delay=1.0):
    """All points between start and end ('YYYY-MM-DD HH:MM' UTC), paging past the ~5k cap."""
    seen, points, cursor = set(), [], start
    while True:
        batch = history(s, device_id, cursor, end, show_lbs)
        new = [p for p in batch
               if (k := (p["deviceUtcDate"], p["latitude"], p["longitude"])) not in seen
               and not seen.add(k)]
        points += new
        print(f"from {cursor}: got {len(batch)}, new {len(new)}, total {len(points)}")
        if not new:
            break
        last = datetime.strptime(batch[-1]["deviceUtcDate"], "%Y-%m-%d %H:%M:%S")
        nxt = last.strftime("%Y-%m-%d %H:%M")          # API takes minute precision
        if nxt == cursor:                               # >5k points in one minute: skip ahead
            nxt = (last + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        if nxt >= end:
            break
        cursor = nxt
        time.sleep(delay)
    return sorted(points, key=lambda p: p["deviceUtcDate"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user"); ap.add_argument("--password")
    ap.add_argument("--cookie", help="raw Cookie header from a logged-in browser")
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--start", required=True, help="UTC, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--end", required=True, help="UTC, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--show-lbs", action="store_true", help="include cell/WiFi (non-GPS) fixes")
    ap.add_argument("--out", default="planetgps_history")
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    fmt = lambda x: x if " " in x else x + (" 00:00" if x == a.start else " 23:59")
    start, end = fmt(a.start), fmt(a.end)

    s = requests.Session()
    s.headers["User-Agent"] = UA
    if a.cookie:
        s.headers["Cookie"] = a.cookie
    elif a.user and a.password:
        login(s, a.user, a.password, 0)
    else:
        sys.exit("Give --user/--password or --cookie")

    points = fetch(s, a.device_id, start, end, a.show_lbs, a.delay)

    with open(f"{a.out}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(points)

    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [float(p["longitude"]), float(p["latitude"])]},
         "properties": {k: p.get(k) for k in FIELDS if k not in ("latitude", "longitude")}}
        for p in points]}
    with open(f"{a.out}.geojson", "w") as fh:
        json.dump(gj, fh)

    with open(f"{a.out}.gpx", "w") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="planetgps_history_export" '
                 'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>%s</name><trkseg>\n' % a.device_id)
        for p in points:
            t = p["deviceUtcDate"].replace(" ", "T") + "Z"
            fh.write(f'<trkpt lat="{p["latitude"]}" lon="{p["longitude"]}"><time>{t}</time></trkpt>\n')
        fh.write("</trkseg></trk></gpx>\n")

    print(f"Wrote {len(points)} points to {a.out}.csv / .geojson / .gpx")


if __name__ == "__main__":
    main()
