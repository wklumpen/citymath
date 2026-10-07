-- A roll that spans several parcels repeats its full value on every one, so
-- each row gets only its polygon's share (by area) of the roll's value.
with a as (
    select coalesce({parcel_id}, {roll_number}) as parcel_id,
           {comm_code} as comm_code, {class} as class, geom,
           {res} as res, {nonres} as nonres, {farm} as farm,
           ({sub_use} = any ({exempt_codes}::text[])
               or {sub_use} like any ({exempt_prefixes}::text[])
               or ltrim({roll_number}, '0') = any ({exempt_rolls}::text[])) is true as exempt,
           coalesce(ST_Area(geom) / nullif(sum(ST_Area(geom)) over (
               partition by {roll_number}), 0), 1) as w
    from {table}
    where geom is not null
)
select parcel_id,
       max(comm_code),
       sum(w),
       mode() within group (order by class),
       coalesce(sum(w * res) filter (where not exempt), 0),
       coalesce(sum(w * nonres) filter (where not exempt), 0),
       coalesce(sum(w * farm) filter (where not exempt), 0),
       coalesce(sum(w * (coalesce(res, 0) + coalesce(nonres, 0) + coalesce(farm, 0)))
                filter (where exempt), 0),
       ST_Transform((array_agg(geom))[1], {srid})
from a
group by 1
