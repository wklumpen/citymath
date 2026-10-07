#!/usr/bin/env python3
"""Load a City of Calgary "Historical Property Assessments (Parcel)" CSV into
the spatial database as a PostGIS table.

    uv run load_assessment_csv.py data/<file>.csv na_ca_ab_cgy.assessments_2025

Refuses to overwrite an existing table unless --replace is given.
"""
import argparse
import re
from pathlib import Path

from dotenv import load_dotenv

from citymath import ROOT, connect

NUM = "nullif(replace({}, ',', ''), '')::numeric"
COLUMNS = {  # output column: expression over the raw (all-text) CSV columns
    "roll_year": "roll_year::integer",
    "roll_number": "roll_number",
    "address": "address",
    "assessed_value": NUM.format("assessed_value"),
    "assessment_class": "assessment_class",
    "assessment_class_description": "assessment_class_description",
    "re_assessed_value": NUM.format("re_assessed_value"),
    "nr_assessed_value": NUM.format("nr_assessed_value"),
    "fl_assessed_value": NUM.format("fl_assessed_value"),
    "comm_code": "comm_code",
    "comm_name": "comm_name",
    "year_of_construction": NUM.format("year_of_construction") + "::integer",
    "land_use_designation": "land_use_designation",
    "property_type": "property_type",
    "land_size_sm": NUM.format("land_size_sm"),
    "land_size_sf": NUM.format("land_size_sf"),
    "land_size_ac": NUM.format("land_size_ac"),
    "sub_property_use": "sub_property_use",
    "cpid": "cpid",
    "geom": "ST_Multi(ST_GeomFromText(nullif(multipolygon, ''), 4326))"
            "::geometry(MultiPolygon, 4326)",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("table", help="schema.table in the spatial database")
    parser.add_argument("--database", default="spatial")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.table):
        parser.error("table must look like schema.table")

    load_dotenv(ROOT / ".env")
    raw = [c for c in COLUMNS if c != "geom"] + ["multipolygon"]
    with connect(args.database) as conn:
        if conn.execute("select to_regclass(%s)", (args.table,)).fetchone()[0]:
            if not args.replace:
                raise SystemExit(f"{args.table} already exists (use --replace)")
            conn.execute(f"drop table {args.table}")
        conn.execute("create temp table raw_csv ("
                     + ", ".join(f"{c} text" for c in raw) + ")")
        # CSV header order: ..., SUB_PROPERTY_USE, MULTIPOLYGON, CPID
        order = [c for c in raw if c not in ("cpid", "multipolygon")] + ["multipolygon", "cpid"]
        with args.csv.open("rb") as f, conn.cursor().copy(
                f"copy raw_csv ({', '.join(order)}) from stdin (format csv, header)") as copy:
            header = f.readline()
            found = header.decode("utf-8-sig").strip().replace('"', "").lower().split(",")
            if found != order:
                raise SystemExit(f"unexpected CSV columns: {found}")
            copy.write(header)
            while chunk := f.read(1 << 20):
                copy.write(chunk)
        conn.execute(
            f"create table {args.table} as select row_number() over ()::bigint as fid, "
            + ", ".join(f"{expr} as {name}" for name, expr in COLUMNS.items())
            + " from raw_csv")
        name = args.table.split(".")[1]
        conn.execute(f"""
            alter table {args.table} add primary key (fid);
            create index {name}_geom_idx on {args.table} using gist (geom);
            create index {name}_roll_number_idx on {args.table} (roll_number);
            analyze {args.table};""")
        n, nogeom, invalid = conn.execute(f"""
            select count(*), count(*) filter (where geom is null),
                   count(*) filter (where not ST_IsValid(geom)) from {args.table}""").fetchone()
        print(f"{args.table}: {n:,} rows, {nogeom} without geometry, {invalid} invalid geometries")


if __name__ == "__main__":
    main()
