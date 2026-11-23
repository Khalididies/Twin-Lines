"""Find bus line numbers reused by different operators in the same area.

Usage:
    python gtfs_collisions.py --demo                 # tiny built-in sample
    python gtfs_collisions.py                        # download Israel MoT GTFS and run
    python gtfs_collisions.py --zip my_feed.zip      # use a local GTFS zip
    python gtfs_collisions.py --stride               # weight by real rides/day (Stride API)
"""
import argparse, datetime, io, json, urllib.parse, urllib.request, zipfile
from pathlib import Path

import pandas as pd

URL = "https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip"
STRIDE = "https://open-bus-stride-api.hasadna.org.il"
CELL = 0.005  # grid cell in degrees, roughly 500 m


def recent_thursdays(n=4):
    """Normal full-service weekdays, newest first (Shabbat has very few rides)."""
    d = datetime.date.today() - datetime.timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() == 3:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out


def stride_rides(date=None):
    """Planned rides per line number on one day, from the Open Bus Stride API.

    Tries the last few Thursdays (the newest day may not be aggregated yet).
    Returns None if the API has nothing usable, so callers can fall back to trip counts.
    """
    for d in ([date] if date else recent_thursdays()):
        q = urllib.parse.urlencode({"date_from": d, "date_to": d, "group_by": "line_ref"})
        try:
            with urllib.request.urlopen(f"{STRIDE}/gtfs_rides_agg/group_by?{q}", timeout=60) as r:
                df = pd.DataFrame(json.load(r))
        except Exception:
            continue
        if df.empty or "route_short_name" not in df or "total_planned_rides" not in df:
            continue
        df["route_short_name"] = df.route_short_name.astype(str).str.strip()
        df["total_planned_rides"] = pd.to_numeric(df.total_planned_rides, errors="coerce").fillna(0)
        out = (df.groupby("route_short_name").total_planned_rides.sum()
                 .rename("rides_per_day").reset_index())
        if out.rides_per_day.sum() > 0:
            return out
    return None


def read(z, name, **kw):
    with z.open(name) as f:
        return pd.read_csv(f, dtype=str, **kw)


def demo_zip():
    files = {
        "agency.txt": "agency_id,agency_name\n1,Sample Bus Co A\n2,Sample Bus Co B\n3,Sample Bus Co C\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name\n"
                      "r1,1,7,Sample route A1\nr2,2,7,Sample route B1\nr3,3,7,Sample route C1\n"
                      "r4,1,18,Sample route A2\nr5,2,18,Sample route B2\n",
        "trips.txt": "route_id,trip_id,direction_id\nr1,t1,0\nr2,t2,0\nr3,t3,0\nr4,t4,0\nr5,t5,0\n"
                     "r1,t6,0\nr1,t7,0\nr2,t8,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     "s1,Sample stop 1,32.0900,34.7800\ns2,Sample stop 2,32.0962,34.7862\n"
                     "s3,Sample stop 3,32.0963,34.7863\ns4,Sample stop 4,31.7700,35.2100\n"
                     "s5,Sample stop 5,32.8000,34.9900\ns6,Sample stop 6,32.8100,35.0000\n",
        "stop_times.txt": "trip_id,stop_id,stop_sequence\nt1,s1,1\nt1,s2,2\nt2,s3,1\nt2,s4,2\n"
                          "t3,s5,1\nt3,s6,2\nt4,s1,1\nt5,s5,1\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    buf.seek(0)
    return zipfile.ZipFile(buf)


LINE_COLS = ["route_short_name", "agency_name", "route_id", "route_long_name", "n_trips",
             "stop_sequence", "stop_name", "stop_lat", "stop_lon"]
OUT_COLS = ["route_short_name", "shared_cells", "max_agencies", "operators", "trips", "impact"]


def collide(df, trips_by_name, rides=None):
    """df: one row per (route, stop) with LINE_COLS. Returns (summary, shared cells, lines)."""
    df = df.copy()
    df["cell"] = (df.stop_lat // CELL).astype(int).astype(str) + "_" + (df.stop_lon // CELL).astype(int).astype(str)
    cells = df.drop_duplicates(["route_short_name", "agency_name", "cell"])

    g = cells.groupby(["route_short_name", "cell"]).agency_name.nunique()
    shared = g[g > 1].reset_index(name="agencies")
    if shared.empty:
        return (pd.DataFrame(columns=OUT_COLS),
                pd.DataFrame(columns=["route_short_name", "cell", "agencies", "lat", "lon"]),
                pd.DataFrame(columns=LINE_COLS))
    out = (shared.groupby("route_short_name")
                 .agg(shared_cells=("cell", "count"), max_agencies=("agencies", "max"))
                 .reset_index())
    ops = cells.groupby("route_short_name").agency_name.apply(lambda s: ", ".join(sorted(set(s))))
    out = out.merge(ops.rename("operators"), on="route_short_name")
    out = out.merge(trips_by_name, on="route_short_name")  # frequency weight: trips on this number
    weight = out.trips
    if rides is not None:  # real planned rides on a normal weekday (Stride API)
        merged = out.merge(rides, on="route_short_name", how="left").fillna({"rides_per_day": 0})
        if (merged.rides_per_day > 0).mean() >= 0.5:  # enough lines matched to trust it
            out = merged
            out["rides_per_day"] = out.rides_per_day.astype(int)
            weight = out.rides_per_day
    out["impact"] = out.shared_cells * weight  # busy lines colliding over a wide area rank first
    out = out.sort_values("impact", ascending=False).reset_index(drop=True)

    # cell centers, for plotting on a map
    shared["lat"] = shared.cell.str.split("_").str[0].astype(int) * CELL + CELL / 2
    shared["lon"] = shared.cell.str.split("_").str[1].astype(int) * CELL + CELL / 2
    # route geometry (stops in order) for the colliding line numbers, for drawing on a map
    lines = df[df.route_short_name.isin(out.route_short_name)][LINE_COLS].copy()
    lines["stop_sequence"] = lines.stop_sequence.astype(int)
    lines = lines.sort_values(["route_id", "stop_sequence"])
    return out, shared, lines


def run(z, rides=None):
    """Whole-country analysis from a GTFS zip."""
    agency = read(z, "agency.txt")[["agency_id", "agency_name"]]
    routes = read(z, "routes.txt")
    if "route_long_name" not in routes:
        routes["route_long_name"] = ""
    routes = routes[["route_id", "agency_id", "route_short_name", "route_long_name"]].fillna("")

    all_trips = read(z, "trips.txt")[["route_id", "trip_id"]]
    trip_counts = all_trips.groupby("route_id").size().rename("n_trips").reset_index()
    routes = routes.merge(trip_counts, on="route_id", how="left").fillna({"n_trips": 0})
    routes["n_trips"] = routes.n_trips.astype(int)
    trips = all_trips.drop_duplicates("route_id")  # 1 trip per route for the stop geometry
    keep = set(trips.trip_id)

    # stop_times is the big table: read in chunks and keep only needed rows
    parts = []
    with z.open("stop_times.txt") as f:
        for chunk in pd.read_csv(f, dtype=str, usecols=["trip_id", "stop_id", "stop_sequence"],
                                 chunksize=1_000_000):
            parts.append(chunk[chunk.trip_id.isin(keep)])
    st = pd.concat(parts)

    stops = read(z, "stops.txt")
    if "stop_name" not in stops:
        stops["stop_name"] = ""
    stops = stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].fillna("")
    stops[["stop_lat", "stop_lon"]] = stops[["stop_lat", "stop_lon"]].astype(float)

    df = (st.merge(trips, on="trip_id").merge(routes, on="route_id")
            .merge(agency, on="agency_id").merge(stops, on="stop_id"))
    n = routes.groupby("route_short_name").n_trips.sum().rename("trips").reset_index()
    return collide(df, n, rides)


EXAMPLES_FILE = Path(__file__).with_name("sample_data") / "real_examples.csv"
EXAMPLE_NOTES = {
    "Line 240 · Bnei Brak": "Two operators run a line 240 that serves the same stop area in Bnei Brak. Kavim's goes to "
                            "Modi'in Illit; Dan's goes to Holon. Their terminals are about 28 km apart.",
    "Line 3 · Haifa Bay": "Egged's line 3 runs in Haifa (Hof HaCarmel central station to Bar Rav Hai St.); "
                          "Superbus's line 3 starts and ends at the Krayot central station in Kiryat Motzkin. "
                          "They share a stop area, but the routes are about 14 km apart.",
}


NATIONAL_FILE = Path(__file__).with_name("sample_data") / "national_summary.csv"


def load_national_summary():
    """Ranking of all colliding line numbers from a real national run (November 2026)."""
    return pd.read_csv(NATIONAL_FILE, dtype={"route_short_name": str})


def load_examples():
    """Bundled snapshot of real routes from the Israel MoT GTFS feed (November 2026).

    Returns {example name: (summary, shared cells, lines)}.
    """
    df = pd.read_csv(EXAMPLES_FILE, dtype={"route_id": str, "route_short_name": str}).fillna("")
    out = {}
    for name, g in df.groupby("example", sort=False):
        trips = (g.drop_duplicates("route_id").groupby("route_short_name").n_trips.sum()
                  .rename("trips").reset_index())
        out[name] = collide(g.drop(columns="example"), trips)
    return out


def _get(path, **params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{STRIDE}{path}?{q}", timeout=60) as r:
        return json.load(r)


def lookup_line(number):
    """One line number, all operators, straight from the Stride API (no big download).

    Per route: 1 request for a sample ride, 1 for the day's ride count, 1 for its stops.
    Returns None if the line is not found.
    """
    number = str(number).strip()
    routes = []
    for d in recent_thursdays():
        routes = _get("/gtfs_routes/list", route_short_name=number, date_from=d, date_to=d, limit=500)
        if routes:
            break
    rows = []
    for r in routes:
        rides = _get("/gtfs_rides/list", gtfs_route_id=r["id"], limit=1)
        if not rides:
            continue
        try:
            c = _get("/gtfs_rides/list", gtfs_route_id=r["id"], get_count="true")
            n = int(c) if not isinstance(c, (list, dict)) else 0
        except Exception:
            n = 0
        for s in _get("/gtfs_ride_stops/list", gtfs_ride_ids=str(rides[0]["id"]), limit=1000):
            rows.append({"route_short_name": str(r.get("route_short_name") or number),
                         "agency_name": r.get("agency_name") or "", "route_id": str(r["id"]),
                         "route_long_name": r.get("route_long_name") or "", "n_trips": n,
                         "stop_sequence": s.get("stop_sequence") or 0, "stop_name": s.get("gtfs_stop__name") or "",
                         "stop_lat": s.get("gtfs_stop__lat"), "stop_lon": s.get("gtfs_stop__lon")})
    if not rows:
        return None
    df = pd.DataFrame(rows).dropna(subset=["stop_lat", "stop_lon"])
    df[["stop_lat", "stop_lon"]] = df[["stop_lat", "stop_lon"]].astype(float)
    trips = (df.drop_duplicates("route_id").groupby("route_short_name").n_trips.sum()
               .rename("trips").reset_index())
    return collide(df, trips)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--zip")
    ap.add_argument("--stride", action="store_true", help="weight by real rides/day from the Stride API")
    a = ap.parse_args()
    if a.demo:
        z = demo_zip()
    elif a.zip:
        z = zipfile.ZipFile(a.zip)
    else:
        print("Downloading GTFS...")
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL).read()))
    rides = stride_rides() if a.stride else None
    if a.stride and rides is None:
        print("Stride API gave nothing usable; weighting by GTFS trip counts instead.")
    res, *_ = run(z, rides)
    res.to_csv("collisions.csv", index=False)
    print(res.head(15).to_string(index=False))
    print(f"\n{len(res)} line numbers are reused by different operators in the same area -> collisions.csv")
