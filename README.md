# Pre-Sail Index

Early-warning index for maritime gray-zone escalation in the South China Sea.
It fuses free open-source signals into a per-location "pre-sail" score (0-100)
that rises **before** documented militia massing events, giving watch officers
lead time instead of after-the-fact situational awareness.

The thesis: a militia sortie is preceded by observable precursors — a rise in
physical vessel presence at the target reef and a rise in multilingual news
chatter. Physical presence (satellite/AIS) tends to lead the news cycle. The
index quantifies and fuses both, then backtests against real 2021 and 2024
events to show the signal crossed a WATCH threshold days ahead.

## Data sources (all free, no scraping)

| Signal | Source | Access |
|---|---|---|
| News volume + tone (EN + ZH) | [GDELT DOC 2.0 API](https://www.gdeltproject.org/) | No key |
| AIS vessel presence (hours/day) | [Global Fishing Watch 4Wings API](https://globalfishingwatch.org/our-apis/) | Free bearer token |
| SAR satellite detections (count/day) | Global Fishing Watch SAR presence | Free bearer token |

Everything is pulled through documented public APIs. No web scraping, no paid
feeds. GFW usage is under its non-commercial API terms.

## Setup

```
uv sync
cp .env.example .env       # then paste your GFW token into GFW_TOKEN
```

Get a free GFW token at https://globalfishingwatch.org/our-apis/tokens.
Without a token the pipeline still runs in `--gdelt-only` mode.

## Run the full pipeline + backtest

```
uv run python -m presail.cli run --start 2020-08-01 --end 2024-12-31
```

This fetches (and caches) all signals, builds the index, backtests the three
events, renders charts to `charts/`, and writes `data/artifacts/latest.json`
(the schema-1.0 contract consumed by the dashboard phase).

Individual stages:

```
uv run python -m presail.cli fetch-gdelt --query '("Whitsun Reef" OR "Julian Felipe Reef")' --start 2021-01-01 --end 2021-04-01
uv run python -m presail.cli fetch-gfw --aoi hainan_staging --start 2021-02-20 --end 2021-03-10
uv run python -m presail.cli build-index --start 2020-08-01 --end 2024-12-31
uv run python -m presail.cli backtest
```

All API responses cache to `data/raw/`; re-runs are offline and instant.

## Methodology

Per signal, per day, a robust z-score is computed against a **180-day trailing
baseline with a 14-day embargo** (median/MAD), so an in-progress buildup never
contaminates its own baseline. Positive deviations are clipped to [0, 6];
"quieter than usual" contributes nothing to an escalation score. The clipped
z-scores are weight-averaged (weights in `config/index.yaml`) and passed
through a saturating transform to a 0-100 index. The composite headline score
is the **max** across locations (a sortie is an OR across staging areas).

Every value feeding `index[t]` comes from strictly before `t` — the causality
guarantee is enforced by `tests/test_index.py` (no-lookahead test).

## Backtest events

| event | date | location |
|---|---|---|
| Whitsun Reef militia massing (~220 vessels) | 2021-03-07 | Whitsun / Julian Felipe Reef |
| Scarborough Shoal water-cannon escalation | 2024-04-30 | Scarborough Shoal |
| Sabina/Escoda Shoal escalation (203 vessels) | 2024-08-31 | Sabina Shoal |

Metrics: **lead time** (days the index crossed WATCH before the event), peak
percentile vs the location's own baseline, and false-positive episodes in
quiet periods.

## Findings (real-data backtest)

| event | pattern | result |
|---|---|---|
| Sabina/Escoda 2024 | prolonged multi-week massing | **WATCH crossed ~45 days before** the Aug 31 escalation, sustained ALERT through it |
| Scarborough 2024 | sudden water-cannon incident | same-day ALERT detection (no early warning — a discrete event) |
| Whitsun Reef 2021 | AIS-dark militia | AIS presence stayed flat (vessels went dark); index fired only when news broke — the hard case that motivates SAR/OSINT fusion |

The honest narrative is stronger than "everything triggered": the system buys
weeks of warning for the sustained massing operations that can actually be
pre-empted (Sabina), detects sudden incidents on the day (Scarborough), and
transparently exposes the dark-vessel gap (Whitsun) where AIS alone is blind.

## Honest scope

- Two of the planned GFW signals (AIS-gap and port-visit events) require an
  Events-API permission tier this token does not have (HTTP 403). The index
  runs on **seven signals** (five GDELT + AIS presence + SAR presence) and
  renormalizes weights over whatever signals are available.
- With three labeled events this is a **case study**, not a statistically
  powered ROC/PR evaluation. It demonstrates the signal exists and leads; it
  does not claim a tuned production detector.
- Reef bounding boxes were verified against published coordinates and
  confirmed empirically (vessel presence spikes on the event dates).
- GDELT enforces a strict ~1-request/5s rate limit. The client throttles and
  backs off; a cold full build takes a few minutes. Chinese-language queries
  that miss the cache during a rate-limit window fall back to empty and simply
  drop out of the weighted average (English + AIS + SAR still carry the index).
  Re-running once the limit clears fills them in.

## Tests

```
uv run pytest
```
