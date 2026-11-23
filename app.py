"""Twin Lines: where the same bus number means two different routes.

Streamlit front end for gtfs_collisions.py.  Run with:  streamlit run app.py
"""
import base64
import html
import io
import math
import pickle
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from gtfs_collisions import (EXAMPLE_NOTES, URL, load_examples, load_national_summary,
                             lookup_line, run, stride_rides)

# --------------------------------------------------------------------------- setup
st.set_page_config(page_title="Twin Lines", page_icon="🚌", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1500px;}
h1 {font-weight: 700; letter-spacing: -0.5px; margin-bottom: 0;}
footer {visibility: hidden;}
.tl-sub {color: #9aa0a6; margin: 0 0 .9rem 0; font-size: 1.02rem;}
.tl-badge {display:inline-block; padding:2px 10px; border-radius:12px; font-size:.78rem; font-weight:600;}
.tl-real {background:#17402a; color:#6fe3a1;}
.tl-card {background:#2a2d30; border:1px solid #3a3e42; border-radius:10px; padding:14px 18px;}
.tl-card h4 {margin:0 0 .5rem 0; font-size:1.05rem;}
.tl-row {display:flex; justify-content:space-between; gap:12px; padding:5px 0;
         border-bottom:1px solid #34383c; font-size:.88rem;}
.tl-row:last-child {border-bottom:none;} .tl-row span:first-child {color:#9aa0a6;}
.tl-row span:last-child {text-align:right; font-weight:500;}
.tl-legend {background:#2b2f33; color:#fff; padding:9px 14px; border-radius:8px; display:inline-block;
            font-size:.85rem; line-height:1.9; margin-bottom:8px;}
</style>
""", unsafe_allow_html=True)


def svg_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


BUS_ICON = svg_url("<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 48 48'>"
                   "<rect x='4' y='4' width='40' height='40' rx='9' fill='#3f4bb8' stroke='white' stroke-width='3'/>"
                   "<rect x='13' y='11' width='22' height='15' rx='3' fill='white'/>"
                   "<rect x='16' y='14' width='16' height='7' fill='#3f4bb8'/>"
                   "<circle cx='17' cy='32' r='3' fill='white'/><circle cx='31' cy='32' r='3' fill='white'/></svg>")
END_ICON = svg_url("<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 48 48'>"
                   "<circle cx='24' cy='24' r='20' fill='white' stroke='#1d78dc' stroke-width='4'/>"
                   "<g fill='black'><rect x='12' y='12' width='8' height='8'/><rect x='28' y='12' width='8' height='8'/>"
                   "<rect x='20' y='20' width='8' height='8'/><rect x='12' y='28' width='8' height='8'/>"
                   "<rect x='28' y='28' width='8' height='8'/></g></svg>")
START_ICON = svg_url("<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 48 48'>"
                     "<circle cx='24' cy='24' r='20' fill='#2e9e4f' stroke='white' stroke-width='4'/>"
                     "<polygon points='19,14 19,34 35,24' fill='white'/></svg>")


def icon(url: str) -> dict:
    return {"url": url, "width": 48, "height": 48, "anchorY": 24}


SAVED = Path(__file__).with_name("last_real_run.pkl")  # results of the last real run
EXAMPLE = "Real example (bundled snapshot)"
REAL = "Israel MoT feed (real data)"
LIVE = "Live lookup of one line (Stride API)"
UPLOAD = "Upload a GTFS zip"

def set_example(name: str) -> None:  # runs before the rerun, so the new choice is used immediately
    st.session_state["example"] = name


# --------------------------------------------------------------------------- data access
with st.sidebar:
    st.subheader("Data source")
    source = st.radio("Source", [EXAMPLE, REAL, LIVE, UPLOAD], index=0, label_visibility="collapsed")
    example_name = st.session_state.get("example", next(iter(EXAMPLE_NOTES)))
    upload = st.file_uploader("GTFS .zip", type="zip") if source == UPLOAD else None
    clicked = False
    if source == LIVE:
        live_number = st.text_input("Line number", value="1")
        if st.button("Look up"):
            st.session_state["live_number"] = live_number
    if source == REAL:
        clicked = st.button("Re-download latest feed" if SAVED.exists() else "Download and analyze")
    st.subheader("Options")
    use_stride = st.checkbox("Weight by real rides per day", help="Uses the Open Bus Stride API. "
                             "Falls back to GTFS trip counts if the API has no usable data.")
    if source == REAL and SAVED.exists():
        st.caption("Showing your last saved run.")


@st.cache_data
def national_summary():
    return load_national_summary()


@st.cache_data
def examples():
    return load_examples()


@st.cache_data(show_spinner="Fetching ride counts...", ttl=3600)
def get_rides():
    return stride_rides()


@st.cache_data(show_spinner="Asking the Stride API (a few requests per route)...", ttl=3600)
def live(number):
    return lookup_line(number)


@st.cache_data(show_spinner="Processing GTFS (the national feed can take a few minutes)...")
def process(kind, data=None, weighted=False):
    rides = get_rides() if weighted else None
    if weighted and rides is None:
        st.warning("The Stride API had no usable ride counts, so GTFS trip counts are used instead.")
    if kind == "upload":
        z = zipfile.ZipFile(io.BytesIO(data))
    else:
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL).read()))
    return run(z, rides)


result = None
try:
    if source == EXAMPLE:
        result = examples()[example_name]
    elif source == REAL:
        if clicked:
            process.clear()  # force a fresh download
            result = process("download", weighted=use_stride)
            with open(SAVED, "wb") as f:
                pickle.dump(result, f)
        elif SAVED.exists():
            with open(SAVED, "rb") as f:
                result = pickle.load(f)
    elif source == LIVE:
        if st.session_state.get("live_number"):
            result = live(st.session_state["live_number"])
            if result is None:
                st.error(f"No routes found for line {st.session_state['live_number']} on a recent weekday.")
                st.stop()
    elif source == UPLOAD and upload:
        result = process("upload", upload.getvalue(), use_stride)
except Exception as exc:  # network or parsing problems
    st.error(f"Could not load the data: {exc}")
    st.caption("If the download keeps failing, download the GTFS zip from the Ministry of Transport "
               "and use 'Upload a GTFS zip'.")
    st.stop()

# --------------------------------------------------------------------------- header
badge = '<span class="tl-badge tl-real">● Real data</span>'
st.title("Twin Lines")
st.markdown(f'<p class="tl-sub">Where the same bus number means two different routes. &nbsp;{badge}</p>',
            unsafe_allow_html=True)
if source == EXAMPLE:
    st.markdown("### Two real cases from the Israeli feed")
    cols = st.columns(len(EXAMPLE_NOTES))
    for col, (name, note) in zip(cols, EXAMPLE_NOTES.items()):
        chosen = name == example_name
        with col:
            st.markdown(f'<div class="tl-card" style="border-color:{"#3f8cff" if chosen else "#3a3e42"}">'
                        f'<h4>{html.escape(name)}</h4><p style="color:#c5c8cc;font-size:.9rem;margin:0">'
                        f'{html.escape(note)}</p></div>', unsafe_allow_html=True)
            st.button("Showing on map" if chosen else "Show on map", key=f"ex-{name}",
                      on_click=set_example, args=(name,), disabled=chosen)
    national = national_summary()
    with st.expander(f"All {len(national)} colliding line numbers nationwide (real run)"):
        st.dataframe(national.rename(columns={"route_short_name": "Line", "shared_cells": "Shared areas",
                                              "max_agencies": "Max operators in an area", "operators": "Operators",
                                              "trips": "Trips in feed", "impact": "Impact"}), hide_index=True)
    st.caption("Data: snapshot of the Israel Ministry of Transport GTFS feed, November 2026.")

if result is None:
    msg = {REAL: "Click **Download and analyze** in the sidebar to load the real Israel feed. The first run "
                 "takes a few minutes; after that your results are saved and open instantly.",
           LIVE: "Type a line number in the sidebar and click **Look up**.",
           UPLOAD: "Upload a GTFS zip in the sidebar."}[source]
    st.info(msg)
    st.stop()

summary, cells, lines = result
if summary.empty:
    st.success("No collisions found: no line number is reused by different operators in the same area.")
    st.stop()

weighted_by = "real rides per day" if "rides_per_day" in summary.columns else "trips in the GTFS feed"
worst = summary.iloc[0]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Colliding line numbers", f"{len(summary):,}")
k2.metric("Shared map areas", f"{int(summary.shared_cells.sum()):,}")
k3.metric("Operators involved", f"{lines.agency_name.nunique():,}")
k4.metric("Top collision", f"Line {worst.route_short_name}", f"{int(worst.shared_cells)} shared areas",
          delta_color="off")

tab_map, tab_rank, tab_method = st.tabs(["Route explorer", "Ranking", "Method"])

# --------------------------------------------------------------------------- route explorer
with tab_map:
    c1, c2, c3 = st.columns(3)
    agency = c1.selectbox("Operating company", sorted(lines.agency_name.unique()))
    mine = lines[lines.agency_name == agency]
    rank = {n: i for i, n in enumerate(summary.route_short_name)}
    number = c2.selectbox("Line number", sorted(mine.route_short_name.unique(), key=lambda n: rank[n]),
                          help="Worst collisions first.")

    def label(g):
        g = g.sort_values("stop_sequence")
        name = g.route_long_name.iloc[0] or f"{g.stop_name.iloc[0]} → {g.stop_name.iloc[-1]}"
        return f"{name}  ({g.n_trips.iloc[0]} trips)"

    opts = {rid: label(g) for rid, g in mine[mine.route_short_name == number].groupby("route_id")}
    rid = c3.selectbox(f"Route ({len(opts)} options)", list(opts), format_func=opts.get)

    sel = lines[lines.route_id == rid].sort_values("stop_sequence")
    others = lines[(lines.route_short_name == number) & (lines.agency_name != agency)]
    hot = cells[cells.route_short_name == number]
    palette = [[230, 57, 70], [40, 170, 90], [240, 170, 20], [150, 80, 200], [0, 170, 190]]
    other_agencies = sorted(others.agency_name.unique())
    color = {ag: palette[i % len(palette)] for i, ag in enumerate(other_agencies)}
    BLACK = [20, 20, 20]

    other_paths = [{"name": f"{ag} · {g.route_long_name.iloc[0] or r2}", "color": color[ag],
                    "path": g[["stop_lon", "stop_lat"]].values.tolist()}
                   for (ag, r2), g in others.groupby(["agency_name", "route_id"]) if len(g) > 1]
    sel_path = [{"name": f"{agency} · {opts[rid]}", "color": BLACK,
                 "path": sel[["stop_lon", "stop_lat"]].values.tolist()}]
    stops = sel.assign(name=sel.stop_name)[["name", "stop_lon", "stop_lat"]].copy()
    stops["icon_data"] = [icon(BUS_ICON)] * len(stops)

    arrows = []  # direction arrows at the middle of each segment
    pts = sel[["stop_lon", "stop_lat"]].values
    for (lo1, la1), (lo2, la2) in zip(pts[:-1], pts[1:]):
        if (lo1, la1) == (lo2, la2):
            continue
        brg = math.degrees(math.atan2((lo2 - lo1) * math.cos(math.radians(la1)), la2 - la1))
        arrows.append({"lon": (lo1 + lo2) / 2, "lat": (la1 + la2) / 2, "text": "▲", "angle": -brg})
    arrows = pd.DataFrame(arrows, columns=["lon", "lat", "text", "angle"])
    ends = pd.DataFrame([
        {"lon": float(sel.stop_lon.iloc[0]), "lat": float(sel.stop_lat.iloc[0]),
         "name": "Start: " + sel.stop_name.iloc[0], "icon_data": icon(START_ICON)},
        {"lon": float(sel.stop_lon.iloc[-1]), "lat": float(sel.stop_lat.iloc[-1]),
         "name": "End: " + sel.stop_name.iloc[-1], "icon_data": icon(END_ICON)}])

    span = max(float(sel.stop_lat.max() - sel.stop_lat.min()), float(sel.stop_lon.max() - sel.stop_lon.min()))
    zoom = 13 if span < 0.03 else 11 if span < 0.15 else 9 if span < 0.6 else 8 if span < 1.2 else 7

    left, right = st.columns([4, 1])
    with left:
        legend = (f'<div class="tl-legend"><img src="{BUS_ICON}" width="18" style="vertical-align:middle"> '
                  f'<b>Planned route</b> · {html.escape(agency)}')
        for ag in other_agencies:
            r, g_, b = color[ag]
            legend += (f'<br><span style="display:inline-block;width:18px;height:4px;background:rgb({r},{g_},{b});'
                       f'vertical-align:middle"></span> Same number, {html.escape(ag)}')
        legend += ('<br><span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
                   'background:rgba(255,220,0,.6);vertical-align:middle"></span> Shared area</div>')
        st.markdown(legend, unsafe_allow_html=True)
        deck = pdk.Deck(
            map_style="road",
            layers=[
                pdk.Layer("ScatterplotLayer", hot, get_position="[lon, lat]", get_radius=300,
                          get_fill_color=[255, 220, 0, 110]),
                pdk.Layer("PathLayer", other_paths, get_path="path", get_color="color", width_min_pixels=3),
                pdk.Layer("PathLayer", sel_path, get_path="path", get_color="color", width_min_pixels=4),
                pdk.Layer("TextLayer", arrows, get_position="[lon, lat]", get_text="text", get_angle="angle",
                          get_size=16, get_color=[20, 20, 20]),
                pdk.Layer("IconLayer", stops, get_icon="icon_data", get_position="[stop_lon, stop_lat]",
                          get_size=22, pickable=True),
                pdk.Layer("IconLayer", ends, get_icon="icon_data", get_position="[lon, lat]",
                          get_size=30, pickable=True),
            ],
            initial_view_state=pdk.ViewState(latitude=float(sel.stop_lat.mean()),
                                             longitude=float(sel.stop_lon.mean()), zoom=zoom),
            tooltip={"text": "{name}"})
        try:
            st.pydeck_chart(deck, height=650)
        except TypeError:  # older Streamlit versions have no height argument
            st.pydeck_chart(deck)

    with right:
        row = summary[summary.route_short_name == number].iloc[0]
        facts = [("Operator", agency), ("From", sel.stop_name.iloc[0] or "—"),
                 ("Destination", sel.stop_name.iloc[-1] or "—"), ("Stops", len(sel)),
                 ("Trips in feed", f"{int(sel.n_trips.iloc[0]):,}"),
                 ("Also used by", ", ".join(other_agencies) or "—"),
                 ("Shared areas", int(row.shared_cells)),
                 ("Collision rank", f"{rank[number] + 1} of {len(summary)}"),
                 ("Impact score", f"{int(row.impact):,}")]
        rows = "".join(f'<div class="tl-row"><span>{k}</span><span>{html.escape(str(v))}</span></div>'
                       for k, v in facts)
        st.markdown(f'<div class="tl-card"><h4>Line {html.escape(str(number))}</h4>{rows}</div>',
                    unsafe_allow_html=True)

# --------------------------------------------------------------------------- ranking
with tab_rank:
    st.caption(f"Ranked by shared areas × {weighted_by}.")
    names = {"route_short_name": "Line", "shared_cells": "Shared areas", "max_agencies": "Max operators in an area",
             "operators": "Operators", "trips": "Trips in feed", "rides_per_day": "Rides per day",
             "impact": "Impact"}
    table = summary.rename(columns=names)
    st.bar_chart(table.head(10).set_index("Line")["Impact"])
    st.dataframe(table, hide_index=True)
    st.download_button("Download CSV", summary.to_csv(index=False), "twin_lines_collisions.csv",
                       mime="text/csv")

# --------------------------------------------------------------------------- method
with tab_method:
    st.markdown(f"""
**Question.** When two operators run a line with the same number in the same neighbourhood, passengers can
board the wrong bus. Twin Lines finds those cases in Israel's public transport data.

**Data.** Planned timetables in GTFS format from the Israel Ministry of Transport. Optionally, real planned
rides per day from the Open Bus Stride API (Public Knowledge Workshop).

**Method.**
1. Take one representative trip per route and its ordered stops.
2. Snap every stop to a grid of roughly 500 m squares.
3. A *collision* is a line number that appears in the same square under two or more operators.
4. **Impact** = shared squares × weight, where the weight is currently *{weighted_by}*. Busy lines that clash over
   a wide area rank first.

**Limitations.**
- One trip per route is a simplification: a line can have several variants.
- Two operators running the *same corridor* (for example one in each direction, or as subcontractors) can also be
  flagged. Comparing the routes' end points would separate these from truly different routes.
- A grid is approximate. Two nearby stops can fall in different squares.
- Trip counts cover all service days in the feed, so they are a frequency proxy, not trips per day.
- Routes are drawn as straight segments between stops, not along the road (GTFS `shapes.txt` could improve this).
- The tool detects number overlap, not whether passengers are actually confused.

**Next steps.** Stop-to-stop distance checks, per-weekday counts from `calendar.txt`, real route shapes, and
clustering lines into regions.
""")
