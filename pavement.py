#!/usr/bin/env python3
"""Pavement history and the proposed 2027-2030 pavement budget, for docs/roads.html.

    uv run pavement.py   # pavement.yaml -> docs/data/pavement.json

Every figure and its source is in pavement.yaml; this checks the proposed Mobility
budget adds up and writes it out as JSON.
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data" / "pavement.json"


def main():
    p = yaml.safe_load((ROOT / "pavement.yaml").read_text())
    for y in p["mobility_proposed"]:
        # the budget rounds each part to the nearest million
        if abs(y["operating"] + y["capital"] - y["total"]) > 1:
            raise SystemExit(f"{y['year']}: operating + capital != total")
    OUT.write_text(json.dumps(p, indent=1))
    print(f"  -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
