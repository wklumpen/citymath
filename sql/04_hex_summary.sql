-- One row per hex: community tag, road lengths and cost, assessed value and
-- municipal tax revenue, and the net. This is the table to load in QGIS.
drop table if exists hex_summary cascade;
create table hex_summary as
with lw as (
    -- width per hex and class: sampled by community structure where available
    select l.hex_id, l.road_class, l.length_m, c.life_years, c.shared,
           l.length_m * coalesce(w.width_median, c.width_m) as m2
    from hex_road_length l
    join cfg_road_class c using (road_class)
    join hex_community hc using (hex_id)
    left join comm_structure_width w
           on w.comm_structure = hc.comm_structure
          and l.road_class = %(sampled_class)s
),
shared as (
    -- citywide pavement of the shared classes, to be spread across hexes
    select coalesce(sum(m2), 0) as m2, coalesce(sum(m2 / life_years), 0) as m2_per_year
    from lw where shared
),
r as (
    select h.hex_id,
           {road_cols},
           coalesce(sum(l.length_m), 0) as road_m_total,
           coalesce(sum(l.m2) filter (where not l.shared), 0) as pavement_m2_local,
           coalesce(sum(l.m2 / l.life_years) filter (where not l.shared), 0) as local_m2_per_year
    from src_hex h
    left join lw l using (hex_id)
    group by h.hex_id
),
j as (
    select *
    from src_hex
    join hex_community using (hex_id)
    join hex_assessment using (hex_id)
    join r using (hex_id)
    join hex_structure_pct using (hex_id)
    left join comm_structure_width using (comm_structure)
),
k as (
    select *,
           ST_Area(geom) / 10000 as hex_area_ha,
           coalesce(comm_structure = any (%(special)s::text[]), false) as is_special,
           value_res + value_nonres + value_farm as value_total,
           value_res * %(rate_res)s::float8 as revenue_res,
           value_nonres * %(rate_nonres)s::float8 as revenue_nonres,
           value_farm * %(rate_farm)s::float8 as revenue_farm,
           value_res * %(prov_res)s::float8 + value_nonres * %(prov_nonres)s::float8
               + value_farm * %(prov_farm)s::float8 as tax_provincial
    from j
),
t as (
    select *, revenue_res + revenue_nonres + revenue_farm as revenue_total,
           revenue_res + revenue_nonres + revenue_farm + tax_provincial as tax_total
    from k
),
u as (
    -- each hex's slice of the shared pavement
    select t.*,
           case %(shared_basis)s
               when 'equal' then 1.0 / count(*) over ()
               when 'area' then hex_area_ha / sum(hex_area_ha) over ()
               when 'revenue' then revenue_total / sum(revenue_total) over ()
           end as shared_weight
    from t
),
v as (
    select u.*,
           shared_weight * shared.m2 as pavement_m2_shared,
           pavement_m2_local + shared_weight * shared.m2 as pavement_m2,
           -- pavement reconstructed in an average year, given each class's life
           local_m2_per_year + shared_weight * shared.m2_per_year as pavement_m2_per_year
    from u cross join shared
),
x as (
    select *,
           {cost_basis} * %(cost_low)s::float8 as road_cost_low,
           {cost_basis} * (%(cost_low)s::float8 + %(cost_high)s::float8) / 2 as road_cost,
           {cost_basis} * %(cost_high)s::float8 as road_cost_high
    from v
)
select *,
       revenue_total - road_cost_high as net_low,
       revenue_total - road_cost as net,
       revenue_total - road_cost_low as net_high,
       revenue_total / hex_area_ha as revenue_per_ha,
       road_cost / hex_area_ha as road_cost_per_ha,
       (revenue_total - road_cost) / hex_area_ha as net_per_ha,
       -- share of municipal tax revenue needed to pay for the hex's roads
       road_cost_low / nullif(revenue_total, 0) as road_share_low,
       road_cost / nullif(revenue_total, 0) as road_share,
       road_cost_high / nullif(revenue_total, 0) as road_share_high
from x;
alter table hex_summary drop column local_m2_per_year;
alter table hex_summary add primary key (hex_id);
create index on hex_summary using gist (geom);
