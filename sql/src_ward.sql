select ward_num, label, councillor, ST_Multi(ST_Transform(geom, {srid}))
from {table}
