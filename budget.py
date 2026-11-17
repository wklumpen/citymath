#!/usr/bin/env python3
"""The City's budget as flows, for docs/pay.html.

    uv run budget.py                    # fetch the open data, write docs/data/budget.json
    uv run budget.py --cache rows.json  # use a saved copy of the open data instead

Groupings, labels and the figures typed in from the budget document are in
budget.yaml. Spending by business unit comes from the City's open data. The
script stops if the flows do not add up to the totals the budget document gives.
"""
import argparse
import json
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data" / "budget.json"
TOLERANCE = 1.5  # $ millions; the budget document rounds to the nearest million


def fetch(dataset):
    url = f"https://data.calgary.ca/resource/{dataset}.json?$limit=50000"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def check(label, got, want):
    if abs(got - want) > TOLERANCE:
        raise SystemExit(f"{label}: flows give {got:,.1f}, budget document says {want:,.1f}")
    print(f"  {label:<34}{got:>9,.1f}  (document: {want:,})")


def spending(rows, year, fund):
    """{business unit: (department, $M)} for one year and fund."""
    out = {}
    for r in rows:
        if r.get("year") == str(year) and r.get("fund") == fund:
            dept, amt = out.get(r["business_unit"], (r["budget_department"], 0.0))
            out[r["business_unit"]] = (dept, amt + float(r["budget"]))
    return out


def group(uses, units):
    """Total each group in `uses`; every business unit must be claimed once."""
    left = dict(units)
    totals = {}
    for u in uses:
        names = list(u.get("units", []))
        names += [n for n, (dept, _) in units.items() if dept in u.get("departments", [])]
        missing = [n for n in names if n not in left]
        if missing:
            raise SystemExit(f"{u['id']}: not in the open data, or claimed twice: {missing}")
        totals[u["id"]] = sum(left.pop(n)[1] for n in names)
    for u in uses:  # a single project lifted out of a business unit
        if "take" in u:
            host = next(h for h in uses if u["take"]["from"] in h.get("units", []))
            totals[u["id"]] += u["take"]["amount"]
            totals[host["id"]] -= u["take"]["amount"]
    rest = next((u for u in uses if u.get("rest")), None)
    if rest:
        totals[rest["id"]] += sum(v for _, v in left.values())
    elif left:
        raise SystemExit(f"business units not in any group: {sorted(left)}")
    return totals


def node(n, col, **extra):
    keep = ("id", "label", "color", "desc", "link", "view", "items")
    return {**{k: n[k] for k in keep if k in n}, "col": col, **extra}


def operating(cfg, rows, year):
    spend = group(cfg["uses"], spending(rows, year, cfg["fund"]))
    src = {s["id"]: s for s in cfg["sources"]}
    fees = sum(u.get("revenue", 0) for u in cfg["uses"])
    values = {"tax": src["tax"]["value"], "water": src["water"]["value"], "fees": fees,
              "general": cfg["corporate_revenue"] - src["tax"]["value"]}

    # Money the budget counts against one service passes the pot on its way to that service.
    nodes = [node(s, 0) for s in cfg["sources"]]
    nodes += [node({"id": "pot", **cfg["pot"]}, 1), {"id": "fees_", "col": 1, "ghost": "fees"}, {"id": "water_", "col": 1, "ghost": "water"}]
    nodes += [node(u, 2) for u in cfg["uses"]] + [node({"id": "reserve", **cfg["reserve"]}, 2)]

    links, pot_out, water_out = [], 0.0, 0.0
    for u in cfg["uses"]:
        s = spend[u["id"]]
        if u.get("paid_by") == "water":
            links.append(("water_", u["id"], s))
            water_out += s
            continue
        own = u.get("revenue", 0)
        if own > s:
            raise SystemExit(f"{u['id']}: raises more ({own}) than it spends ({s:.1f})")
        links.append(("pot", u["id"], s - own))
        pot_out += s - own
        if own:
            links.append(("fees_", u["id"], own))
    # The water utility's bills cover its own services and reserves; the remainder
    # is utility work carried in other departments' budgets (p. 33), shown joining the pot.
    water_other = values["water"] - water_out - cfg["water_reserves"]
    pot_in = values["tax"] + values["general"] + water_other
    links += [("tax", "pot", values["tax"]), ("general", "pot", values["general"]), ("water", "pot", water_other, cfg["water_other_label"]),
              ("fees", "fees_", fees), ("water", "water_", water_out + cfg["water_reserves"]),
              ("water_", "reserve", cfg["water_reserves"]), ("pot", "reserve", pot_in - pot_out)]

    print("Operating")
    check("revenue", sum(values.values()), cfg["revenue_total"])
    check("spending on services", sum(spend.values()), cfg["spending_total"])
    check("set aside", sum(l[2] for l in links if l[1] == "reserve"), cfg["net_reserves"])
    return nodes, links, sum(values.values())


def capital(cfg, rows, year):
    spend = group(cfg["uses"], spending(rows, year, cfg["fund"]))
    nodes = [node(s, 0) for s in cfg["sources"]] + [node({"id": "pot", **cfg["pot"]}, 1)] + [node(u, 2) for u in cfg["uses"]]
    links = [(s["id"], "pot", s["value"]) for s in cfg["sources"]] + [("pot", u["id"], spend[u["id"]]) for u in cfg["uses"]]
    print("Capital")
    check("sources", sum(s["value"] for s in cfg["sources"]), cfg["spending_total"])
    check("spending", sum(spend.values()), cfg["spending_total"])
    return nodes, links, sum(spend.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, help="saved copy of the open data (JSON) to use instead of fetching")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "budget.yaml").read_text())
    rows = json.loads(args.cache.read_text()) if args.cache else fetch(cfg["dataset"])

    views = {}
    for key, build in (("operating", operating), ("capital", capital)):
        c = cfg[key]
        nodes, links, total = build(c, rows, cfg["year"])
        views[key] = {
            **{k: c[k] for k in ("tab", "name", "heads", "lead", "takeaways")},
            "total": round(total, 1),
            "nodes": nodes,
            "links": [{"s": s, "t": t, "v": round(v, 1), **({"label": note[0]} if note else {})} for s, t, v, *note in links if v > 0.05],
        }

    out = {"year": cfg["year"], "document": cfg["document"],
           "dataset": f"https://data.calgary.ca/d/{cfg['dataset']}", "views": views}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
