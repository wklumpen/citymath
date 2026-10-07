# CityMath: do Calgary's streets pay for themselves?

For each cell of an 800 m hex grid over Calgary, this compares the municipal
property tax raised with the cost of the road pavement inside it.

## What it does

`citymath.py` runs six steps against a PostGIS database. The spatial work is
plain SQL in `sql/`; every assumption is in `config.yaml`.

| Step | What it produces |
|---|---|
| `load` | Staging copies of the hex grid, communities, OSM roads and the assessment roll |
| `community` | Each hex tagged with the community its centroid falls in, plus the mix of community structures by area and dissolved hex outlines per community |
| `roads` | Length of City-maintained, paved road per hex by class |
| `assessments` | Assessed value per hex by class, allocated from parcels by area, with tax-exempt property removed |
| `summary` | `hex_summary` (one row per hex) and `hex_scenario` (one row per hex per pavement scenario) |
| `export` | `docs/data/hexes.geojson`, the per-hex file the website reads |

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

`docs/` is a static site served by GitHub Pages: `index.html` reads
`data/hexes.geojson` and recomputes road cost in the browser as the reader
changes the scenario. Preview it locally with
`python3 -m http.server -d docs`.

Source data (the hex grid, assessment rolls and street width samples) is not
included in this repository; only the derived per-hex file for the website is.
