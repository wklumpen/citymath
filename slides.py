"""Slide images (PNG) from the website's data, with the same math as docs/index.html.

    uv run slides.py                       # every chart, every plan
    uv run slides.py recommended budget_2026

Writes to slides/out/: each chart as <name>_wide.png (16:9, 1920x1080, with a
title) and <name>_square.png (1080x1080, no title, for text beside it).
"""
import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import vl_convert as vlc

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
OUT = ROOT / "slides" / "out"
SCALE = 2  # charts are laid out at 960x540 / 540x540 and rendered at twice that

# Colours and fonts from docs/index.html (light theme).
INK, MUTED, LINE, BAND, ACCENT = "#101b2d", "#586579", "#dde2ea", "#12305c", "#e8751a"
GOOD, BAD, SPECIAL = "#1f7a8c", "#c2410c", "#d5dae2"
DISPLAY, BODY = "Archivo", "'Source Sans 3'"  # quoted: a CSS family name can't start a word with a digit
# Map classes: road cost as a multiple of the area's mobility budget.
STEPS = [0.5, 1, 2, 4, 8]
CLASSES = ["Roads use under half", "Roads use half to all of it", "Up to 100% overrun",
           "100–300% overrun", "300–700% overrun", "Over 700% overrun",
           "Park, undeveloped or special district"]
COLOURS = ["#1f7a8c", "#9fd3db", "#fbd3a6", "#f29b4b", "#d1611a", "#8a3608", SPECIAL]
ORDER = ["CENTRE CITY", "INNER CITY", "1950s", "1960s/1970s", "1980s/1990s", "2000s",
         "2010s", "2020s", "BUILDING OUT", "EMPLOYMENT"]
NICE = {"CENTRE CITY": "Centre City", "INNER CITY": "Inner city", "BUILDING OUT": "Still building out",
        "EMPLOYMENT": "Employment area"}


# ---- the money (mirrors prepare / cost / taxRise / ratio in docs/index.html) ----
def load():
    s = json.loads((DATA / "scenarios.json").read_text())
    hexes = json.loads((DATA / "hexes.geojson").read_text())
    wards = json.loads((DATA / "wards.geojson").read_text())
    h = pd.DataFrame([f["properties"] for f in hexes["features"]])
    h["st"] = h["structure"].fillna("OTHER")
    h["rev"] = h["rev_res"] + h["rev_com"]
    w = {"equal": 1 / len(h), "area": h["area_ha"] / h["area_ha"].sum(),
         "revenue": h["rev"] / h["rev"].sum()}.get(s["shared_basis"])
    h["pm2"] = h["m2"] + (h["m2_sh"] if w is None else w * h["m2_sh"].sum())
    h["pm2y"] = h["m2y"] + (h["m2y_sh"] if w is None else w * h["m2y_sh"].sum())
    global PM2_TOTAL
    PM2_TOTAL = h["pm2"].sum()
    return s, h, hexes, wards


PM2_TOTAL = None  # citywide pavement, so a budget is shared out the same way for any subset of hexes


def cost(h, sc, end=None):
    rate = sc[end] if end else (sc["low"] + sc["high"]) / 2
    if sc["kind"] == "budget":
        return rate * h["pm2"] / PM2_TOTAL
    return rate * (h["pm2y"] if sc["kind"] == "life" else h["pm2"])


def plans(s, h):
    """One row per plan: citywide cost, share of the mobility budget, tax rise."""
    rev, mob = h["rev"].sum(), h["rev"].sum() * s["mobility_share"]
    now = cost(h, next(x for x in s["scenarios"] if x["id"] == s["current"])).sum()
    ordinary = h[~h["special"] & (h["rev"] > 0)]
    rows = []
    for sc in s["scenarios"]:
        c = cost(h, sc).sum()
        rise = max(0, (c - now) / rev)
        over = (cost(ordinary, sc) > ordinary["rev"] * s["mobility_share"]).sum()
        rows.append({"id": sc["id"], "plan": sc["label"], "cost": c, "ratio": c / mob,
                     "rise": rise, "home": rise * s["typical_home_value"] * s["res_rate"],
                     "over": int(over), "n": len(ordinary)})
    return pd.DataFrame(rows), mob


# ---- formatting ----
def money(v):
    a = abs(v)
    if a >= 1e9:
        return f"${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"${a / 1e6:.0f}M" if a >= 1e8 else f"${a / 1e6:.1f}M".replace(".0M", "M")
    return f"${a:,.0f}"


def pct(v):
    return f"{v * 100:.1f}%" if v * 100 < 10 else f"{v * 100:,.0f}%"


def cents(v):
    return f"{v * 100:.1f}¢" if v * 100 < 10 else f"{v * 100:.0f}¢"


# ---- rendering ----
@alt.theme.register("citymath", enable=True)
def theme():
    return alt.theme.ThemeConfig({"config": {
        "background": "#ffffff", "padding": 28,
        "font": BODY,
        "title": {"font": DISPLAY, "fontSize": 30, "fontWeight": 800, "color": INK, "anchor": "start",
                  "subtitleFont": BODY, "subtitleFontSize": 18, "subtitleColor": MUTED, "subtitlePadding": 8,
                  "offset": 22},
        "axis": {"labelFont": BODY, "labelFontSize": 16, "labelColor": INK, "titleFont": BODY,
                 "titleFontSize": 15, "titleColor": MUTED, "titleFontWeight": 400,
                 "gridColor": LINE, "domainColor": LINE, "tickColor": LINE},
        "legend": {"labelFont": BODY, "labelFontSize": 15, "labelColor": INK, "titleFont": DISPLAY,
                   "titleFontSize": 15, "titleColor": INK, "symbolSize": 260},
        "text": {"font": BODY, "fontSize": 16, "color": INK},
        "view": {"stroke": None},
    }})


vlc.register_font_directory(str(ROOT / "slides" / "fonts"))


def save(chart, name, title=None, subtitle=None):
    """Write <name>_wide.png (16:9, titled) and <name>_square.png (untitled)."""
    OUT.mkdir(parents=True, exist_ok=True)
    for shape, (w, hgt) in {"wide": (960, 540), "square": (540, 540)}.items():
        c = chart(shape)
        if shape == "wide" and title:
            c = c.properties(title=alt.Title(title, subtitle=subtitle or []))
        c = c.properties(width=w, height=hgt).configure(
            autosize={"type": "fit", "contains": "padding"})
        png = vlc.vegalite_to_png(c.to_json(), scale=SCALE)
        (OUT / f"{name}_{shape}.png").write_bytes(png)
        print(f"  {name}_{shape}.png")


def bar_chart(df, field, label, rule=None, rule_label=None, sort=None, rule_short=None, colours=(GOOD, BAD)):
    df = df.assign(lx=df[field].clip(lower=rule) if rule is not None else df[field])

    def chart(shape):
        base = alt.Chart(df).encode(
            y=alt.Y("plan:N", sort=sort or list(df["plan"]), title=None,
                    axis=alt.Axis(labelLimit=300 if shape == "wide" else 240, domain=False, ticks=False,
                                  labelFontSize=16 if shape == "wide" else 15)),
            x=alt.X(f"{field}:Q", title=None, axis=None))
        bars = base.mark_bar(cornerRadiusEnd=3, height={"band": 0.7}).encode(
            color=alt.Color("over:N", scale=alt.Scale(domain=[False, True], range=list(colours)), legend=None))
        # labels start past the rule, so the line never runs through them
        text = base.mark_text(align="left", dx=8, fontWeight=600, fontSize=17 if shape == "wide" else 15).encode(
            x="lx:Q", text=f"{label}:N")
        layers = [bars, text]
        if rule is not None:
            r = pd.DataFrame({"x": [rule], "t": [rule_label if shape == "wide" else rule_short or rule_label]})
            layers += [alt.Chart(r).mark_rule(color=INK, strokeWidth=2.5, strokeDash=[6, 4]).encode(x="x:Q"),
                       alt.Chart(r).mark_text(align="left", dx=6, dy=-6, baseline="bottom", fontWeight=600,
                                              color=INK, fontSize=15).encode(
                           x="x:Q", y=alt.value(0), text="t:N")]
        return alt.layer(*layers).resolve_scale(x="shared")
    return chart


def plan_charts(s, h):
    df, mob = plans(s, h)
    df["over"] = df["ratio"] > 1
    df["cost_t"] = [f"{money(c)} · {pct(r)} of mobility" if r <= 1 else f"{money(c)} · {pct(r - 1)} overrun"
                    for c, r in zip(df["cost"], df["ratio"])]
    save(bar_chart(df, "cost", "cost_t", rule=mob, rule_label=f"Mobility's whole share of property tax: {money(mob)}",
                   rule_short=f"Mobility budget: {money(mob)}"),
         "plans_cost", "The City's own plans eat most of the mobility budget",
         f"Road pavement and repair, a year citywide, against mobility's {cents(s['mobility_share'])} of each "
         f"{s['tax_year']} property tax dollar")

    df["home_t"] = [("no increase" if r <= 0.0005 else f"+{pct(r)} tax · +${m:,.0f} a year")
                    for r, m in zip(df["rise"], df["home"])]
    df["over"] = False
    save(bar_chart(df, "home", "home_t", colours=(BAND, BAND)), "plans_tax",
         "What each plan costs the median household",
         f"Extra municipal property tax a year on a ${s['typical_home_value']:,} home, "
         f"if the rate alone paid for it")

    hexes = df.rename(columns={"over": "_"}).assign(
        over=df["ratio"] > 1, n_over=plans(s, h)[0]["over"],
        over_t=[f"{o:,} of {n:,}" for o, n in zip(plans(s, h)[0]["over"], df["n"])])
    save(bar_chart(hexes, "n_over", "over_t", colours=(BAD, BAD)), "plans_hexes",
         "Neighbourhoods where roads alone overrun the mobility budget",
         "Number of 800 m hexagons, not counting parks, undeveloped land and special districts")


def neighbourhood_chart(s, h, sc):
    mob = s["mobility_share"]
    rows = []
    for st in ORDER:
        g = h[h["st"] == st]
        v = cost(g, sc).sum() / g["rev"].sum()
        rows.append({"plan": NICE.get(st, st), "v": v, "t": cents(v), "over": v > mob})
    df = pd.DataFrame(rows)
    save(bar_chart(df, "v", "t", rule=mob, rule_label=f"Mobility budget: {cents(mob)}"),
         f"neighbourhoods_{sc['id']}",
         "More homes and businesses per street, more money left over",
         f"{sc['label']}: cents of each property tax dollar needed for roads, by type of neighbourhood")


def rings_clockwise(geom):
    """d3 (Vega) wants exterior rings clockwise, the reverse of RFC 7946."""
    def area(r):
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:]))
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = [[r if (area(r) < 0) == (i == 0) else r[::-1] for i, r in enumerate(p)] for p in polys]
    return {"type": "MultiPolygon", "coordinates": out}


def map_chart(s, h, hexes, wards, sc):
    c = cost(h, sc).values
    ratio = c / (h["rev"].values * s["mobility_share"]).clip(min=1e-9)
    klass = []
    for special, rev, r in zip(h["special"], h["rev"], ratio):
        if special or rev <= 0:
            klass.append(6)
        else:
            klass.append(sum(r >= x for x in STEPS))
    feats = [{"type": "Feature", "geometry": rings_clockwise(f["geometry"]),
              "properties": {"k": CLASSES[k]}} for f, k in zip(hexes["features"], klass)]
    outline = [{"type": "Feature", "geometry": rings_clockwise(f["geometry"]), "properties": {}}
               for f in wards["features"] if f["properties"]["kind"] == "outline"]
    hex_data = alt.Data(values=feats)
    ward_data = alt.Data(values=outline)
    over = sum(1 for k in klass if 2 <= k <= 5)
    ordinary = sum(1 for k in klass if k < 6)

    def chart(shape):
        legend = alt.Legend(title="Road cost against the area's mobility budget" if shape == "wide" else None,
                            orient="right" if shape == "wide" else "bottom", titleFontSize=18, titlePadding=12, titleLimit=600,
                            columns=1 if shape == "wide" else 2, labelLimit=460, symbolType="square",
                            symbolStrokeWidth=0, rowPadding=6, columnPadding=18,
                            labelFontSize=17 if shape == "wide" else 13)
        hx = alt.Chart(hex_data).mark_geoshape(stroke="#ffffff", strokeWidth=0.4).encode(
            color=alt.Color("properties.k:N", scale=alt.Scale(domain=CLASSES, range=COLOURS), legend=legend))
        wd = alt.Chart(ward_data).mark_geoshape(filled=False, stroke=BAND, strokeWidth=1.2, strokeOpacity=0.7)
        return alt.layer(hx, wd).project(type="mercator")

    save(chart, f"map_{sc['id']}",
         "Where roads alone use up the area's mobility budget",
         f"{sc['label']}: roads alone overrun it in {over:,} of {ordinary:,} neighbourhood hexagons")


def main():
    s, h, hexes, wards = load()
    wanted = sys.argv[1:] or [x["id"] for x in s["scenarios"]]
    unknown = set(wanted) - {x["id"] for x in s["scenarios"]}
    if unknown:
        raise SystemExit(f"unknown plan(s): {', '.join(sorted(unknown))}")
    print(f"writing to {OUT.relative_to(ROOT)}/")
    plan_charts(s, h)
    for sc in s["scenarios"]:
        if sc["id"] in wanted:
            neighbourhood_chart(s, h, sc)
            map_chart(s, h, hexes, wards, sc)


if __name__ == "__main__":
    main()
