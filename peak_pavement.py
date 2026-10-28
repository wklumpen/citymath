"""Pavement per person by community, at each community's peak population and in 2019.

    uv run peak_pavement.py            # query the database, fill the table, draw the slides
    uv run peak_pavement.py --cached   # redraw from slides/data/ without the database

Reads peak_pavement_pop.csv (community, peak population and year, 2019 population).
Pavement is every road in the analysis (all classes, paved, City-maintained, widths as in
the website's method) that lies inside the community boundary. Writes:
  slides/data/community_pavement.csv   m2 of pavement per community, from the database
  slides/data/community_shapes.geojson community outlines for the maps
  slides/out/peak_pavement_pop_filled.csv  the input table with the blank columns filled in
  slides/out/peak_map_{peak,2019}_{wide,square}.png   two maps on one colour scale
  slides/out/peak_chart_change_*.png, peak_city_*.png  the ten biggest changes, and the whole city
"""
import csv
import json
import sys

import altair as alt
import pandas as pd
import yaml
from dotenv import load_dotenv

import citymath
import slides
from slides import BAND, BODY, DISPLAY, INK, MUTED, ROOT, SPECIAL, rings_clockwise, save

DATA = ROOT / "slides" / "data"
OUT = slides.OUT
MIN_POP = 500  # below this, pavement per person says more about a few residents than about the street

# Names in peak_pavement_pop.csv that differ from the City's community boundaries.
ALIAS = {"MACEWAN": ["MACEWAN GLEN"], "PARKHILL/STANLEY PARK": ["PARKHILL"],
         "FOREST LAWN - INDUSTRIAL": ["FOREST LAWN INDUSTRIAL"],
         "SCARBORO/SUNALTA WEST": ["SCARBORO/ SUNALTA WEST"],
         "RED CARPET/MOUNTVIEW MOBILE PARK": ["RED CARPET"],
         "CHARLESWOOD/COLLINGWOOD*": ["CHARLESWOOD", "COLLINGWOOD"]}
# Counted together with their neighbour for the peak year only.
PEAK_EXTRA = {"ALTADORE": ["GARRISON WOODS"]}
SKIP = {"COLLINGWOOD*"}  # the combined Charleswood/Collingwood row covers it
# Peak is for the pair together, so 2019 is the sum of both rows.
POP_2019_SUM = {"CHARLESWOOD/COLLINGWOOD*": ["CHARLESWOOD/COLLINGWOOD*", "COLLINGWOOD*"]}
# Left out of the charts: 2019 population looks like a data-entry error (peak 19,223 in 2015, 1,900 in 2019).
SUSPECT = {"TARADALE"}

# One scale for both maps: m2 of pavement per person.
BREAKS = [30, 40, 50, 65, 100]
LABELS = ["Under 30", "30–40", "40–50", "50–65", "65–100", "100 or more", f"Under {MIN_POP:,} residents"]
RAMP = ["#fbe3c8", "#f6c08a", "#ee9a4e", "#d1611a", "#9a3f0c", "#5a2306", SPECIAL]


def query():
    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    out = cfg["output"]
    db = citymath.connect(out["database"], out["schema"])
    rows = db.execute("""
        select m.name, max(m.comm_structure) as structure,
               sum(ST_Length(ST_Intersection(r.geom, m.geom))
                   * coalesce(case when r.road_class = 'residential' then w.width_median end, k.width_m)) as m2
        from src_community m
        left join road_used r on ST_Intersects(r.geom, m.geom)
        left join cfg_road_class k on k.road_class = r.road_class
        left join comm_structure_width w on w.comm_structure = m.comm_structure
        group by m.comm_code, m.name, m.geom order by m.name""").fetchall()
    pd.DataFrame(rows, columns=["name", "structure", "m2"]).to_csv(DATA / "community_pavement.csv", index=False)
    shapes = db.execute("""
        select name, ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 15), 4326), 5)
        from src_community order by name""").fetchall()
    feats = [{"type": "Feature", "properties": {"name": n}, "geometry": json.loads(g)} for n, g in shapes]
    (DATA / "community_shapes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def table():
    cp = pd.read_csv(DATA / "community_pavement.csv").set_index("name")
    pav, structure = cp["m2"].fillna(0), cp["structure"]
    rows = []
    with open(ROOT / "peak_pavement_pop.csv", newline="") as f:
        raw = list(csv.DictReader(f))
        pop19 = {r["Community"]: float(r["Population (2019)"] or 0) for r in raw}
        for r in raw:
            name = r["Community"]
            if not name or name in SKIP or not r["Peak Population"]:
                continue
            names = ALIAS.get(name, [name])
            if not set(names) <= set(pav.index):
                print(f"  no boundary for {name}")
                continue
            peak = float(r["Peak Population"])
            now = sum(pop19[n] for n in POP_2019_SUM.get(name, [name]))
            m2 = float(sum(pav[n] for n in names))
            m2_peak = m2 + float(sum(pav[n] for n in PEAK_EXTRA.get(name, [])))
            rows.append({"community": name, "shapes": names, "structure": structure[names[0]], "peak_year": int(r["Year"]), "peak_pop": peak,
                         "pop_2019": now, "m2": m2, "m2_peak": m2_peak,
                         "pp_peak": m2_peak / peak if peak >= MIN_POP else None,
                         "pp_2019": m2 / now if now >= MIN_POP else None})
    return pd.DataFrame(rows)


def write_filled(df):
    """The input table with pavement and the two per-person columns filled in."""
    src = pd.read_csv(ROOT / "peak_pavement_pop.csv", dtype=str).fillna("")
    cols = list(src.columns)
    by = df.set_index("community")
    for i, r in src.iterrows():
        row = by.loc["CHARLESWOOD/COLLINGWOOD*"] if r["Community"] == "COLLINGWOOD*" else by.loc[r["Community"]] \
            if r["Community"] in by.index else None
        if row is None:
            continue
        src.loc[i, cols[1]] = f"{row['m2_peak']:.0f}"
        src.loc[i, cols[4]] = "" if pd.isna(row["pp_peak"]) else f"{row['pp_peak']:.1f}"
        src.loc[i, cols[6]] = "" if pd.isna(row["pp_2019"]) else f"{row['pp_2019']:.1f}"
    src.rename(columns={cols[1]: "Pavement area (m2)"}).to_csv(OUT / "peak_pavement_pop_filled.csv", index=False)


def klass(v):
    return 6 if v is None or pd.isna(v) else sum(v >= b for b in BREAKS)


def map_chart(df, shapes, which):
    col, pop = ("pp_peak", "peak_pop") if which == "peak" else ("pp_2019", "pop_2019")
    k = {}
    for _, r in df.iterrows():
        for n in r["shapes"]:
            k[n] = (klass(r[col]), r[col])
    feats = [{"type": "Feature", "geometry": rings_clockwise(f["geometry"]),
              "properties": {"k": LABELS[k.get(f["properties"]["name"], (6, None))[0]]}}
             for f in shapes["features"]]
    data = alt.Data(values=feats)

    def chart(shape):
        legend = alt.Legend(title="Road pavement per resident (m²)" if shape == "wide" else None,
                            orient="right" if shape == "wide" else "bottom", titleFontSize=18, titlePadding=12,
                            titleLimit=600, columns=1 if shape == "wide" else 2, labelLimit=460,
                            symbolType="square", symbolStrokeWidth=0, rowPadding=6, columnPadding=18,
                            labelFontSize=17 if shape == "wide" else 13)
        return alt.Chart(data).mark_geoshape(stroke="#ffffff", strokeWidth=0.5).encode(
            color=alt.Color("properties.k:N", scale=alt.Scale(domain=LABELS, range=RAMP), legend=legend)
        ).project(type="mercator")

    ok = df[col].notna()
    med = df.loc[ok, col].median()
    title = ("Pavement per person at peak population" if which == "peak"
             else "Pavement per person today")
    sub = ("Square metres of road per resident, in the year each community had the most people" if which == "peak"
           else "Square metres of road per resident, using 2019 populations") + f" · median {med:,.0f} m²"
    save(chart, f"peak_map_{which}", title, sub)


def change_chart(df, name, title, subtitle):
    """Ten biggest rises in pavement per person, peak to 2019, labelled with the % change."""
    d = df[~df["community"].isin(SUSPECT)].dropna(subset=["pp_peak", "pp_2019"]).copy()
    d["change"] = d["pp_2019"] / d["pp_peak"] - 1
    top = d.sort_values("change", ascending=False).head(10).copy()
    top["label"] = [f"{c.title().rstrip('*').replace('/', ' / ')} ({int(y)})" for c, y in zip(top["community"], top["peak_year"])]
    order = list(top["label"])
    long = pd.concat([top.assign(when="At peak population", v=top["pp_peak"]),
                      top.assign(when="2019", v=top["pp_2019"])])
    top["lx"] = top[["pp_peak", "pp_2019"]].max(axis=1)
    top["note"] = [f"{c:+.0%}" for c in top["change"]]

    def chart(shape):
        wide = shape == "wide"
        y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=420, labelFontSize=15 if wide else 12))
        x = alt.X("v:Q", title="Square metres of road per resident", scale=alt.Scale(zero=True))
        colour = alt.Color("when:N", scale=alt.Scale(domain=["At peak population", "2019"], range=[slides.GOOD, slides.BAD]),
                           legend=alt.Legend(title=None, orient="top", labelFontSize=15, labelLimit=400, symbolType="circle"))
        line = alt.Chart(top).mark_rule(color=slides.LINE, strokeWidth=3).encode(y=y, x="pp_peak:Q", x2="pp_2019:Q")
        pts = alt.Chart(long).mark_circle(size=230 if wide else 140, opacity=1).encode(y=y, x=x, color=colour)
        lab = alt.Chart(top).mark_text(align="left", dx=12, fontSize=17 if wide else 13, fontWeight=600,
                                       color=INK, font=BODY).encode(y=y, x="lx:Q", text="note:N")
        return alt.layer(line, pts, lab)

    save(chart, name, title, subtitle)
    return top


def city_chart(df):
    """The whole city: total pavement over total residents, at each community's peak and in 2019."""
    d = df[~df["community"].isin(SUSPECT)].dropna(subset=["pp_peak", "pp_2019"])
    peak = d["m2_peak"].sum() / d["peak_pop"].sum()
    now = d["m2"].sum() / d["pop_2019"].sum()
    rows = pd.DataFrame({"when": ["At peak population", "2019"], "v": [peak, now], "row": "All communities",
                         "note": [f"{peak:.1f} m²", f"{now:.1f} m² ({now / peak - 1:+.0%})"]})
    print(f"  city: {peak:.1f} -> {now:.1f} m2 per person over {len(d)} communities ({now / peak - 1:+.1%})")

    def chart(shape):
        wide = shape == "wide"
        y = alt.Y("when:N", sort=list(rows["when"]), title=None,
                  axis=alt.Axis(labelLimit=300 if wide else 160, labelFontSize=18 if wide else 14, labelPadding=10))
        x = alt.X("v:Q", title="Square metres of road per resident", scale=alt.Scale(zero=True, domain=[0, max(peak, now) * 1.45]))
        colour = alt.Color("when:N", scale=alt.Scale(domain=list(rows["when"]), range=[slides.GOOD, slides.BAD]), legend=None)
        bars = alt.Chart(rows).mark_bar(size=110 if wide else 90, cornerRadiusEnd=4).encode(y=y, x=x, color=colour)
        lab = alt.Chart(rows).mark_text(align="left", dx=12, fontSize=26 if wide else 18, fontWeight=700, color=INK,
                                        font=BODY).encode(y=y, x="v:Q", text="note:N")
        return alt.layer(bars, lab)

    save(chart, "peak_city", "Each resident now has more road to maintain",
         f"Square metres of road per resident across {len(d)} communities, each at its own peak population vs 2019")


def structure_chart(df):
    """Pavement per resident by type of neighbourhood: total pavement over total residents."""
    d = df[~df["community"].isin(SUSPECT)].dropna(subset=["pp_peak", "pp_2019"])
    g = d.groupby("structure").agg(n=("community", "size"), m2_peak=("m2_peak", "sum"), peak_pop=("peak_pop", "sum"),
                                   m2=("m2", "sum"), pop_2019=("pop_2019", "sum")).reset_index()
    g["pp_peak"], g["pp_2019"] = g["m2_peak"] / g["peak_pop"], g["m2"] / g["pop_2019"]
    g["change"] = g["pp_2019"] / g["pp_peak"] - 1
    g = g[g["structure"].isin(slides.ORDER[:7]) & (g["n"] >= 5)].copy()  # age groups with at least 5 communities
    g["rank"] = g["structure"].map({s: i for i, s in enumerate(slides.ORDER)})
    g = g.sort_values("rank").reset_index(drop=True)
    g["label"] = [f"{slides.NICE.get(s, s)} ({n})" for s, n in zip(g["structure"], g["n"])]
    g["lx"] = g[["pp_peak", "pp_2019"]].max(axis=1)
    g["note"] = [f"{c:+.0%}" for c in g["change"]]
    print(g[["structure", "n", "pp_peak", "pp_2019", "change"]].round(2).to_string())
    order = list(g["label"])
    long = pd.concat([g.assign(when="At peak population", v=g["pp_peak"]), g.assign(when="2019", v=g["pp_2019"])])

    def chart(shape):
        wide = shape == "wide"
        y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=420, labelFontSize=17 if wide else 13))
        x = alt.X("v:Q", title="Square metres of road per resident", scale=alt.Scale(zero=True))
        colour = alt.Color("when:N", scale=alt.Scale(domain=["At peak population", "2019"], range=[slides.GOOD, slides.BAD]),
                           legend=alt.Legend(title=None, orient="top", labelFontSize=15, labelLimit=400, symbolType="circle"))
        line = alt.Chart(g).mark_rule(color=slides.LINE, strokeWidth=4).encode(y=y, x="pp_peak:Q", x2="pp_2019:Q")
        pts = alt.Chart(long).mark_circle(size=300 if wide else 180, opacity=1).encode(y=y, x=x, color=colour)
        lab = alt.Chart(g).mark_text(align="left", dx=14, fontSize=20 if wide else 14, fontWeight=600, color=INK,
                                     font=BODY).encode(y=y, x="lx:Q", text="note:N")
        return alt.layer(line, pts, lab)

    save(chart, "peak_structure", "Pavement per resident by type of neighbourhood",
         "Square metres of road per resident, at each community's peak population and in 2019 (number of communities)")


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if "--cached" not in sys.argv:
        query()
    df = table()
    shapes = json.loads((DATA / "community_shapes.geojson").read_text())
    write_filled(df)
    print(f"{len(df)} communities, {df['m2'].sum() / 1e6:.1f} km2 of pavement")
    map_chart(df, shapes, "peak")
    map_chart(df, shapes, "2019")
    t = change_chart(df, "peak_chart_change", "Where pavement per resident grew the most",
                     "Square metres of road per resident at each community's peak population and in 2019, with the % change")
    print(t[["community", "peak_year", "peak_pop", "pop_2019", "pp_peak", "pp_2019", "change"]].round(2).to_string())
    city_chart(df)
    structure_chart(df)


if __name__ == "__main__":
    main()
