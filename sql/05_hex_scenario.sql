-- Road cost, net and road share for every pavement scenario: one row per hex
-- per scenario, with geometry, so a map can be filtered on `scenario`.
drop table if exists hex_scenario cascade;
create table hex_scenario as
with x as (
    select s.hex_id, c.scenario, c.label, s.ward_num, s.comm_structure, s.is_special, s.revenue_total,
           s.hex_area_ha, s.geom,
           c.cost_low * b.m2 as road_cost_low,
           (c.cost_low + c.cost_high) / 2 * b.m2 as road_cost,
           c.cost_high * b.m2 as road_cost_high
    from hex_summary s
    cross join cfg_scenario c
    cross join (select sum(pavement_m2) as m2 from hex_summary) t
    cross join lateral (
        -- life: one-off cost spread over each class's life; flat: annual rate;
        -- budget: a citywide amount shared out by pavement area
        select case c.kind when 'life' then s.pavement_m2_per_year
                           when 'flat' then s.pavement_m2
                           else s.pavement_m2 / t.m2 end as m2
    ) b
)
select hex_id, scenario, label, ward_num, comm_structure, is_special, revenue_total,
       road_cost_low, road_cost, road_cost_high,
       revenue_total - road_cost_high as net_low,
       revenue_total - road_cost as net,
       revenue_total - road_cost_low as net_high,
       (revenue_total - road_cost) / hex_area_ha as net_per_ha,
       road_cost_low / nullif(revenue_total, 0) as road_share_low,
       road_cost / nullif(revenue_total, 0) as road_share,
       road_cost_high / nullif(revenue_total, 0) as road_share_high,
       geom
from x;
alter table hex_scenario add primary key (hex_id, scenario);
create index on hex_scenario using gist (geom);

-- Ward totals for every scenario, with the ward's hex outline for mapping.
drop table if exists ward_scenario cascade;
create table ward_scenario as
select x.ward_num, x.scenario, x.label, o.ward_label, count(*) as n_hexes,
       sum(x.revenue_total) as revenue_total,
       sum(x.road_cost_low) as road_cost_low, sum(x.road_cost) as road_cost,
       sum(x.road_cost_high) as road_cost_high,
       sum(x.road_cost) / nullif(sum(x.revenue_total), 0) as road_share,
       sum(x.road_cost) / nullif(sum(x.revenue_total) * %(mobility_share)s::float8, 0) as mobility_ratio,
       o.geom
from hex_scenario x
join ward_hex_outline o using (ward_num)
group by x.ward_num, x.scenario, x.label, o.ward_label, o.geom;
alter table ward_scenario add primary key (ward_num, scenario);
