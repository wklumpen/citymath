-- Share of each parcel falling in each hex, by area.
-- `share` is renormalised per parcel so a parcel's full value is always
-- allocated, even if part of it pokes outside the hex grid.
drop table if exists hex_parcel cascade;
create table hex_parcel as
with x as (
    select h.hex_id, p.parcel_id,
           case when ST_Within(p.geom, h.geom) then ST_Area(p.geom)
                else ST_Area(ST_Intersection(p.geom, h.geom)) end as area_m2
    from src_parcel p
    join src_hex h on ST_Intersects(p.geom, h.geom)
)
select hex_id, parcel_id, area_m2,
       area_m2 / sum(area_m2) over (partition by parcel_id) as share
from x
where area_m2 > 0;
create index on hex_parcel (parcel_id);
analyze hex_parcel;

-- Assessed value and land area by class per hex. A parcel's land area is
-- split between classes by value (or goes to its main class if it has none).
drop table if exists hex_assessment cascade;
create table hex_assessment as
with p as (
    select parcel_id, n_rolls, value_res, value_nonres, value_farm, value_exempt,
           value_res + value_nonres + value_farm as value_total,
           main_class
    from src_parcel
),
s as (
    select hp.hex_id, hp.share, hp.area_m2, p.*,
           case when value_total > 0 then value_res / value_total
                else (main_class = 'RE')::int end as f_res,
           case when value_total > 0 then value_nonres / value_total
                else (main_class = 'NR')::int end as f_nonres,
           case when value_total > 0 then value_farm / value_total
                else (main_class = 'FL')::int end as f_farm
    from hex_parcel hp
    join p using (parcel_id)
)
select h.hex_id,
       count(s.parcel_id)                            as n_parcels,
       coalesce(sum(s.share * s.n_rolls), 0)::float8 as n_rolls,
       coalesce(sum(s.share * s.value_res), 0)::float8    as value_res,
       coalesce(sum(s.share * s.value_nonres), 0)::float8 as value_nonres,
       coalesce(sum(s.share * s.value_farm), 0)::float8   as value_farm,
       coalesce(sum(s.share * s.value_exempt), 0)::float8 as value_exempt,
       coalesce(sum(s.area_m2 * s.f_res), 0)::float8    as land_m2_res,
       coalesce(sum(s.area_m2 * s.f_nonres), 0)::float8 as land_m2_nonres,
       coalesce(sum(s.area_m2 * s.f_farm), 0)::float8   as land_m2_farm
from src_hex h
left join s using (hex_id)
group by h.hex_id;
alter table hex_assessment add primary key (hex_id);
