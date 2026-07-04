# MDA Ontology Platform

An extensible maritime-domain-awareness (MDA) data ontology for the F4GE tracks
**"unstructured-data dark/disguised-vessel detection"** and **"OSINT gray-zone
early warning"**. It fuses many free/real feeds into one entity-centric store
(PostGIS), runs track-1/track-2 analysis on top, and drives a real-time
intelligence dashboard. Priority theatre: the Korean **West Sea (Yellow Sea)**;
global coverage where the source allows. Users: ROK military.

This merges two prior systems — a GDELT+GFW **pre-sail escalation index** (batch,
causal, backtested) and **SEASENTINEL** (a Palantir-Gotham-style triage
dashboard) — and replaces SEASENTINEL's synthetic inputs with real data.

## Architecture (three layers)

1. **System of record** — a dedicated `postgis/postgis` container on beelink
   (`compose.yml`, port 5434). Holds every curated entity + observation +
   derived signal. Schema is one file: `src/mda/ontology/schema.sql` (25 tables),
   designed 1:1 with Palantir Foundry ObjectTypes.
2. **Firehose overflow** — a local partitioned parquet lake (`data/lake/`) for the
   global AIS stream when enabled (`--to-lake`); the West Sea stream lands
   full-fidelity in Postgres.
3. **Semantic ontology (Foundry)** — bounded curated objects sync on top
   (`mda foundry-sync`), MCP-gated (types designed once Palantir MCP is enabled).

## Data sources (all real)

| Feed | Source | Access |
|---|---|---|
| Realtime AIS positions/identity | [AISStream.io](https://aisstream.io) WebSocket | free key |
| AIS/SAR daily aggregates | Global Fishing Watch 4Wings | bearer token |
| News volume/tone (EN+ZH) | GDELT DOC 2.0 | no key |
| Darkweb/Telegram OSINT | StealthMole Telegram Tracker | per-request JWT |
| Marine + weather (wave/wind) | Open-Meteo | no key |
| Sanctioned vessels | OFAC SDN + UN 1718 (DPRK) | public |
| Ports | NGA World Port Index | public |
| Submarine cables | TeleGeography cable map | public |
| Coastline | Natural Earth | public |
| Curated West Sea incidents | CSIS/AMTI, Coast Guard, news (cited) | `config/incidents.yaml` |

## Ontology (schema.sql)

- **Entities**: `vessel` (+`vessel_registry_snapshot`), `facility`, `zone`,
  `event` (+`backtest_config`), `document`, `alert` (+`alert_timeline_step`),
  generic `entity_link`.
- **Observations**: `ais_position`, `sar_detection`, `signal_daily`,
  `weather_daily`, `osint_item`.
- **Derived (versioned)**: `index_daily`, `index_contribution`,
  `backtest_result`, `method_registry`.
- Every row carries provenance (`source_id, collector, fetched_at, raw_ref`).
  Geometry is PostGIS (`ST_Contains`/`ST_DWithin` power geofence + proximity).

## Setup

```
uv sync
cp .env.example .env    # fill AISSTREAM_API_KEY, STEALTHMOLE_*, GFW_TOKEN, MDA_PG_DSN
uv run mda init-db      # apply schema to Postgres
```

## Collect (each writes real rows to the ontology)

```
uv run mda migrate                                   # legacy GDELT/GFW/index → DB
uv run mda run --start 2020-08-01 --end 2024-12-31   # pre-sail index + backtest → DB
uv run mda ais-stream --regions west_sea --duration 900
uv run mda collect-weather --start 2020-08-01 --end 2024-12-31
uv run mda collect-reference                         # OFAC + UN1718 + WPI + cables + incidents
uv run mda collect-stealthmole --max-items 200
uv run mda analyze                                   # track-1/2 alerts (dark-vessel, cable, sanctions)
```

## Dashboard (real data)

```
uv run mda export-dashboard --region west_sea --hours 72   # DB → dashboard/data/*.json
cd dashboard && PORT=3011 uv run python server.py
```

The SEASENTINEL frontend is unchanged except its time axis now derives from the
exported window; TRIAGE, dark-vessel detection, geofence intrusion, SAR↔AIS
matching, entity graph, and the LLM copilot all run over real data.

## Foundry sync (MCP-gated)

```
uv run mda foundry-sync    # dry-run until FOUNDRY_HOST/TOKEN set + MCP enabled
```

Syncs a bounded set (observed+sanctioned vessels, events, alerts, sanctions
docs, daily index) — never the raw AIS firehose.

## Pre-sail index findings (real backtest, index.v1)

| event | lead | peak | note |
|---|---|---|---|
| Sabina/Escoda 2024 | **45 days** | 96.3 | sustained massing — weeks of early warning |
| Scarborough 2024 | 42 days | 87.8 | staging-port + news precursors now lead the incident |
| Whitsun 2021 | none | 32.6 | AIS-dark militia — the gap that motivates SAR/OSINT fusion |

`hainan_staging` is now wired: its AIS presence feeds the reef indices as a
`gfw_staging_presence_hours` signal (rear-port precursor). Every value feeding
`index[t]` comes strictly from before `t` (no-lookahead test enforced).

## Tests

```
uv run pytest    # 30 tests
```

## Honest scope / known gaps

- **SAR per-detection**: GFW gives daily aggregates only; `sar.json` stays empty
  until a real per-detection feed (e.g. Sentinel-1) is integrated — never synthetic.
- **NLL geofence**: no authoritative public coordinate list exists; not fabricated.
- **ffill tradeoff**: applying `ffill_max_days` to sparse signals raised lead time
  but also false-positive episodes; signal-specific ffill is a future tuning knob.
- **Chinese GDELT / Hainan GDELT** can fall back to empty under GDELT's rate limit;
  re-run after cooldown (throttle never poisons the cache).
- Synthetic SEASENTINEL data is preserved under `simulation/` for scenario replay,
  never mixed into the real store.
