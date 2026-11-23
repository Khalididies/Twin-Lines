# Twin Lines

**Where the same bus number means two different routes.**

Twin Lines finds bus line numbers that different operators reuse in the same part of Israel, ranks them by how
much they matter, and shows them on a map. It was inspired by the principle that a line number should never
repeat within close geographic range, as in the Paris network.

<!-- Add a screenshot: ![Twin Lines](docs/screenshot.png) -->

## Features

- **Whole-country analysis** of the Israel Ministry of Transport GTFS feed (millions of stop-time rows, read in chunks).
- **Impact ranking:** shared areas × weight, so busy lines that clash widely come first.
- **Route explorer:** pick an operator, a line and a route variant; see the planned route with stops, direction
  arrows, the other operators using the same number, and the shared areas.
- **Live lookup** of a single line through the Open Bus Stride API, with no large download.
- **Real ride counts** per day from the Stride API as an optional weight, with an automatic fallback to GTFS trip counts.
- **CSV export**, command-line mode, and a fictional demo dataset for quick checks.
- **Two real examples bundled** (`sample_data/`), so the app shows real routes without any download.
- Offline unit tests and CI.

## Real examples

The repository includes a small snapshot of real routes from the Israel Ministry of Transport feed (November 2026):

- **Line 240, Bnei Brak:** Kavim's line goes to Modi'in Illit and Dan's goes to Holon. They serve the same stop
  area, and their terminals are about 28 km apart.
- **Line 3, Haifa Bay:** Egged's line 3 runs in Haifa and Superbus's line 3 runs at the Krayot central station.
  They share a stop area, but the routes are about 14 km apart.

The app opens on these two cases, with the nationwide ranking of all 20 colliding line numbers from the
same real run (`sample_data/national_summary.csv`). Use *Show on map* to switch between them.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

In the app choose **Israel MoT feed (real data)** and click *Download and analyze*. The first run takes a few
minutes. The results are then saved to `last_real_run.pkl`, so later launches open instantly.

Command line:

```bash
python gtfs_collisions.py --demo      # fictional sample data, 10-second sanity check
python gtfs_collisions.py             # real feed -> collisions.csv
python gtfs_collisions.py --stride    # weight by real rides per day
python gtfs_collisions.py --zip feed.zip
```

If the automatic download fails, download the GTFS zip from the Ministry of Transport and use `--zip` or the
app's *Upload a GTFS zip* option.

## How it works

1. Take one representative trip per route and its ordered stops.
2. Snap each stop to a grid of roughly 500 m squares.
3. A **collision** is a line number that appears in the same square under two or more operators.
4. **Impact** = shared squares × weight (planned rides per day if available, otherwise trips in the feed).

## Data sources

- Israel Ministry of Transport, GTFS timetables.
- Open Bus Stride API, The Public Knowledge Workshop (`/gtfs_rides_agg/group_by` and the GTFS endpoints).

## Project structure

| Path | Purpose |
|---|---|
| `gtfs_collisions.py` | Analysis: `run` (whole country), `lookup_line` (one line), `collide` (core logic) |
| `app.py` | Streamlit interface |
| `tests/` | Offline unit tests (`pytest`) |
| `sample_data/` | Bundled real examples (CSV) |
| `.streamlit/config.toml` | Dark theme |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Limitations

- One trip per route represents a line that may have several variants.
- The same corridor run by two operators (for example in opposite directions) can also be flagged; comparing
  route end points would separate these from truly different routes.
- A grid is approximate: close stops can fall in different squares.
- Trip counts cover every service day in the feed and are only a frequency proxy.
- Routes are drawn as straight segments between stops, not along the road.
- The tool detects number overlap, not whether passengers are actually confused.

## Roadmap

Stop-to-stop distance checks, per-weekday counts from `calendar.txt`, real route shapes from `shapes.txt`, and
clustering lines into geographic regions.

## License

MIT, see `LICENSE`.
