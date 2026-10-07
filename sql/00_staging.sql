-- Staging copies of the source layers, all in the project SRID.
-- Column order must match the sql/src_*.sql selects.
drop table if exists src_hex cascade;
create table src_hex (
    hex_id integer primary key,
    geom   geometry(MultiPolygon, {srid})
);

drop table if exists src_community cascade;
create table src_community (
    comm_code      text,
    name           text,
    class          text,
    sector         text,
    comm_structure text,
    geom           geometry(MultiPolygon, {srid})
);

drop table if exists src_road cascade;
create table src_road (
    road_id bigint primary key,
    osm_id  text,
    highway text,
    name    text,
    ref     text,
    surface text,
    geom    geometry(Geometry, {srid})
);

-- One row per parcel polygon; condo units sharing a polygon are summed.
drop table if exists src_parcel cascade;
create table src_parcel (
    parcel_id    text primary key,
    comm_code    text,
    n_rolls      numeric,
    main_class   text,
    value_res    numeric,
    value_nonres numeric,
    value_farm   numeric,
    value_exempt numeric,
    geom         geometry(Geometry, {srid})
);
