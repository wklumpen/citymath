#!/usr/bin/env python3
"""The spreadsheets readers can download to check our numbers.

    uv run downloads.py   # docs/data/*.json, hexes.geojson -> docs/downloads/*.csv

Reads only the files the website reads (run citymath.py, budget.py and pavement.py
first if they are stale) and works each plan out with the same formulas the pages
use, so a spreadsheet and the page always agree.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
OUT = ROOT / "docs" / "downloads"


def load(name):
    return json.loads((DATA / name).read_text())


def write(name, header, rows):
    # utf-8-sig so Excel opens accents and the dollar figures correctly
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {len(rows):>5} rows -> {(OUT / name).relative_to(ROOT)}")


def centre(geom):
    """Rough centre of a hexagon: the average of its outer corners."""
    ring = (geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0])[:-1]
    return round(sum(p[1] for p in ring) / len(ring), 5), round(sum(p[0] for p in ring) / len(ring), 5)


def roads():
    S = load("scenarios.json")
    H = [f["properties"] | {"geom": f["geometry"]} for f in load("hexes.geojson")["features"]]
    # each hexagon's pavement: its own local streets plus an equal slice of the shared main roads
    n, sh, shy = len(H), sum(h["m2_sh"] for h in H), sum(h["m2y_sh"] for h in H)
    if S["shared_basis"] != "equal":
        raise SystemExit("downloads.py only knows the 'equal' way of sharing main roads")
    for h in H:
        h["rev"] = h["rev_res"] + h["rev_com"]
        h["pm2"], h["pm2y"] = h["m2"] + sh / n, h["m2y"] + shy / n
    rev, pm2 = sum(h["rev"] for h in H), sum(h["pm2"] for h in H)

    def cost(h, sc):
        rate = (sc["low"] + sc["high"]) / 2
        if sc["kind"] == "budget":
            return rate * h["pm2"] / pm2
        return rate * (h["pm2y"] if sc["kind"] == "life" else h["pm2"])

    plans = S["scenarios"]
    city = {sc["id"]: sum(cost(h, sc) for h in H) for sc in plans}
    base, home = city[S["current"]], S["typical_home_value"] * S["res_rate"]

    write("calgary-hexagons.csv",
          ["Hexagon", "Community", "Community type", "Ward", "Special area", "Area (ha)", "Latitude", "Longitude",
           "Residential tax ($)", "Other tax ($)", "Total municipal tax ($)", "Mobility budget ($)",
           "Local pavement (m2)", "Share of main roads (m2)", "Pavement counted (m2)"]
          + [f"Road cost: {sc['label']} ($ a year)" for sc in plans],
          [[h["id"], h["name"], h["structure"], h["ward"], "yes" if h["special"] else "no", h["area_ha"],
            *centre(h["geom"]), h["rev_res"], h["rev_com"], h["rev"], round(h["rev"] * S["mobility_share"]),
            h["m2"], round(sh / n), round(h["pm2"])]
           + [round(cost(h, sc)) for sc in plans] for h in H])

    unit = {"budget": "$ a year citywide", "flat": "$ per m2 a year", "life": "$ per m2 to rebuild"}
    write("calgary-pavement-plans.csv",
          ["Plan", "Kind", "Low", "High", "Unit", "Cost a year citywide ($)", "Above the City's proposal ($)",
           "Property tax increase needed", "Extra a year, typical home ($)", "What it means", "Sources"],
          [[sc["label"], sc["kind"], sc["low"], sc["high"], unit[sc["kind"]], round(city[sc["id"]]),
            round(city[sc["id"]] - base), f"{max(0, city[sc['id']] - base) / rev:.2%}",
            round(max(0, city[sc["id"]] - base) / rev * home), sc["consequence"] or sc["summary"],
            "; ".join(f"{s['title']} <{s['url']}>" for s in sc["sources"])] for sc in plans])

    rows = []
    for ward in sorted({h["ward"] for h in H}):
        g = [h for h in H if h["ward"] == ward]
        r = sum(h["rev"] for h in g)
        for sc in plans:
            c = sum(cost(h, sc) for h in g)
            rows.append([ward, sc["label"], round(r), round(c), round(c / r * 100, 2),
                         f"{c / (r * S['mobility_share']):.0%}"])
    write("calgary-wards.csv", ["Ward", "Plan", "Municipal tax ($)", "Road cost ($ a year)",
                                "Cents of each tax dollar", "Share of the ward's mobility budget"], rows)


def pavement():
    P = load("pavement.json")
    years = sorted({r["year"] for k in ("good", "lane_km", "spending") for r in P[k]})
    get = {k: {r["year"]: r for r in P[k]} for k in ("good", "lane_km", "spending")}
    mob = {r["year"]: r for r in P["mobility_proposed"]}

    def cell(k, y, fmt=lambda v: v):
        r = get[k].get(y)
        return ("", "") if r is None else (fmt(r["value"]), "read off the City's chart" if r.get("read")
                                           else r.get("status", "printed in the report"))
    rows = []
    for y in years:
        g, l, s = cell("good", y, lambda v: f"{v:.1%}"), cell("lane_km", y), cell("spending", y)
        m = mob.get(y)
        rows.append([y, *g, *l, *s, P["break_even"], m["total"] if m else "",
                     f"{get['spending'][y]['value'] / m['total']:.1%}" if m else ""])
    write("calgary-pavement-history.csv",
          ["Year", "Roads in good condition", "How we got it", "Road network (lane-km)", "How we got it",
           "Pavement spending ($M)", "How we got it", "Break-even spending ($M)",
           "Mobility budget, proposed ($M)", "Pavement's share of Mobility"], rows)
    write("pavement-spending-per-lane-km.csv", ["City", "Annual pavement investment per lane-km, 2018 ($)", "How we got it"],
          [[c["city"], c["value"], "read off the City's chart"] for c in P["per_lane_km"]["cities"]]
          + [["Average of these cities", P["per_lane_km"]["average"], "printed in the report"]])


def budget():
    B = load("budget.json")
    rows = []
    for V in B["views"].values():
        N = {n["id"]: n for n in V["nodes"]}
        name = lambda i: N[i].get("label") or N[N[i]["ghost"]]["label"]
        # ghost nodes carry a service's own fees past the shared pot: skip the leg into the
        # ghost and name the leg out of it after where the money came from
        for l in V["links"]:
            if not N[l["t"]].get("ghost"):
                rows.append([f"{B['year']} {V['name']}", name(l["s"]), l.get("label") or name(l["t"]), l["v"]])
    write("calgary-budget-flows.csv", ["Budget", "From", "To", "Amount ($M)"], rows)
    T, P = B["tax"], B["proposed"]
    write("calgary-property-tax.csv", ["Figure", "Value", "Notes"], [
        ["Tax year", T["year"], ""],
        ["Municipal tax rate on homes", T["res_rate"], "multiply a home's assessed value by this"],
        ["Typical home's assessed value ($)", T["typical_home_value"], "median single residential property"],
        ["Typical home's municipal tax ($)", round(T["typical_home_value"] * T["res_rate"]), ""],
        ["Municipal tax from homes ($)", T["homes"], ""],
        ["Municipal tax from businesses and other property ($)", T["businesses"], ""],
        [f"Proposed {P['year']} increase in property tax needed", P["increase"], P["source"]],
    ])


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    roads(); pavement(); budget()
