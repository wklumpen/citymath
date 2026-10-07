create index on src_hex using gist (geom);
create index on src_community using gist (geom);
create index on src_road using gist (geom);
create index on src_parcel using gist (geom);
analyze src_hex;
analyze src_community;
analyze src_road;
analyze src_parcel;
