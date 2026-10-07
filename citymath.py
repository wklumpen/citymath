#!/usr/bin/env python3
"""CityMath: per-hex road cost vs. property tax revenue.

    uv run citymath.py                 # everything
    uv run citymath.py roads summary   # just re-run some steps

Steps: load, community, roads, assessments, summary. Settings are in config.yaml,
database credentials in .env, and the actual spatial work in sql/.
"""
import argparse
import csv
import os
import re
import sqlite3
import time
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent
SQL = ROOT / "sql"


def connect(dbname, schema=None):
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=dbname,
        options=f"-c search_path={schema},public" if schema else None,
        cursor_factory=psycopg.ClientCursor,
    )


def run_sql(conn, name, params=None, **fmt):
    text = (SQL / name).read_text()
    conn.execute(text.format(**fmt) if fmt else text, params)


def show(conn, title, query):
    cur = conn.execute(query)
    print(f"  {title}")
    for row in cur.fetchall():
        print("    " + "  ".join(
            f"{v:,.1f}" if isinstance(v, float) else str(v) for v in row))


def gpkg_to_wkb(blob):
    """Strip the GeoPackage header (8 bytes + optional envelope) to get WKB."""
    envelope = (0, 32, 48, 48, 64)[(blob[3] >> 1) & 7]
    return bytes(blob[8 + envelope:])


def text_array(values, suffix=""):
    """SQL array literal for a config list of plain codes / roll numbers."""
    values = [str(v) for v in values or []]
    for v in values:
        if not re.fullmatch(r"[A-Za-z0-9]+", v):
            raise SystemExit(f"exempt code / roll number {v!r} must be alphanumeric")
    return "'{" + ",".join(v + suffix for v in values) + "}'"


def pipe(src, dst, name, target, **fmt):
    """Stream a query on the source database into a staging table."""
    select = (SQL / name).read_text().format(**fmt)
    with src.cursor().copy(f"copy ({select}) to stdout") as out, \
            dst.cursor().copy(f"copy {target} from stdin") as into:
        for chunk in out:
            into.write(chunk)


def load(cfg, dst):
    srid = cfg["srid"]
    run_sql(dst, "00_staging.sql", srid=srid)

    hex_cfg = cfg["hex"]
    gpkg = sqlite3.connect(f"file:{ROOT / hex_cfg['gpkg']}?mode=ro", uri=True)
    layer = hex_cfg["layer"]
    geom_col, hex_srid = gpkg.execute(
        "select column_name, srs_id from gpkg_geometry_columns where table_name = ?",
        (layer,)).fetchone()
    rows = gpkg.execute(
        f'select "{hex_cfg["id_column"]}", "{geom_col}" from "{layer}"').fetchall()
    dst.cursor().executemany(
        "insert into src_hex values "
        "(%s, ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromWKB(%s), %s), %s)))",
        [(i, gpkg_to_wkb(g), hex_srid, srid) for i, g in rows])

    sources = cfg["sources"]
    exempt = cfg["assessments"]["exempt"]
    with connect(sources["database"]) as src:
        pipe(src, dst, "src_community.sql", "src_community",
             table=sources["communities"], srid=srid)
        pipe(src, dst, "src_road.sql", "src_road",
             table=sources["roads"], srid=srid)
        pipe(src, dst, "src_parcel.sql", "src_parcel",
             table=sources["assessments"]["table"], srid=srid,
             exempt_codes=text_array(exempt["sub_property_codes"]),
             exempt_prefixes=text_array(sources["assessments"].get("exempt_prefixes"), suffix="%"),
             exempt_rolls=text_array(str(r).lstrip("0") for r in exempt["roll_numbers"] or []),
             **sources["assessments"]["columns"])
    run_sql(dst, "00_staging_index.sql")
    show(dst, "staging rows", """
        select 'src_hex', count(*) from src_hex union all
        select 'src_community', count(*) from src_community union all
        select 'src_road', count(*) from src_road union all
        select 'src_parcel', count(*) from src_parcel""")


def community(cfg, dst):
    run_sql(dst, "01_hex_community.sql", srid=cfg["srid"])
    # Wide version: one pct_<structure> column (0-100) per community structure.
    names = [r[0] for r in dst.execute(
        "select distinct comm_structure from hex_structure_area order by 1")]
    cols = {"pct_" + re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_"): n for n in names}
    dst.execute(
        "drop table if exists hex_structure_pct cascade; "
        "create table hex_structure_pct as select h.hex_id, "
        + ", ".join(f"coalesce(100 * sum(a.share) filter (where a.comm_structure = %({c})s), 0)"
                    f" as {c}" for c in cols)
        + " from src_hex h left join hex_structure_area a using (hex_id) group by h.hex_id",
        cols)
    show(dst, "city area by community structure: % of hex area, hexes mostly (>50%) that structure", """
        select a.comm_structure,
               (100 * sum(a.share * ST_Area(h.geom)) / (select sum(ST_Area(geom)) from src_hex))::float8,
               count(*) filter (where a.share > 0.5)
        from hex_structure_area a join src_hex h using (hex_id) group by 1 order by 1""")
    show(dst, "hexes by community structure (match method)", """
        select coalesce(comm_structure, '(none)'), comm_match, count(*)
        from hex_community group by 1, 2 order by 1, 2""")


def load_road_config(cfg, dst):
    classes = cfg["roads"]["classes"]
    for name in classes:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise SystemExit(f"road class name {name!r} must be lowercase snake_case")
    dst.execute("""
        drop table if exists cfg_road_class cascade;
        drop table if exists cfg_road_highway cascade;
        create table cfg_road_class (road_class text primary key, width_m float8,
                                     life_years float8, shared boolean);
        create table cfg_road_highway (highway text primary key, road_class text);""")
    cur = dst.cursor()
    shared = cfg["roads"]["shared"]["classes"] or []
    if unknown := set(shared) - set(classes):
        raise SystemExit(f"roads.shared.classes: unknown road class {sorted(unknown)}")
    cur.executemany("insert into cfg_road_class values (%s, %s, %s, %s)",
                    [(n, c["width_m"], c["life_years"], n in shared)
                     for n, c in classes.items()])
    cur.executemany("insert into cfg_road_highway values (%s, %s)",
                    [(h, n) for n, c in classes.items() for h in c["osm"]])
    return list(classes)


def load_width_samples(cfg, dst):
    """Sampled street widths -> min/avg/max per community structure."""
    samples = cfg["roads"]["width_samples"]
    with open(ROOT / samples["csv"], newline="") as f:
        rows = [(r["id"], r["comm_structure"], r["name"], r["width_m"])
                for r in csv.DictReader(f) if r["width_m"]]
    dst.execute("""
        drop table if exists street_width_sample cascade;
        drop table if exists comm_structure_width cascade;
        create table street_width_sample (sample_id integer primary key,
            comm_structure text, name text, width_m float8);""")
    dst.cursor().executemany(
        "insert into street_width_sample values (%s, %s, %s, %s)", rows)
    dst.execute("""
        create table comm_structure_width as
        select comm_structure, count(*) as width_n, min(width_m) as width_min,
               avg(width_m) as width_avg,
               percentile_cont(0.5) within group (order by width_m) as width_median,
               max(width_m) as width_max
        from street_width_sample group by comm_structure;""")
    return samples["applies_to"]


def load_scenarios(cfg, dst):
    """Pavement scenarios -> cfg_scenario, with costs inflated to target_year."""
    infl = cfg["roads"]["cost_inflation"]
    factor = (1 + infl["annual_inflation"]) ** (infl["target_year"] - infl["base_year"])
    rows = {}
    for name, sc in cfg["roads"]["scenarios"].items():
        per_life = "cost_per_m2" in sc
        cost = sc["cost_per_m2"] if per_life else sc["cost_per_m2_year"]
        rows[name] = (sc.get("label", name), cost["low"] * factor, cost["high"] * factor, per_life)
    dst.execute("""
        drop table if exists cfg_scenario cascade;
        create table cfg_scenario (scenario text primary key, label text,
            cost_low float8, cost_high float8, per_life boolean);""")
    dst.cursor().executemany("insert into cfg_scenario values (%s, %s, %s, %s, %s)",
                             [(n, *r) for n, r in rows.items()])
    print(f"  pavement costs in {infl['target_year']} dollars (x{factor:.4f})")
    return rows


def roads(cfg, dst):
    load_road_config(cfg, dst)
    r = cfg["roads"]
    run_sql(dst, "02_hex_roads.sql", {
        "provincial_refs": [str(x) for x in r["provincial_refs"]],
        "unpaved": r["unpaved_surfaces"],
        "link_buffer": r["provincial_link_buffer_m"],
    })
    show(dst, "road km by class: kept / in hexes", """
        select road_class,
               (select sum(ST_Length(geom)) / 1000 from road_used u
                 where u.road_class = c.road_class)::float8,
               (select sum(length_m) / 1000 from hex_road_length l
                 where l.road_class = c.road_class)::float8
        from cfg_road_class c order by 1""")


def assessments(cfg, dst):
    run_sql(dst, "03_hex_assessment.sql")
    show(dst, "assessed value $M (res, nonres, farm): source / allocated to hexes", """
        select 'source', (sum(value_res) / 1e6)::float8,
               (sum(value_nonres) / 1e6)::float8, (sum(value_farm) / 1e6)::float8
        from src_parcel union all
        select 'hexes', sum(value_res) / 1e6, sum(value_nonres) / 1e6,
               sum(value_farm) / 1e6
        from hex_assessment""")
    show(dst, "exempt assessed value $M (earns no revenue)", """
        select sum(value_exempt) / 1e6 from hex_assessment""")
    show(dst, "parcels touching no hex (value not allocated)", """
        select count(*), (coalesce(sum(value_res + value_nonres + value_farm), 0) / 1e6)::float8
        from src_parcel p
        where not exists (select 1 from hex_parcel hp where hp.parcel_id = p.parcel_id)""")


def summary(cfg, dst):
    classes = load_road_config(cfg, dst)
    road_cols = ",\n           ".join(
        f"coalesce(sum(l.length_m) filter (where l.road_class = '{c}'), 0) as road_m_{c}"
        for c in classes)
    sampled_class = load_width_samples(cfg, dst)
    if sampled_class not in classes:
        raise SystemExit(f"width_samples.applies_to: no road class {sampled_class!r}")
    show(dst, "sampled street width by community structure: n, min, avg, median, max", """
        select comm_structure, width_n, width_min, width_avg, width_median, width_max
        from comm_structure_width order by 1""")
    rates = cfg["tax_rates"]
    params = {f"rate_{k}": rates["municipal"][k] for k in ("res", "nonres", "farm")}
    params |= {f"prov_{k}": rates["provincial"][k] for k in ("res", "nonres", "farm")}
    params["sampled_class"] = sampled_class
    scenarios = load_scenarios(cfg, dst)
    _, low, high, per_life = scenarios[cfg["roads"]["default_scenario"]]
    params["cost_low"], params["cost_high"] = low, high
    params["shared_basis"] = cfg["roads"]["shared"]["basis"]
    params["special"] = cfg.get("special_structures") or []
    if params["shared_basis"] not in ("equal", "area", "revenue"):
        raise SystemExit("roads.shared.basis must be equal, area or revenue")
    run_sql(dst, "04_hex_summary.sql", params, road_cols=road_cols,
            cost_basis="pavement_m2_per_year" if per_life else "pavement_m2")
    run_sql(dst, "05_hex_scenario.sql")
    show(dst, "scenarios: road cost $M (low, mid, high), % of municipal tax "
              "(low, mid, high), hexes with net <= 0 (mid)", """
        select scenario, sum(road_cost_low) / 1e6, sum(road_cost) / 1e6,
               sum(road_cost_high) / 1e6,
               100 * sum(road_cost_low) / sum(revenue_total),
               100 * sum(road_cost) / sum(revenue_total),
               100 * sum(road_cost_high) / sum(revenue_total),
               count(*) filter (where net <= 0)
        from hex_scenario group by 1 order by 3 desc""")
    show(dst, "city totals: hexes, road km, pavement km2, revenue $M", """
        select count(*), sum(road_m_total) / 1000, sum(pavement_m2) / 1e6,
               sum(revenue_total) / 1e6
        from hex_summary""")
    show(dst, "tax $M: municipal (= revenue), provincial, total", """
        select sum(revenue_total) / 1e6, sum(tax_provincial) / 1e6, sum(tax_total) / 1e6
        from hex_summary""")
    show(dst, "road cost $M (low, mid, high) / net $M (low, mid, high)", """
        select 'cost', sum(road_cost_low) / 1e6, sum(road_cost) / 1e6,
               sum(road_cost_high) / 1e6 from hex_summary union all
        select 'net', sum(net_low) / 1e6, sum(net) / 1e6, sum(net_high) / 1e6
        from hex_summary""")
    show(dst, "road cost as % of municipal tax, by community structure: "
              "hexes, revenue $M, road cost $M, share (low, mid, high)", """
        select case when grouping(comm_structure) = 1 then 'ALL HEXES'
                    else coalesce(comm_structure, '(none)') end,
               count(*), sum(revenue_total) / 1e6,
               sum(road_cost) / 1e6,
               100 * sum(road_cost_low) / nullif(sum(revenue_total), 0),
               100 * sum(road_cost) / nullif(sum(revenue_total), 0),
               100 * sum(road_cost_high) / nullif(sum(revenue_total), 0)
        from hex_summary group by rollup (comm_structure) order by 1""")
    show(dst, "ordinary vs special hexes: hexes, % of area, revenue $M, "
              "road cost $M, local pavement km2, hexes with net <= 0", """
        select case when is_special then 'special' else 'ordinary' end, count(*),
               100 * sum(hex_area_ha) / (select sum(hex_area_ha) from hex_summary),
               sum(revenue_total) / 1e6, sum(road_cost) / 1e6,
               sum(pavement_m2_local) / 1e6, count(*) filter (where net <= 0)
        from hex_summary group by 1 order by 1""")
    show(dst, "hexes with net <= 0 at low / mid / high road cost", """
        select count(*) filter (where net_high <= 0), count(*) filter (where net <= 0),
               count(*) filter (where net_low <= 0)
        from hex_summary""")


STEPS = {"load": load, "community": community, "roads": roads,
         "assessments": assessments, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("steps", nargs="*", metavar="step",
                        help=f"steps to run, in pipeline order (default: all): {', '.join(STEPS)}")
    parser.add_argument("--config", default=ROOT / "config.yaml")
    args = parser.parse_args()
    if unknown := set(args.steps) - set(STEPS):
        parser.error(f"unknown step(s): {', '.join(sorted(unknown))}")

    load_dotenv(ROOT / ".env")
    if not os.environ.get("PGPASSWORD"):
        raise SystemExit("No PGPASSWORD set: copy .env.example to .env and fill it in.")
    cfg = yaml.safe_load(Path(args.config).read_text())
    out = cfg["output"]
    with connect(out["database"], out["schema"]) as dst:
        for name, step in STEPS.items():
            if args.steps and name not in args.steps:
                continue
            print(f"[{name}]")
            start = time.time()
            step(cfg, dst)
            dst.commit()
            print(f"  done in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
