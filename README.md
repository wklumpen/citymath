# CityMath: do Calgary's streets pay for themselves?

For each cell of an 800 m hex grid over Calgary, this compares the municipal
property tax raised with the cost of the road pavement inside it.

## What it does

`citymath.py` runs six steps against a PostGIS database. The spatial work is
plain SQL in `sql/`; every assumption is in `config.yaml`.

| Step | What it produces |
|---|---|
| `load` | Staging copies of the hex grid, communities, wards, OSM roads and the assessment roll |
| `community` | Each hex tagged with the community its centroid falls in, plus the mix of community structures by area, the ward (also by centroid), and dissolved hex outlines per community and per ward |
| `roads` | Length of City-maintained, paved road per hex by class |
| `assessments` | Assessed value per hex by class, allocated from parcels by area, with tax-exempt property removed |
| `summary` | `hex_summary` (one row per hex), `hex_scenario` (one row per hex per pavement scenario) and `ward_scenario` (ward totals per scenario) |
| `export` | `docs/data/hexes.geojson`, `wards.geojson` and `scenarios.json`, the files the website reads |

## Method in brief

- **Revenue**: assessed value times the municipal tax rate, by assessment
  class. A parcel straddling hexes is split between them by area. Institutional
  and recreation properties are treated as exempt, which brings the total within
  about 1% of the City's reported 2025 figure.
- **Road cost**: OSM road length by class, times a width, times a cost per
  square metre. Residential widths come from sampled street measurements by
  community structure. Reconstruction cost is spread over a per-class life;
  repaving and crack sealing are flat annual rates.
- **Shared roads**: highways and arterials can be pooled citywide and spread
  across hexes instead of charged to the hex they sit in.
- Roads only: pipes, transit, parks and other services are not included.

## Running it

Needs [uv](https://docs.astral.sh/uv/) and a PostGIS server holding the source
tables named in `config.yaml`.

    cp .env.example .env        # add the database password
    uv run citymath.py          # all steps
    uv run citymath.py summary  # just re-run some steps after a config change

`load_assessment_csv.py` loads a City of Calgary "Historical Property
Assessments (Parcel)" CSV into the spatial database.

## Website

`docs/` is a static site served by GitHub Pages. Preview it locally with
`python3 -m http.server -d docs`.

- `index.html`, the landing page: why the site exists, how the City's budget
  and the property tax work, and links to the deep dives. Its budget diagrams
  read `data/budget.json`, which `uv run budget.py` builds from the City's open
  budget data and the figures and groupings in `budget.yaml`.
- `roads.html`, the roads deep dive: pavement condition and spending history,
  the gap, whether property tax can close it, the map and the methods. It reads
  `data/scenarios.json`, `data/hexes.geojson` and `data/wards.geojson`, and
  recomputes road cost in the browser as the reader changes the plan. The
  history and the City's proposed 2027-2030 pavement budget are typed in, with
  their sources, in `pavement.yaml`; `uv run pavement.py` writes
  `data/pavement.json`.
- `downloads/`: the spreadsheets readers can check our numbers with.
  `uv run downloads.py` writes them from the files above, with the same
  formulas as the pages. Re-run it after any of the other scripts.
- `pay.html` and `methods.html` only redirect to the pages above, so old links
  keep working.

Source data (the hex grid, assessment rolls and street width samples) is not
included in this repository; only the derived per-hex file for the website is.

## Slide images

`uv run slides.py` renders PNGs for presentations from the same
`docs/data/` files as the website, with the same math, into `slides/out/`
(not committed). Pass plan ids (e.g. `uv run slides.py recommended`) to limit
the per-plan charts. Each chart comes as `_wide.png` (1920x1080, with a title)
and `_square.png` (1080x1080, untitled, for text beside it):

- `plans_cost`, `plans_tax`, `plans_hexes`: every plan side by side
- `neighbourhoods_<plan>`: cents per tax dollar by type of neighbourhood
- `map_<plan>`: the hexagon map

Charts are drawn with Altair and rendered with vl-convert, using the site's
fonts (Archivo and Source Sans 3, SIL Open Font License) from `slides/fonts/`.

### Pavement per person by community

`uv run peak_pavement.py` reads `peak_pavement_pop.csv` (peak and 2019
populations by community), measures the pavement inside each community
boundary from the database, and writes two maps on one colour scale (peak
population and 2019), a "biggest rises" chart, a whole-city comparison, and a filled-in copy of
the table to `slides/out/`. `--cached` redraws from `slides/data/` without the
database. Not part of the website.
