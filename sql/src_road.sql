select fid, osm_id, highway, name, ref, surface,
       ST_Transform(geom, {srid})
from {table}
