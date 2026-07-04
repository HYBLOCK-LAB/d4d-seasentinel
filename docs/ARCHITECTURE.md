# MDA 플랫폼 3계층 아키텍처 — 소스 데이터 · 온톨로지 · 솔루션

> 문서 성격: 소스 연동 → 온톨로지 → 분석/예측 솔루션까지 전 계층의 현재 상태 정리.
> 모든 수치는 2026-07-05 기준 운영 DB(`MDA_PG_DSN`, beelink PostGIS) 직접 집계 결과.
> 구현 완료 항목과 설계 단계 항목을 구분해 표기함. 문제 정의·백테스트 상세는 `docs/OVERVIEW.md` 참조.

---

## 0. 전체 데이터 흐름

```
[소스 10종]                [온톨로지 (PostGIS, schema.sql 23테이블)]        [솔루션]
AISStream ─────────────▶ vessel + ais_position ──────────┐
GFW 4Wings ────────────▶ signal_daily                    ├─▶ 사전징후 지수(index.v1)
GDELT ─────────────────▶ signal_daily                    │   └ index_daily / contribution
Open-Meteo ────────────▶ weather_daily                   ├─▶ 백테스트(backtest_result)
StealthMole ───────────▶ osint_item + document           ├─▶ 규칙 경보(tracks.v1 → alert)
OFAC/UN1718 ───────────▶ vessel + document               ├─▶ 대시보드(export-dashboard)
WPI/케이블/해안선 ─────▶ facility + zone                 ├─▶ LLM 코파일럿(dashboard/server.py)
incidents.yaml ────────▶ event                           └─▶ Foundry 온톨로지(foundry-sync)
                          ↑ 전 행 provenance:                [설계] 확률 예측 계층
                            source_id/collector/               forecast + forecast_evidence
                            fetched_at/raw_ref
```

---

## 1. 소스 데이터 계층

`source` 테이블 등록 기준 10종. 수집 코드는 10종 전부 실데이터로 검증되었으나,
적재 수준은 소스마다 다름.

### 1.1 연동 실태 (DB 실측)

| 분류 | 소스 | 적재량 | 기간 | 연동 수준 |
|---|---|---|---|---|
| 해상 AIS (실시간) | AISStream WebSocket | 위치 223행, 선박 50척 | 2026-07-04 하루 | 코드 완성, 상시 수집 미가동 |
| AIS 집계 | GFW 4Wings presence | 1,923행 + staging 531행 | 2020-08~2024-09 | 양호, 백필 이후 갱신 없음 |
| 위성 SAR (집계) | GFW SAR presence | 114행 | 2020-08~2024-09 | 희소 (AOI 일 집계) |
| 위성 SAR (개별 탐지) | `sar_detection` | **0행** | — | 스키마만 존재, 피드 미확보 |
| 입출항 | gfw_port_visit_count / gfw_ais_gap_count | **0행** | — | 지수 가중치만 배정, 수집 이력 없음 |
| 기상 | Open-Meteo | 4,842행 | 2020-08~2024-12 | 백필 완료, 현행화 없음 |
| OSINT | StealthMole Telegram | 215건 | 2017-12~2026-05 | 수집기 작동, 주기 실행 없어 희소 |
| 뉴스 (영어) | GDELT EN 3종 + tone | 4,872행 | 2020-08~2024-09 | 가장 충실 |
| 뉴스 (중국어) | GDELT ZH 2종 | **0행** | — | 가중치 0.20 배정, 레이트리밋 낙착으로 빈 상태 |
| 제재·기준정보 | OFAC 1,496척 + UN1718 15척 + 제재문서 1,512 + WPI 항만 3,689 + 케이블 존 695 + 사건 19건 | 정적 | — | 완전 적재 |

### 1.2 저장 인프라

- **시스템 오브 레코드**: beelink `postgis/postgis:16` (포트 5434), tailscale 경유 접근.
- **파이어호스 오버플로**: 로컬 parquet 레이크(`data/lake/`) — 현재 비어 있음.
- **S3** (`s3://mda-lake`, durumari MinIO): 대시보드 아티팩트 1개만 존재. 비공개 유지.

### 1.3 미연동/공백 항목 (심각도 순)

1. **시간축 정지 (전 소스 공통)** — 신호·지수·기상이 2024-09~12에서 종료. 상시 수집
   데몬이 없어 현재는 "과거 백테스트 시스템" 상태. 확률 계산에 필요한 평시 기저율도
   여기에 걸려 있음.
2. **입출항 신호 0행** — GFW port-visits API로 채울 수 있으며 RFP의 "배후 항만
   물류·군집 징후"에 직결.
3. **중국어 GDELT 0행** — 쿨다운 후 재수집으로 복구 가능.
4. **개별 SAR 탐지 0행** — AIS-dark 검증(Whitsun 2021 미탐 원인)의 유일한 수단.
   Sentinel-1 연동 전까지 구조적 공백으로 명시.
5. **OSINT 희소 (215건)** — 키워드 확장 + 주기 수집 필요.

---

## 2. 온톨로지 계층

단일 스키마 파일 `src/mda/ontology/schema.sql` (테이블 23개), Foundry ObjectType과
1:1 대응 설계. 전 테이블 공통 provenance 4컬럼(`source_id, collector, fetched_at,
raw_ref`), 지오메트리는 PostGIS(공간 인덱스 포함).

### 2.1 테이블 구성 (3계층 + 운영)

| 계층 | 테이블 | 역할 |
|---|---|---|
| 개체 | `vessel`(+`vessel_registry_snapshot`), `facility`, `zone`, `event`(+`backtest_config`), `document`, `alert`(+`alert_timeline_step`), `entity_link` | 실세계 엔티티와 그 관계 |
| 관측 | `ais_position`, `sar_detection`, `signal_daily`, `weather_daily`, `osint_item` | 시점 부착 원시/집계 관측 |
| 파생 | `index_daily`, `index_contribution`, `backtest_result`, `method_registry` | 버전 관리되는 분석 산출물 |
| 운영 | `source`, `collector_gap`, `foundry_sync_state`, `artifact_snapshot` | 소스 등록·수집 공백·동기화 상태 |

### 2.2 소스 → 테이블 매핑 (수집기별)

| 수집기 | 기록 대상 | 방식 |
|---|---|---|
| `aisstream_realtime` | `vessel` + `ais_position` | MMSI 키 업서트, 위치 (mmsi, ts) PK |
| `gdelt` | `signal_daily` | AOI 쿼리 → 일 단위 신호 (기사 원문 미보관) |
| `gfw` | `signal_daily` | 4Wings 타일 → AOI 일 집계 |
| `weather_openmeteo` | `weather_daily` | region 일별 파고·풍속 |
| `stealthmole` | `osint_item` + `document` | 텔레그램 원문·감성 포함 |
| `reference` | `vessel`, `document`, `facility`, `zone`, `event` | 정적 기준정보 일괄 |
| 파이프라인 | `index_daily/contribution`, `backtest_result`, `alert`, `entity_link` | 파생 계층 생성 |

### 2.3 객체 간 관계 — 설계 2종, 충족률 실측

**(a) 고정 FK 관계**

| 관계 | 실측 (2026-07-05) |
|---|---|
| ais_position → vessel | 223/223 연결 |
| alert → vessel | 3/3 연결 (AIS 공백형 dark_vessel) |
| event → zone | 3/19 연결, 16건은 `region_id` 문자열 참조만 |
| sar_detection → vessel | 0/0 (데이터 부재) |
| signal_daily.aoi_id ↔ zone(kind='aoi') | soft key, AOI 존 4개와 대응 |
| region_id ↔ zone(kind='region') | soft key, region 3개와 대응 |

**(b) 범용 그래프 `entity_link`** — (src_type, src_id)→(dst_type, dst_id) +
`rel_type`, `confidence`, `hypothesis`. `tracks.py`가 `near_cable`, `sanctioned_as`
링크를 생성하도록 구현되어 있으나 **현재 0행** (하루치 AIS에서 케이블 3km 근접·제재
IMO 일치 미발생). 가설적 관계(선단 소속 추정 등)를 확정 관계와 구분할 컬럼 구조는
준비됨.

### 2.4 Foundry 시맨틱 온톨로지 (라이브)

- 프로젝트 "Maritime MDA Ontology", ObjectType 5개(Vessel/Facility/MaritimeEvent/
  Alert/Zone) + Vessel→Alert LinkType, 브랜치 `mda-ontology-v1`.
- Vessel 1,561객체 라이브 검증. RID 일체는 `config/foundry.yaml`.
- 동기화 범위는 큐레이션된 개체로 한정(AIS 파이어호스 제외), `mda foundry-sync`.

---

## 3. 솔루션 계층

### 3.1 구현 완료

**사전징후 지수 (index.v1)** — `pipelines/index.py`
- 신호별 robust-z(중앙값·MAD, baseline 180일 + embargo 14일) → 가중합 →
  `100·(1−exp(−raw/1.5))` → 0–100 지수, WATCH 65 / ALERT 80.
- 기여도는 `index_contribution`에 신호 단위로 분해 저장 (설명가능성의 기반 패턴).
- no-lookahead: `index[t]`에 들어가는 모든 값은 t 이전 데이터만 사용 (테스트 강제).

**백테스트** — `pipelines/backtest.py` → `backtest_result`
- 지표: 리드타임, 피크, 통제기간 대비 백분위, 오경보 에피소드.
- 실측: Sabina 2024 리드 45일(피크 96.3), Scarborough 2024 42일(87.8),
  Whitsun 2021 미탐(32.6, AIS-dark 민병대 — SAR 공백의 근거 사례).

**규칙 기반 경보 (tracks.v1)** — `pipelines/tracks.py` → `alert`
- AIS 공백 ≥6h → dark_vessel (점수 60+gap시간, ≥12h HIGH).
- 해저케이블 3km 근접 → zone_intrusion + `near_cable` 링크.
- OFAC/UN1718 IMO 일치 → CRITICAL 98 + `sanctioned_as` 링크.
- 한계: 점수가 수기 산식(우도 근거 없음), 수신 커버리지 보정 없음
  (`collector_gap`과 미결합 — 커버리지 공백을 선박 공백으로 오인 가능).

**대시보드 + 코파일럿** — `mda export-dashboard` → `dashboard/` (SEASENTINEL)
- Postgres → 10파일 JSON 계약 → TRIAGE·다크베슬·지오펜스·엔티티 그래프·LLM 코파일럿.
- beelink 배포(포트 8123), LLM 게이트웨이 19모델(기본 gpt-5.4).

### 3.2 설계 단계 — 확률 예측 계층 (미구현)

목표: RFP의 "향후 특정 해역 내 위협 전개 가능성과 시점을 **정량적 확률**로 예측"
+ "위험도 신뢰도 평가". 현 지수는 이상도 점수이며 확률이 아님.

**원리 — 확률은 온톨로지 행 집계**
1. 라벨: `index_daily` 각 (AOI, 날짜)에 y = "이후 h일 내 `event` 존재".
2. 조건부 빈도: P(사건|조건) = 조건 만족일 중 y=1 비율.
3. 소표본 보정: Beta 사후분포 → 점추정 + 신뢰구간 (예: 0.50 [0.19, 0.81]).
4. 다변량 일반화: 로지스틱 hazard
   `log-odds = α_aoi + β·z(staging, 뉴스, tone, …) + s(월)` — 파라미터 10개 미만.
   기상은 학습 아닌 물리 게이트로 곱함: P(행동) = P(의도) × P(기동 가능|파고).
5. 선박 단위(트랙 1)는 곱셈형: 사후 odds = 사전 odds × Π(우도비),
   우도비 = 제재 선박군/일반 선박군 행동 빈도 대비.

**2026-07-05 실측에서 확인된 표본 함정 (설계 근거)**
- WATCH 초과 42에피소드 집계 결과, 지수≥65일의 45일 내 사건율(0.62)이
  지수<65일(0.79)에 못 미치는 역전 발생.
- 원인: (1) 사건 직후 오염(지수 높음, 미래 사건 없음), (2) 사건창 표집 편향 —
  신호가 사건 주변 창에서만 수집되어 잔존 표본의 73%가 y=1인 case-control 표본.
- 결론: 현 데이터로 정당한 것은 상대 위험·리드타임까지. **절대 확률에는 평시
  기저율이 필요** — 상시 수집 전환 또는 외부 앵커(예: 해경 월별 단속 통계,
  AOI-연당 사건율) + case-control 절편 보정.

**온톨로지 통합 — 파생 테이블 2개 추가로 완결**

```sql
forecast          (aoi_id, event_type, horizon_days, issued_at,
                   probability, ci_low, ci_high, method_version)
forecast_evidence (forecast_id, term_name, log_odds_delta,
                   src_table, src_id)   -- 원천 행 직접 역참조
```

- 근거 추적: 가법 모델만 허용(로그오즈 합 분해 가능)이라는 **모델 제약**으로
  "확률 클릭 → 기여 항 → signal_daily/osint_item 행 → raw_ref 원문" 사슬 보장.
  `index_contribution`의 기존 분해 패턴을 확률에 복제하는 구조.
- Foundry에는 Forecast ObjectType 1개 + LinkType 2개 추가로 대응.

**객관성 절차 7**
1. 라벨 외부성 — `event`는 인용 가능한 외부 출처만, 자체 alert로 라벨 생성 금지(순환 차단).
2. no-lookahead — `fetched_at < t` 행만 사용, provenance로 사후 감사 가능.
3. 사전 등록 — 임계값·호라이즌을 `method_registry`에 commit sha와 동결, 수정은 새 버전.
4. 표본 설계 보정 — 사후 기간 제외 + case-control 절편 보정을 명시 단계로.
5. 교차·전향 검증 — 사건별 leave-one-out 전 결과 공개, 동결 후 신규 사건이 진짜 시험 세트.
6. proper scoring — Brier/로그 점수 + reliability diagram ("40%라 말한 날들의 실제 사건율이 40%인가").
7. 기저선 초과 증명 — 계절 기저율 모델 대비 skill score 보고, 못 이기면 그대로 기록.

**시나리오 시뮬레이션 (설계)** — hazard × 세력 규모(staging 존재량→척수 분포) ×
통항 물리(PostGIS 거리÷선속) Monte Carlo → "D+3~5일, 해역 X, 80–150척, P=0.31
[0.12, 0.55]" 형태 자동 생성.

### 3.3 착수 우선순위

1. 상시 수집 전환 (AIS west_sea 스트림 + GDELT/GFW/기상 크론) — 평시 기저율 확보.
2. 0행 3종 해소: 입출항(GFW port-visits), 중국어 GDELT 재수집, SAR은 한계 명시 유지.
3. 라벨 확장: 해경 단속 통계 → `event` 수백 사건-일 (서해 불법조업 클래스 소표본 해소).
4. `forecast`/`forecast_evidence` 스키마 + 보정(Stage A) → hazard(Stage B) →
   proper scoring 백테스트 확장(Stage D) → 시뮬레이션(Stage C).
5. tracks.v1 점수의 우도 기반 교체 + `collector_gap` 커버리지 보정.
