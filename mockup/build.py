#!/usr/bin/env python3
"""Build the web mockup: export per-hex data from the database and embed it in
mockup/template.html, writing mockup/calgary-street-math.html (git-ignored).

    uv run mockup/build.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import citymath  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parent / ".env")
c = citymath.connect('projects', 'strongtowns_citymath')
x0, y0, x1, y1 = c.execute("select ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) from (select ST_Extent(geom) e from src_hex) q").fetchone()
rows = c.execute("""
 with m as (
   select l.hex_id,
     sum(l.length_m * coalesce(w.width_median, k.width_m)) filter (where l.road_class = 'residential') res,
     sum(l.length_m * k.width_m) filter (where l.road_class = 'tertiary') ter,
     sum(l.length_m * k.width_m) filter (where k.shared) sh
   from hex_road_length l join cfg_road_class k using (road_class)
   join hex_community hc using (hex_id)
   left join comm_structure_width w on w.comm_structure = hc.comm_structure
   group by 1)
 select s.hex_id, ST_AsGeoJSON(s.geom, 0), coalesce(s.comm_structure, 'OTHER'), s.is_special,
        s.revenue_total, coalesce(m.res, 0), coalesce(m.ter, 0), coalesce(m.sh, 0), s.comm_name
 from hex_summary s left join m using (hex_id) order by s.hex_id""").fetchall()
structs = sorted({r[2] for r in rows})
hexes = []
for hid, gj, st, sp, rev, res, ter, sh, name in rows:
    g = json.loads(gj)
    polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    d = ''
    for poly in polys:
        for ring in poly:
            pts = [(round((x - x0) / 10), round((y1 - y) / 10)) for x, y in ring[:-1]]
            d += 'M' + 'L'.join(f'{a} {b}' for a, b in pts) + 'Z'
    hexes.append([hid, d, structs.index(st), 1 if sp or st == 'OTHER' and False else int(bool(sp)), round(rev), round(res), round(ter), round(sh), (name or '').title()])
out = {'w': round((x1 - x0) / 10), 'h': round((y1 - y0) / 10), 'structs': structs, 'hex': hexes}
data = json.dumps(out, separators=(",", ":"))
page = (HERE / "template.html").read_text().replace("/*DATA*/", data)
(HERE / "calgary-street-math.html").write_text(page)
print(f"{len(hexes)} hexes -> mockup/calgary-street-math.html ({len(page) // 1024} KB)")
