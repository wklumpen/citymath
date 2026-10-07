-- Road cost, net and road share for every pavement scenario: one row per hex
-- per scenario, with geometry, so a map can be filtered on `scenario`.
drop table if exists hex_scenario cascade;
create table hex_scenario as
with x as (
    select s.hex_id, c.scenario, c.label, s.comm_structure, s.is_special, s.revenue_total,
           s.hex_area_ha, s.geom,
           c.cost_low * b.m2 as road_cost_low,
           (c.cost_low + c.cost_high) / 2 * b.m2 as road_cost,
           c.cost_high * b.m2 as road_cost_high
    from hex_summary s
    cross join cfg_scenario c
    cross join lateral (
        select case when c.per_life then s.pavement_m2_per_year
                    else s.pavement_m2 end as m2
    ) b
)
select hex_id, scenario, label, comm_structure, is_special, revenue_total,
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
