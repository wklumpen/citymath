-- Tag each hex with the community its centroid falls in. Centroids that land
-- outside every community (edge hexes) take the nearest one.
drop table if exists hex_community cascade;
create table hex_community as
select h.hex_id,
       m.comm_code,
       m.name           as comm_name,
       m.class          as comm_class,
       m.sector         as comm_sector,
       m.comm_structure,
       case when ST_Intersects(m.geom, h.pt) then 'centroid' else 'nearest' end as comm_match
from (select hex_id, ST_Centroid(geom) as pt from src_hex) h
cross join lateral (
    select * from src_community c order by c.geom <-> h.pt limit 1
) m;
alter table hex_community add primary key (hex_id);

-- Share of each hex's area in each community structure (long format).
-- The centroid tag above picks one structure; this shows the actual mix.
drop table if exists hex_structure_area cascade;
create table hex_structure_area as
select h.hex_id,
       coalesce(c.comm_structure, 'NONE') as comm_structure,
       sum(ST_Area(ST_Intersection(h.geom, c.geom))) / ST_Area(h.geom) as share
from src_hex h
join src_community c on ST_Intersects(h.geom, c.geom)
group by h.hex_id, h.geom, coalesce(c.comm_structure, 'NONE');

-- Neighbourhood outlines on the hex grid: the hexes tagged to each community,
-- dissolved into one shape. A layer to draw on top of the hex map.
drop table if exists community_hex_outline cascade;
create table community_hex_outline as
select c.comm_code,
       max(c.comm_name)      as comm_name,
       max(c.comm_class)     as comm_class,
       max(c.comm_sector)    as comm_sector,
       max(c.comm_structure) as comm_structure,
       count(*)              as n_hexes,
       ST_Multi(ST_Union(h.geom))::geometry(MultiPolygon, {srid}) as geom
from hex_community c
join src_hex h using (hex_id)
group by c.comm_code;
alter table community_hex_outline add primary key (comm_code);
create index on community_hex_outline using gist (geom);

-- Ward of each hex, by centroid like the community tag (nearest ward for the
-- few centroids that fall outside every ward).
drop table if exists hex_ward cascade;
create table hex_ward as
select h.hex_id, w.ward_num, w.label as ward_label
from (select hex_id, ST_Centroid(geom) as pt from src_hex) h
cross join lateral (
    select * from src_ward w order by w.geom <-> h.pt limit 1
) w;
alter table hex_ward add primary key (hex_id);

-- Wards on the hex grid: each ward's hexes dissolved into one shape.
drop table if exists ward_hex_outline cascade;
create table ward_hex_outline as
select w.ward_num, max(w.ward_label) as ward_label, max(s.councillor) as councillor,
       count(*) as n_hexes,
       ST_Multi(ST_Union(h.geom))::geometry(MultiPolygon, {srid}) as geom
from hex_ward w
join src_hex h using (hex_id)
join src_ward s using (ward_num)
group by w.ward_num;
alter table ward_hex_outline add primary key (ward_num);
create index on ward_hex_outline using gist (geom);
