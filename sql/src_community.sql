select "COMM_CODE", "NAME", "CLASS", "SECTOR", "COMM_STRUCTURE",
       ST_Multi(ST_Transform(geom, {srid}))
from {table}
