-- Roads that count toward City cost: a costed class, paved, not provincial.
drop table if exists road_used cascade;
create table road_used as
with base as (
    select r.road_id, k.road_class, r.highway, r.name, r.ref, r.geom,
           string_to_array(replace(coalesce(r.ref, ''), ' ', ''), ';')
               && %(provincial_refs)s::text[] as provincial
    from src_road r
    join cfg_road_highway k using (highway)
    where not (lower(coalesce(r.surface, '')) = any (%(unpaved)s::text[]))
),
prov as (
    select geom from base where provincial
)
select b.road_id, b.road_class, b.highway, b.name, b.ref, b.geom
from base b
where not b.provincial
  and not (right(b.highway, 5) = '_link'
           and exists (select 1 from prov p
                       where ST_DWithin(p.geom, b.geom, %(link_buffer)s)));
create index on road_used using gist (geom);
analyze road_used;

-- Length of road by class inside each hex (long format).
drop table if exists hex_road_length cascade;
create table hex_road_length as
select h.hex_id,
       r.road_class,
       sum(ST_Length(case when ST_Within(r.geom, h.geom) then r.geom
                          else ST_Intersection(r.geom, h.geom) end)) as length_m
from src_hex h
join road_used r on ST_Intersects(r.geom, h.geom)
group by h.hex_id, r.road_class;
alter table hex_road_length add primary key (hex_id, road_class);
