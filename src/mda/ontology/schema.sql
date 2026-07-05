create extension if not exists postgis;

create table if not exists source (
    source_id text primary key,
    kind text not null,
    base_url text,
    license text,
    description text
);

create table if not exists method_registry (
    method_version text primary key,
    code_commit_sha text,
    config_snapshot jsonb,
    description text,
    created_at timestamptz not null default now()
);

create table if not exists vessel (
    vessel_id text primary key,
    mmsi bigint,
    imo bigint,
    name text,
    vessel_type text,
    length_m double precision,
    owner text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists vessel_mmsi_idx on vessel (mmsi);
create index if not exists vessel_imo_idx on vessel (imo);

create table if not exists vessel_registry_snapshot (
    vessel_id text not null references vessel (vessel_id),
    attribute text not null,
    value text,
    valid_from timestamptz,
    valid_to timestamptz,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text,
    primary key (vessel_id, attribute, valid_from)
);

create table if not exists facility (
    facility_id text primary key,
    name text,
    name_ko text,
    kind text not null,
    geom geometry(Point, 4326),
    country text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists facility_geom_idx on facility using gist (geom);

create table if not exists zone (
    zone_id text primary key,
    name text,
    kind text not null,
    role text,
    region_id text,
    geom geometry(Geometry, 4326) not null,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists zone_geom_idx on zone using gist (geom);
create index if not exists zone_region_idx on zone (region_id);

create table if not exists event (
    event_id text primary key,
    name text not null,
    event_type text,
    event_date date not null,
    zone_id text references zone (zone_id),
    aoi_id text,
    description text,
    citations text[],
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);

alter table event add column if not exists region_id text;
alter table event add column if not exists geom geometry(Point, 4326);

create table if not exists backtest_config (
    event_id text primary key references event (event_id),
    search_days_before int not null,
    search_days_after int not null
);

create table if not exists document (
    document_id text primary key,
    doc_type text not null,
    title text,
    lang text,
    url text,
    published_at timestamptz,
    text_excerpt text,
    sha256 text,
    region_id text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists document_published_idx on document (published_at);

create table if not exists alert (
    alert_id text primary key,
    alert_type text not null,
    level text,
    vessel_id text references vessel (vessel_id),
    zone_id text references zone (zone_id),
    region_id text,
    generated_at timestamptz not null,
    method_version text,
    score double precision,
    title_ko text,
    title_en text,
    why text[],
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists alert_generated_idx on alert (generated_at);
create index if not exists alert_vessel_idx on alert (vessel_id);

create table if not exists alert_timeline_step (
    alert_id text not null references alert (alert_id) on delete cascade,
    step_no int not null,
    phase text,
    ts timestamptz,
    description text,
    primary key (alert_id, step_no)
);

create table if not exists alert_evidence (
    evidence_id bigserial primary key,
    alert_id text not null references alert (alert_id) on delete cascade,
    term_name text not null,
    points double precision not null,
    src_table text not null,
    src_id text not null,
    detail text,
    method_version text not null
);
create index if not exists alert_evidence_alert_idx on alert_evidence (alert_id);

create table if not exists entity_link (
    link_id text primary key,
    src_type text not null,
    src_id text not null,
    dst_type text not null,
    dst_id text not null,
    rel_type text not null,
    confidence double precision,
    hypothesis boolean not null default false,
    method_version text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists entity_link_src_idx on entity_link (src_type, src_id);
create index if not exists entity_link_dst_idx on entity_link (dst_type, dst_id);

create table if not exists ais_position (
    mmsi bigint not null,
    ts timestamptz not null,
    vessel_id text,
    geom geometry(Point, 4326) not null,
    sog double precision,
    cog double precision,
    heading double precision,
    nav_status text,
    msg_type text,
    region_id text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text,
    primary key (mmsi, ts)
);
create index if not exists ais_position_ts_idx on ais_position using brin (ts);
create index if not exists ais_position_vessel_idx on ais_position (vessel_id, ts);
create index if not exists ais_position_geom_idx on ais_position using gist (geom);
create index if not exists ais_position_region_idx on ais_position (region_id, ts);

create table if not exists sar_detection (
    detection_id text primary key,
    ts timestamptz not null,
    geom geometry(Point, 4326),
    length_est_m double precision,
    confidence double precision,
    sensor text,
    matched_vessel_id text references vessel (vessel_id),
    region_id text,
    aoi_id text,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists sar_detection_ts_idx on sar_detection (ts);
create index if not exists sar_detection_geom_idx on sar_detection using gist (geom);

create table if not exists signal_daily (
    aoi_id text not null,
    date date not null,
    signal_name text not null,
    value double precision,
    method_version text not null,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text,
    primary key (aoi_id, date, signal_name, method_version)
);
create index if not exists signal_daily_lookup_idx on signal_daily (aoi_id, signal_name, date);

create table if not exists weather_daily (
    region_id text not null,
    date date not null,
    wind_speed double precision,
    wave_height double precision,
    visibility double precision,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text,
    primary key (region_id, date)
);

create table if not exists osint_item (
    item_id text primary key,
    ts timestamptz not null,
    region_id text,
    kind text,
    lang text,
    source_module text not null,
    text text,
    sentiment double precision,
    weight double precision,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);
create index if not exists osint_item_ts_idx on osint_item (ts);
create index if not exists osint_item_region_idx on osint_item (region_id, ts);

create table if not exists index_daily (
    aoi_id text not null,
    date date not null,
    index_value double precision,
    raw_score double precision,
    level text,
    method_version text not null,
    config_hash text,
    fetched_at timestamptz not null default now(),
    primary key (aoi_id, date, method_version)
);

create table if not exists index_contribution (
    aoi_id text not null,
    date date not null,
    signal_name text not null,
    z_clip double precision,
    index_points double precision,
    method_version text not null,
    primary key (aoi_id, date, signal_name, method_version)
);

create table if not exists backtest_result (
    event_id text not null references event (event_id),
    method_version text not null,
    lead_time_days int,
    peak_index double precision,
    peak_date date,
    peak_percentile double precision,
    false_positive_episodes int,
    computed_at timestamptz not null default now(),
    primary key (event_id, method_version)
);

create table if not exists collector_gap (
    gap_id bigserial primary key,
    source_id text not null,
    collector text not null,
    region_id text,
    started_at timestamptz not null,
    ended_at timestamptz,
    reason text
);
create index if not exists collector_gap_source_idx on collector_gap (source_id, started_at);

create table if not exists foundry_sync_state (
    object_type text primary key,
    last_synced_at timestamptz not null
);

create table if not exists artifact_snapshot (
    snapshot_id text primary key,
    schema_version text,
    generated_at timestamptz,
    payload jsonb,
    source_id text,
    collector text,
    fetched_at timestamptz not null default now(),
    raw_ref text
);

create table if not exists scenario (
    scenario_id text primary key,
    name_ko text not null,
    name_en text,
    description text,
    kind text not null,
    created_at timestamptz not null default now()
);
