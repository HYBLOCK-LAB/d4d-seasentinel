"""Deterministic threat-scenario generators emitting ontology rows.

Scenario content is ported from simulation/generate_data.py (real 2024-2026
incidents: Shunxin-39, Deoksong/DE YI, Eagle S, Yi Peng 3, NLL fleets), with
geometry fitted into the configured region bboxes so scenarios render inside
the dashboard's default map view.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from psycopg import sql

from mda.config import load_regions
from mda.paths import config_path
from mda.store import pg

METHOD = "sim.v1"
COLLECTOR = "sim.preset"
SOURCE_ID = "simulation"

TABLE_ORDER = [
    "source",
    "vessel",
    "zone",
    "facility",
    "event",
    "ais_position",
    "sar_detection",
    "osint_item",
    "alert",
    "alert_evidence",
    "alert_timeline_step",
    "entity_link",
]

CONFLICTS = {
    "source": ["source_id"],
    "vessel": ["vessel_id"],
    "zone": ["zone_id"],
    "facility": ["facility_id"],
    "event": ["event_id"],
    "ais_position": ["mmsi", "ts"],
    "sar_detection": ["detection_id"],
    "osint_item": ["item_id"],
    "alert": ["alert_id"],
    "alert_evidence": ["evidence_id"],
    "alert_timeline_step": ["alert_id", "step_no"],
    "entity_link": ["link_id"],
}


def _point(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({round(lon, 5)} {round(lat, 5)})"


def _linestring(path: list[list[float]]) -> str:
    coords = ", ".join(f"{round(lon, 5)} {round(lat, 5)}" for lon, lat in path)
    return f"SRID=4326;LINESTRING({coords})"


def _polygon(ring: list[list[float]]) -> str:
    closed = ring + [ring[0]] if ring[0] != ring[-1] else ring
    coords = ", ".join(f"{round(lon, 5)} {round(lat, 5)}" for lon, lat in closed)
    return f"SRID=4326;POLYGON(({coords}))"


def _pip(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class _Builder:
    def __init__(self, region_id: str, t0: datetime, window_h: int, seed: int):
        self.region = region_id
        self.t0 = t0
        self.window_h = window_h
        self.rng = random.Random(seed)
        self.rows: dict[str, list[dict]] = {table: [] for table in TABLE_ORDER}
        self.rows["source"].append(
            {"source_id": SOURCE_ID, "kind": "synthetic", "description": "scenario preset generator"}
        )
        self._mmsi_used: set[int] = set()
        self._sar_seq = 0
        self._link_seq = 0
        region = next(r for r in load_regions() if r.region_id == region_id)
        self.bbox = region.bbox
        try:
            coast = json.loads(config_path("coast.json").read_text())
        except OSError:
            coast = {}
        self._land = [ring for c in coast.get(region_id, []) for ring in c["rings"]]

    def at(self, hours: float) -> datetime:
        return self.t0 + timedelta(hours=hours)

    def _on_land(self, lon: float, lat: float) -> bool:
        return any(_pip(lon, lat, ring) for ring in self._land)

    def sea_pos(self, lon: float, lat: float, spread: float = 0.5) -> list[float]:
        lo0, la0, lo1, la1 = self.bbox
        for _ in range(30):
            clon = lon + self.rng.uniform(-spread, spread)
            clat = lat + self.rng.uniform(-spread, spread)
            if lo0 < clon < lo1 and la0 < clat < la1 and not self._on_land(clon, clat):
                return [round(clon, 4), round(clat, 4)]
        return [lon, lat]

    def _mmsi(self) -> int:
        while True:
            value = self.rng.randint(200000000, 799999999)
            if value not in self._mmsi_used:
                self._mmsi_used.add(value)
                return value

    def vessel(
        self,
        vessel_id: str,
        name: str,
        vessel_type: str,
        *,
        mmsi: int | None = None,
        imo: int | None = None,
        length_m: float | None = None,
        owner: str | None = None,
        start: list[float] | None = None,
        waypoints: list[list[float]] | None = None,
        n: int = 24,
        gap: tuple[float, float] | None = None,
        base_sog: float = 8.0,
        sar_in_gap: int = 0,
    ) -> str:
        if mmsi is None and start is not None:
            mmsi = self._mmsi()
        elif mmsi is not None:
            self._mmsi_used.add(mmsi)
        self.rows["vessel"].append(
            {
                "vessel_id": vessel_id,
                "mmsi": mmsi,
                "imo": imo,
                "name": name,
                "vessel_type": vessel_type,
                "length_m": length_m or self.rng.randint(18, 55),
                "owner": owner,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        if start is None:
            return vessel_id
        segs = [start] + (waypoints or [start])
        points = []
        for k in range(n):
            f = k / (n - 1)
            pos = f * (len(segs) - 1)
            i = min(int(pos), len(segs) - 2)
            lf = pos - i
            lon = segs[i][0] + (segs[i + 1][0] - segs[i][0]) * lf + self.rng.uniform(-0.01, 0.01)
            lat = segs[i][1] + (segs[i + 1][1] - segs[i][1]) * lf + self.rng.uniform(-0.01, 0.01)
            h = self.window_h * f
            if gap and gap[0] <= h <= gap[1]:
                continue
            points.append((h, lon, lat))
        for h, lon, lat in points:
            self.rows["ais_position"].append(
                {
                    "mmsi": mmsi,
                    "ts": self.at(h),
                    "vessel_id": vessel_id,
                    "geom": _point(lon, lat),
                    "sog": round(max(0.0, base_sog + self.rng.uniform(-2, 2)), 1),
                    "cog": round(self.rng.uniform(0, 360), 1),
                    "region_id": self.region,
                    "source_id": SOURCE_ID,
                    "collector": COLLECTOR,
                }
            )
        if gap and sar_in_gap:
            hc = (gap[0] + gap[1]) / 2
            pos = hc / self.window_h * (len(segs) - 1)
            i = min(int(pos), len(segs) - 2)
            lf = pos - i
            mlon = segs[i][0] + (segs[i + 1][0] - segs[i][0]) * lf
            mlat = segs[i][1] + (segs[i + 1][1] - segs[i][1]) * lf
            for _ in range(sar_in_gap):
                self.sar(
                    mlon + self.rng.uniform(-0.08, 0.08),
                    mlat + self.rng.uniform(-0.06, 0.06),
                    self.rng.uniform(gap[0] + 1, gap[1] - 1),
                    confidence=self.rng.uniform(0.72, 0.9),
                    length_est=length_m,
                )
        return vessel_id

    def sar(
        self,
        lon: float,
        lat: float,
        hours: float,
        *,
        matched: str | None = None,
        confidence: float = 0.8,
        length_est: float | None = None,
    ) -> str:
        self._sar_seq += 1
        detection_id = f"sim_sar_{self._sar_seq:04d}"
        self.rows["sar_detection"].append(
            {
                "detection_id": detection_id,
                "ts": self.at(hours),
                "geom": _point(lon, lat),
                "length_est_m": length_est or self.rng.randint(20, 240),
                "confidence": round(confidence, 2),
                "sensor": self.rng.choice(["Sentinel-1", "ICEYE", "Capella", "KOMPSAT-6"]),
                "matched_vessel_id": matched,
                "region_id": self.region,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        return detection_id

    def osint(
        self,
        item_id: str,
        hours: float,
        kind: str,
        text: str,
        *,
        lang: str = "ko",
        source_module: str = "sim.osint",
        sentiment: float = 0.0,
        weight: float = 0.5,
    ) -> str:
        self.rows["osint_item"].append(
            {
                "item_id": item_id,
                "ts": self.at(hours),
                "region_id": self.region,
                "kind": kind,
                "lang": lang,
                "source_module": source_module,
                "text": text,
                "sentiment": sentiment,
                "weight": weight,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        return item_id

    def routine_osint(self, count: int) -> None:
        pool = [
            "정기 어업지도선 순찰 보고",
            "기상 악화 예보(시정 2km 이하)",
            "상용 위성 재방문 스케줄 갱신",
            "AIS 기지국 커버리지 점검 완료",
            "해상 교통량 정상 범위",
            "항만 하역 실적 평이",
        ]
        for i in range(count):
            self.osint(
                f"sim_obg_{i}",
                self.rng.uniform(0, self.window_h),
                "routine",
                self.rng.choice(pool),
                weight=0.1,
            )

    def zone(self, zone_id: str, name: str, kind: str, geom: str) -> str:
        self.rows["zone"].append(
            {
                "zone_id": zone_id,
                "name": name,
                "kind": kind,
                "region_id": self.region,
                "geom": geom,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        return zone_id

    def facility(self, facility_id: str, name: str, kind: str, lon: float, lat: float, country: str) -> str:
        self.rows["facility"].append(
            {
                "facility_id": facility_id,
                "name": name,
                "kind": kind,
                "geom": _point(lon, lat),
                "country": country,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        return facility_id

    def event(self, event_id: str, name: str, event_type: str, hours: float, lon: float, lat: float, description: str) -> str:
        self.rows["event"].append(
            {
                "event_id": event_id,
                "name": name,
                "event_type": event_type,
                "event_date": self.at(hours).date(),
                "region_id": self.region,
                "geom": _point(lon, lat),
                "description": description,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        return event_id

    def alert(
        self,
        alert_id: str,
        alert_type: str,
        level: str,
        score: float,
        title_ko: str,
        title_en: str,
        *,
        vessel_id: str | None = None,
        zone_id: str | None = None,
        hours: float = 40,
        why: list[str] | None = None,
        evidence: list[tuple[str, float, str, str, str]] = (),
        timeline: list[tuple[str, float, str]] = (),
    ) -> str:
        self.rows["alert"].append(
            {
                "alert_id": alert_id,
                "alert_type": alert_type,
                "level": level,
                "vessel_id": vessel_id,
                "zone_id": zone_id,
                "region_id": self.region,
                "generated_at": self.at(hours),
                "method_version": METHOD,
                "score": score,
                "title_ko": title_ko,
                "title_en": title_en,
                "why": why or [],
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )
        for term_name, points, src_table, src_id, detail in evidence:
            self.rows["alert_evidence"].append(
                {
                    "alert_id": alert_id,
                    "term_name": term_name,
                    "points": points,
                    "src_table": src_table,
                    "src_id": src_id,
                    "detail": detail,
                    "method_version": METHOD,
                }
            )
        for step_no, (phase, step_hours, description) in enumerate(timeline, start=1):
            self.rows["alert_timeline_step"].append(
                {
                    "alert_id": alert_id,
                    "step_no": step_no,
                    "phase": phase,
                    "ts": self.at(step_hours),
                    "description": description,
                }
            )
        return alert_id

    def link(
        self,
        src_type: str,
        src_id: str,
        dst_type: str,
        dst_id: str,
        rel_type: str,
        *,
        confidence: float = 0.8,
        hypothesis: bool = False,
    ) -> None:
        self._link_seq += 1
        self.rows["entity_link"].append(
            {
                "link_id": f"sim_link_{self._link_seq:03d}",
                "src_type": src_type,
                "src_id": src_id,
                "dst_type": dst_type,
                "dst_id": dst_id,
                "rel_type": rel_type,
                "confidence": confidence,
                "hypothesis": hypothesis,
                "method_version": METHOD,
                "source_id": SOURCE_ID,
                "collector": COLLECTOR,
            }
        )

    def background_fleet(self, prefix: str, count: int, anchor: list[float], spread: float, *, vessel_type: str = "fishing", names: list[str] = (), n: int = 8, base_sog: float = 4.0, length: tuple[int, int] = (18, 45), owner: str = "") -> None:
        for i in range(count):
            pos = self.sea_pos(anchor[0], anchor[1], spread)
            self.vessel(
                f"sim_{prefix}{i}",
                f"{self.rng.choice(names or ['vessel'])} {self.rng.randint(1, 9999)}",
                vessel_type,
                length_m=self.rng.randint(*length),
                owner=owner,
                start=pos,
                waypoints=[self.sea_pos(pos[0], pos[1], spread * 0.2)],
                n=n,
                base_sog=base_sog,
            )


CN_FISH = ["Lu Rong Yu", "Liao Dan Yu", "Su Yan Yu", "Zhe Ling Yu", "Min Shi Yu", "Ji Dan Yu"]
KR_FISH = ["대성호", "해성호", "동양호", "금양호", "제성호", "한별호", "광성호", "태양호"]
CARGO = ["Ocean Pride", "Silver Star", "Golden Wave", "Blue Horizon", "Eastern Glory", "Pacific Trust"]


def _west_sea_infra(b: _Builder) -> None:
    b.zone("sim_c_tpe", "TPE (Trans-Pacific Express)", "cable", _linestring([[126.5, 37.2], [125.4, 36.3], [125.3, 35.2], [126.2, 34.6]]))
    b.zone("sim_c_kj", "Korea-China cable segment", "cable", _linestring([[126.5, 37.3], [124.8, 36.6], [124.1, 36.3]]))
    b.zone("sim_nll", "NLL(북방한계선)", "geofence_line", _linestring([[124.6, 37.75], [125.2, 37.68], [125.7, 37.63], [126.0, 37.56]]))
    b.zone("sim_special_zone", "NLL 특정금지구역(꽃게철)", "geofence_poly", _polygon([[124.5, 37.55], [125.9, 37.5], [125.9, 37.85], [124.5, 37.9]]))
    b.zone("sim_pmz", "한중 잠정조치수역(PMZ, 재구성)", "geofence_poly", _polygon([[124.0, 34.6], [124.9, 34.6], [124.9, 35.8], [124.0, 35.8]]))
    b.facility("sim_p_incheon", "인천항", "port", 126.60, 37.45, "KR")
    b.facility("sim_p_nampo", "남포항", "port", 125.40, 38.55, "KP")
    b.facility("sim_p_pyeongtaek", "평택항", "port", 126.55, 36.96, "KR")
    b.facility("sim_s_seolan1", "선란(深藍) 1호", "platform", 124.35, 35.30, "CN")
    b.facility("sim_s_seolan2", "선란(深藍) 2호", "platform", 124.55, 35.50, "CN")
    b.facility("sim_s_platform", "관리평대(管理平臺)", "platform", 124.45, 35.40, "CN")


def west_sea_cable(seed: int = 20260624) -> _Builder:
    b = _Builder("west_sea", datetime(2026, 6, 24, tzinfo=timezone.utc), 72, seed)
    _west_sea_infra(b)

    b.vessel("sim_v_shunxin39", "순싱39호 (Shunxin-39)", "cargo", mmsi=413000039, length_m=125,
             owner="Jie Yang Trading (홍콩, 中 Guo Wenjie)",
             start=[124.2, 36.8], waypoints=[[125.2, 36.2], [125.4, 35.4], [126.0, 34.8], [126.5, 34.6]],
             n=96, gap=(20, 34), base_sog=11.0, sar_in_gap=3)
    b.vessel("sim_v_deoksong", "덕성호 (Deoksong)", "cargo", mmsi=445120071, imo=8660071, length_m=95,
             owner="북한 국적선",
             start=[124.4, 38.15], waypoints=[[124.1, 37.8], [124.3, 37.5]],
             n=96, gap=(28, 44), base_sog=11.0, sar_in_gap=2)
    b.vessel("sim_v_deyi", "DE YI (무국적)", "cargo", mmsi=0, length_m=88,
             owner="HK Yilin Shipping (실소유 불명)",
             start=[124.2, 37.2], waypoints=[[124.2, 37.4], [124.5, 37.5]],
             n=96, gap=(26, 46), base_sog=11.0, sar_in_gap=2)
    b.vessel("sim_v_huixin", "후이신호 (Hui Xin)", "tanker", mmsi=445200188, imo=9110188, length_m=110,
             owner="제재 대상 유조선",
             start=[124.2, 34.9], waypoints=[[124.7, 35.2], [125.1, 35.6]],
             n=96, gap=(30, 50), base_sog=11.0, sar_in_gap=2)
    b.vessel("sim_v_chonmasan", "천마산호 (Chonma San)", "tanker", mmsi=445300565, imo=8916565, length_m=100,
             owner="유엔 1718 제재 등재 (2018-03)",
             start=[125.6, 36.4], waypoints=[[125.0, 37.0], [124.6, 37.5]],
             n=96, base_sog=11.0)

    b.background_fleet("cn", 90, [124.7, 37.6], 0.55, names=CN_FISH, owner="중국 어선(선단)", length=(20, 45))
    b.background_fleet("kr", 50, [125.8, 36.6], 0.5, names=KR_FISH, owner="한국 어선(V-Pass)", length=(8, 29), n=6)
    b.background_fleet("cargo", 25, [125.3, 35.8], 0.9, vessel_type="cargo", names=CARGO, owner="상용 해운", length=(120, 260), n=10, base_sog=13.0)
    b.background_fleet("rok", 6, [125.6, 37.3], 0.4, vessel_type="patrol", names=["ROK Patrol"], owner="대한민국 해경/해군", length=(50, 120), n=12, base_sog=15.0)

    sar_deyi = b.sar(124.32, 37.46, 36, confidence=0.85, length_est=90)

    b.osint("sim_o1", 2, "port_logistics", "산둥 스다오항 유류·보급 반출량 평년 대비 급증 — 대형 선단 출항 정황", source_module="sat.logistics", sentiment=-0.3, weight=0.7)
    b.osint("sim_o2", 10, "news", "꽃게철 앞두고 NLL 특정금지구역 중국어선 일평균 98척 — 최근 5년 최다", source_module="news.kcg", sentiment=-0.4, weight=0.6)
    b.osint("sim_o3", 20, "registry", "Vessel 'DE YI' shows registry gap; last known operator HK Yilin Shipping — flag lapsed", lang="en", source_module="registry.gisis", sentiment=-0.7, weight=0.85)
    b.osint("sim_o4", 26, "news", "북·중·러 해상 협력 강화로 제재회피 구분이 어려운 회색지대 물류통로 형성 우려", source_module="news.rfa", sentiment=-0.5, weight=0.6)
    b.osint("sim_o5", 40, "port_logistics", "순싱39호 부산항 입항 신고 접수 — 직전 항적에 케이블 구간 저속 배회 포함", source_module="port.entry", sentiment=-0.8, weight=0.9)
    b.osint("sim_o6", 14, "sat_change", "Satellite change-detection: new activity around Shenlan-2 platform (small craft alongside)", lang="en", source_module="sat.change", sentiment=-0.6, weight=0.8)
    b.routine_osint(15)

    b.event("sim_e_tpe_cut", "TPE 케이블 절단 의혹", "cable_damage", 27, 125.35, 35.3,
            "순싱39호 AIS 공백 구간에서 TPE 케이블 손상 감지 — 앵커드래그 의혹")

    b.alert("sim_a_shunxin39", "critical_infrastructure", "CRITICAL", 94,
            "순싱39호 — 케이블 근접 다크선박 + 신원세탁", "Shunxin-39 — dark vessel near cable + identity laundering",
            vessel_id="sim_v_shunxin39", zone_id="sim_c_tpe", hours=40,
            why=["AIS 20-34h 두절 구간이 TPE 케이블 구간과 겹침",
                 "동일 선체가 Cameroon-Tanzania 이중선적 (Xing Shun-39 별칭)",
                 "부산항 입항 신고 — 직전 항적 저속 배회(loitering)",
                 "SAR 미매칭 탐지 3건이 공백 구간에 존재"],
            evidence=[("AIS_GAP", 30, "ais_position", "sim_v_shunxin39", "20-34h AIS 공백 (14시간)"),
                      ("CABLE_PROXIMITY", 25, "zone", "sim_c_tpe", "공백 구간이 TPE 경로와 교차"),
                      ("SAR_MISMATCH", 22, "sar_detection", "sim_sar_0001", "공백 구간 내 미매칭 SAR 탐지"),
                      ("IDENTITY_TAMPERING", 17, "vessel", "sim_v_shunxin39", "이중선적·별칭 (Xing Shun-39)")],
            timeline=[("전조", 8, "SNS·물류 이상 없음, 정상 항적"),
                      ("기동", 20, "AIS OFF (공백 진입)"),
                      ("접촉", 27, "TPE 케이블 구간 저속 배회 + SAR 미매칭 탐지"),
                      ("재출현", 34, "AIS ON, 부산 침로"),
                      ("전파", 40, "부산 입항 신고 → KT 공동소유 회선 위험")])
    b.alert("sim_a_deoksong", "sanctions_evasion", "CRITICAL", 90,
            "덕성호 ⇄ DE YI — 제재회피 STS 환적(석탄)", "Deoksong x DE YI — sanctions STS transfer",
            vessel_id="sim_v_deoksong", hours=46,
            why=["덕성호·DE YI 모두 동일 시간창에 AIS OFF 후 근접 랑데부",
                 "DE YI 무국적(등록 공백) — 신분세탁 위장선",
                 "출발항 남포(북한 최대 석탄 반출항)",
                 "SAR 미매칭 탐지가 랑데부 좌표와 일치"],
            evidence=[("AIS_GAP", 28, "ais_position", "sim_v_deoksong", "28-44h 양선 동시 AIS 공백"),
                      ("DARK_STS_RENDEZVOUS", 30, "sar_detection", sar_deyi, "랑데부 좌표 SAR 탐지"),
                      ("STATELESS_PARTNER", 20, "vessel", "sim_v_deyi", "무국적 위장선"),
                      ("OSINT", 12, "osint_item", "sim_o3", "DE YI 등록 공백 보고")],
            timeline=[("전조", 18, "남포 출항, 정상 신고"),
                      ("기동", 28, "양선 AIS OFF"),
                      ("접촉", 36, "공해상 STS 랑데부(석탄 4,500t)"),
                      ("재출현", 46, "AIS ON, 산개")])
    b.alert("sim_a_huixin", "sanctions_evasion", "HIGH", 82,
            "후이신호 — AIS-off 유류 STS 의혹", "Hui Xin — dark oil STS suspicion",
            vessel_id="sim_v_huixin", hours=50,
            why=["30-50h AIS 공백 후 재출현", "제재 대상 유조선", "MSMT 확인 사례형 수법"],
            evidence=[("AIS_GAP", 32, "ais_position", "sim_v_huixin", "30-50h AIS 공백 (20시간)"),
                      ("SANCTIONED_MATCH", 28, "vessel", "sim_v_huixin", "제재 대상 유조선"),
                      ("OSINT", 10, "osint_item", "sim_o4", "회색지대 물류통로 보고")],
            timeline=[("기동", 30, "AIS OFF"), ("접촉", 40, "신원미상 유조선과 STS 추정"), ("재출현", 50, "AIS ON")])

    for vid, name in [("sim_v_shunxin39", "순싱39호"), ("sim_v_deoksong", "덕성호"), ("sim_v_deyi", "DE YI"), ("sim_v_huixin", "후이신호"), ("sim_v_chonmasan", "천마산호")]:
        b.link("vessel", vid, "zone", "sim_c_tpe" if vid == "sim_v_shunxin39" else "sim_nll", "operates_near", confidence=0.6, hypothesis=True)
    b.link("vessel", "sim_v_deoksong", "vessel", "sim_v_deyi", "sts_rendezvous", confidence=0.9)
    b.link("vessel", "sim_v_shunxin39", "zone", "sim_c_tpe", "anchor_proximity", confidence=0.85)
    b.link("vessel", "sim_v_shunxin39", "facility", "sim_p_incheon", "inbound", confidence=0.7)
    return b


def baltic_shadow(seed: int = 20241225) -> _Builder:
    b = _Builder("baltic", datetime(2024, 12, 24, tzinfo=timezone.utc), 72, seed)
    b.zone("sim_c_estlink2", "Estlink 2 (전력)", "cable", _linestring([[26.9, 59.95], [26.6, 59.8], [26.35, 59.55]]))
    b.zone("sim_c_clion1", "C-Lion1", "cable", _linestring([[24.95, 59.95], [22.5, 59.2], [20.0, 58.4], [18.6, 58.0]]))
    b.zone("sim_c_bcs", "BCS East-West Interlink", "cable", _linestring([[18.4, 57.8], [20.6, 56.9], [21.0, 55.7]]))
    b.facility("sim_p_ustluga", "우스트루가항 (Ust-Luga)", "port", 28.30, 59.68, "RU")
    b.facility("sim_p_helsinki", "헬싱키항", "port", 24.95, 59.95, "FI")
    b.facility("sim_p_tallinn", "탈린항", "port", 24.76, 59.44, "EE")

    b.vessel("sim_v_eagles", "이글 S (Eagle S)", "tanker", mmsi=518998610, imo=9329760, length_m=228,
             owner="러 그림자함대 추정 (첩보장비 적재 보도)",
             start=[27.9, 59.78], waypoints=[[27.0, 59.82], [26.55, 59.86], [26.1, 59.72]],
             n=96, gap=(18, 30), base_sog=11.0, sar_in_gap=3)
    b.vessel("sim_v_yipeng3", "이펑3호 (Yi Peng 3)", "cargo", mmsi=412100003, imo=9224984, length_m=225,
             owner="중국 선적 벌크선",
             start=[27.3, 59.9], waypoints=[[24.9, 59.85], [22.5, 59.2], [20.0, 58.5]],
             n=96, gap=(22, 40), base_sog=11.0, sar_in_gap=3)
    b.vessel("sim_v_vezhen", "베젠호 (Vezhen)", "cargo", mmsi=229900123, imo=9420123, length_m=200,
             owner="몰타 선적 벌크선",
             start=[19.5, 58.0], waypoints=[[19.0, 57.4], [18.6, 57.0]],
             n=96, base_sog=11.0)
    suspect_flags = ["Cook Islands", "Palau", "Tanzania", "Cameroon", "Guyana"]
    for i in range(6):
        b.vessel(f"sim_v_shadow{i}", f"Dark Tanker {i + 1}", "tanker",
                 length_m=b.rng.randint(180, 250),
                 owner=f"러 그림자함대 추정 ({b.rng.choice(suspect_flags)} 편의치적)",
                 start=[27.5 + b.rng.uniform(-0.5, 0.4), 59.7 + b.rng.uniform(-0.3, 0.2)],
                 waypoints=[[25.0, 59.4], [22.0, 59.0]],
                 n=96, gap=(b.rng.randint(16, 26), b.rng.randint(34, 48)), base_sog=11.0, sar_in_gap=2)
    b.background_fleet("balt", 60, [23.0, 59.0], 1.5, vessel_type="cargo", names=CARGO, owner="상용 해운", length=(90, 300), n=10, base_sog=14.0)

    b.osint("sim_o1", 30, "ais_gap", "Russia-linked tanker AIS blackout rate 6x EU average; notable gaps up 2x YoY", lang="en", source_module="windward.ftm", sentiment=-0.6, weight=0.7)
    b.osint("sim_o2", 34, "news", "NATO stands up 'Baltic Sentry' after 11 cables damaged in 15 months", lang="en", source_module="news.defense", sentiment=-0.4, weight=0.65)
    b.osint("sim_o3", 29, "news", "Estlink2 전력 급감 감지 — 핀란드-에스토니아 계통 1016→358MW", source_module="grid.fingrid", sentiment=-0.8, weight=0.9)
    b.routine_osint(12)

    b.event("sim_e_estlink2", "Estlink 2 절단", "cable_damage", 28, 26.5, 59.8,
            "Eagle S 앵커드래그로 Estlink 2 및 통신 케이블 4개 절단; 전력 1016→358MW")
    b.event("sim_e_clion1", "C-Lion1 절단 의혹", "cable_damage", 30, 22.6, 59.2,
            "Yi Peng 3 닻 내린 채 약 180km 항해 — C-Lion1·BCS 절단 의혹")

    b.alert("sim_a_eagles", "critical_infrastructure", "CRITICAL", 96,
            "Eagle S — 앵커드래그 해저케이블 절단", "Eagle S — anchor-drag cable cut",
            vessel_id="sim_v_eagles", zone_id="sim_c_estlink2", hours=32,
            why=["AIS 18-30h 공백이 Estlink2 경로와 정확히 교차",
                 "저속·비정상 침로(닻 끌림 패턴)",
                 "Cook Islands 편의치적 그림자함대",
                 "공백 구간 SAR 미매칭 탐지"],
            evidence=[("AIS_GAP", 30, "ais_position", "sim_v_eagles", "18-30h AIS 공백"),
                      ("CABLE_PROXIMITY", 28, "zone", "sim_c_estlink2", "공백 구간이 Estlink2와 교차"),
                      ("ANCHOR_DRAG", 22, "ais_position", "sim_v_eagles", "저속·닻 끌림 항적 패턴"),
                      ("OSINT", 16, "osint_item", "sim_o3", "전력 급감 계통 데이터")],
            timeline=[("전조", 12, "우스트루가 출항"),
                      ("기동", 18, "AIS OFF, 케이블 접근"),
                      ("접촉", 24, "Estlink2 교차 + 저속 앵커드래그"),
                      ("피해", 28, "전력 1016→358MW 급감"),
                      ("대응", 32, "핀란드 특수부대 나포")])
    b.alert("sim_a_yipeng3", "critical_infrastructure", "HIGH", 88,
            "Yi Peng 3 — 케이블 2개 근접 앵커드래그 의혹", "Yi Peng 3 — dual cable anchor-drag",
            vessel_id="sim_v_yipeng3", zone_id="sim_c_clion1", hours=40,
            why=["공백 구간이 C-Lion1·BCS 교차점과 겹침",
                 "닻 내린 채 약 180km 항해 패턴",
                 "기국 협조 없이는 수사 불가(관할권 공백)"],
            evidence=[("AIS_GAP", 30, "ais_position", "sim_v_yipeng3", "22-40h AIS 공백"),
                      ("CABLE_PROXIMITY", 30, "zone", "sim_c_clion1", "C-Lion1·BCS 근접"),
                      ("OSINT", 14, "osint_item", "sim_o2", "발트해 케이블 피해 11건 보고")],
            timeline=[("기동", 22, "AIS OFF"), ("접촉", 30, "C-Lion1·BCS 근접"), ("재출현", 40, "카테가트서 억류")])
    b.alert("sim_a_shadow", "sanctions_evasion", "MED", 69,
            "그림자함대 유조선 — AIS 장기 두절", "Shadow-fleet tanker — prolonged AIS blackout",
            vessel_id="sim_v_shadow0", hours=42,
            why=["AIS 두절 유럽선 대비 6배", "단기 다중 기국세탁", "편의치적·불투명 소유"],
            evidence=[("AIS_GAP", 30, "ais_position", "sim_v_shadow0", "장기 AIS 공백"),
                      ("FLAG_HOPPING", 22, "vessel", "sim_v_shadow0", "다중 기국세탁"),
                      ("OSINT", 17, "osint_item", "sim_o1", "AIS 두절률 6배 보고")],
            timeline=[("기동", 20, "AIS OFF"), ("재출현", 42, "AIS ON")])

    b.link("vessel", "sim_v_eagles", "zone", "sim_c_estlink2", "cable_cut", confidence=0.95)
    b.link("vessel", "sim_v_yipeng3", "zone", "sim_c_clion1", "anchor_proximity", confidence=0.8, hypothesis=True)
    b.link("vessel", "sim_v_eagles", "facility", "sim_p_ustluga", "departed_from", confidence=0.9)
    for i in range(6):
        b.link("vessel", f"sim_v_shadow{i}", "facility", "sim_p_ustluga", "shadow_fleet_member", confidence=0.6, hypothesis=True)
    return b


def nll_intrusion(seed: int = 20260315) -> _Builder:
    b = _Builder("west_sea", datetime(2026, 3, 15, tzinfo=timezone.utc), 72, seed)
    _west_sea_infra(b)

    b.vessel("sim_v_intr1", "미상 어선 (NLL 침범)", "fishing", length_m=42, owner="해상민병대 의심",
             start=[125.35, 38.35], waypoints=[[125.15, 38.02], [125.0, 37.72], [124.85, 37.6]],
             n=84, base_sog=8.0)
    b.vessel("sim_v_intr2", "접근 미상선 (PMZ 구조물)", "cargo", length_m=76, owner="구역 침범 의심",
             start=[125.4, 36.6], waypoints=[[124.9, 36.0], [124.6, 35.6], [124.5, 35.4]],
             n=84, base_sog=8.0)
    b.vessel("sim_v_nkboat", "북한 소형목선(미상)", "unknown", mmsi=None, length_m=7, owner="미상 (비협조 표적)")
    for i in range(9):
        pos = b.sea_pos(124.7, 37.6, 0.45)
        gap = (b.rng.randint(24, 36), b.rng.randint(40, 52)) if b.rng.random() < 0.5 else None
        b.vessel(f"sim_v_mil{i}", f"{b.rng.choice(CN_FISH)} {b.rng.randint(1, 9999)}", "fishing",
                 length_m=b.rng.randint(35, 55), owner="해상민병대 의심",
                 start=pos, waypoints=[b.sea_pos(pos[0], pos[1], 0.12)],
                 n=84, gap=gap, base_sog=6.0, sar_in_gap=2 if gap else 0)
    b.background_fleet("cn", 90, [124.7, 37.6], 0.55, names=CN_FISH, owner="중국 어선(선단)", length=(20, 45))
    b.background_fleet("kr", 45, [125.8, 36.8], 0.5, names=KR_FISH, owner="한국 어선(V-Pass)", length=(8, 29), n=6)
    b.background_fleet("rok", 8, [125.5, 37.4], 0.4, vessel_type="patrol", names=["ROK Patrol"], owner="대한민국 해경/해군", length=(50, 120), n=12, base_sog=15.0)

    nk_sar_ids = [
        b.sar(124.8 + b.rng.uniform(-0.3, 0.5), 37.6 + b.rng.uniform(-0.15, 0.15),
              b.rng.randint(8, 40), confidence=b.rng.uniform(0.45, 0.62), length_est=b.rng.randint(6, 10))
        for _ in range(4)
    ]

    b.osint("sim_o1", 6, "social", "어촌 커뮤니티서 '단기 선원 대규모 모집' 게시물 급증 (연평 인근 조업 언급)", lang="zh", source_module="sns.mining", sentiment=-0.5, weight=0.75)
    b.osint("sim_o2", 10, "news", "꽃게철 앞두고 NLL 특정금지구역 중국어선 일평균 98척 — 최근 5년 최다", source_module="news.kcg", sentiment=-0.4, weight=0.6)
    b.osint("sim_o3", 14, "sat_change", "선란2 인근 소형정 활동 위성 변화탐지", source_module="sat.change", sentiment=-0.6, weight=0.8)
    b.osint("sim_o4", 46, "social", "연평도 어민 '레이더에 안 잡히는 소형보트 목격' 다수 제보", source_module="sns.local", sentiment=-0.5, weight=0.55)
    b.routine_osint(15)

    b.event("sim_e_nll_cross", "NLL 월선", "intrusion", 32, 125.0, 37.7, "미상 어선 NLL 이북에서 특정금지구역으로 남하 침범")

    b.alert("sim_a_intr1", "zone_intrusion", "CRITICAL", 91,
            "미상 어선 — NLL 특정금지구역 침범", "Unknown fishing vessel — NLL restricted-zone intrusion",
            vessel_id="sim_v_intr1", zone_id="sim_special_zone", hours=33,
            why=["NLL 이북 발진 후 특정금지구역 남하 진입", "선명·호출부호 불일치", "회피 기동 패턴"],
            evidence=[("ZONE_INTRUSION", 40, "zone", "sim_special_zone", "특정금지구역 진입 (H+32)"),
                      ("NLL_CROSSING", 30, "zone", "sim_nll", "NLL 월선 항적"),
                      ("IDENTITY_MISMATCH", 21, "vessel", "sim_v_intr1", "선명·호출부호 불일치")],
            timeline=[("전조", 20, "NLL 이북 대기"), ("기동", 28, "남하 개시"), ("침범", 32, "특정금지구역 진입"), ("대응", 34, "경비함 유도·차단 개시")])
    b.alert("sim_a_intr2", "zone_intrusion", "HIGH", 84,
            "접근 미상선 — PMZ 구조물 방향 진입", "Unknown vessel — approaching PMZ structures",
            vessel_id="sim_v_intr2", zone_id="sim_pmz", hours=36,
            why=["선란 구조물 방향 PMZ 진입 접근", "무국적 의심", "AIS 정보 불완전"],
            evidence=[("ZONE_INTRUSION", 35, "zone", "sim_pmz", "PMZ 진입 (H+35)"),
                      ("STRUCTURE_APPROACH", 30, "facility", "sim_s_seolan2", "선란2 방향 접근 침로"),
                      ("OSINT", 19, "osint_item", "sim_o3", "선란2 인근 소형정 활동 변화탐지")],
            timeline=[("기동", 24, "PMZ 방향 변침"), ("접근", 35, "PMZ 진입, 선란2 접근"), ("대응", 38, "관심표적 지정")])
    b.alert("sim_a_militia", "gray_zone", "HIGH", 78,
            "해상민병대 의심 군집 — 회색지대 전조", "Suspected militia mustering — gray-zone precursor",
            vessel_id="sim_v_mil0", hours=30,
            why=["정상 조업 대비 이상 군집·동조 기동", "선원 대규모 모집 SNS 급증(OSINT)", "선란2 인근 소형정 활동 위성 변화탐지"],
            evidence=[("ABNORMAL_CLUSTER", 30, "ais_position", "sim_v_mil0", "이상 군집·동조 기동"),
                      ("OSINT_RECRUITMENT", 26, "osint_item", "sim_o1", "선원 모집 게시물 급증"),
                      ("SAT_CHANGE", 22, "osint_item", "sim_o3", "선란2 인근 위성 변화탐지")],
            timeline=[("전조", 6, "SNS 선원 모집 급증"), ("징후", 14, "선란2 인근 소형정 포착"), ("집결", 30, "이상 군집 형성")])
    b.alert("sim_a_nkboat", "infiltration", "HIGH", 72,
            "북한 소형목선 — 비협조·저RCS 표적(SAR 단독)", "NK wooden boat — non-cooperative low-RCS (SAR-only)",
            vessel_id="sim_v_nkboat", hours=31,
            why=["AIS/V-Pass 신호 전무", "희미한 SAR 탐지만 존재(신뢰도 0.45~0.62)", "중국어선 클러터에 은닉"],
            evidence=[("NO_AIS", 30, "vessel", "sim_v_nkboat", "AIS/V-Pass 미탑재"),
                      ("SAR_ONLY", 28, "sar_detection", nk_sar_ids[0], "클러터 속 희미한 SAR 다중 탐지"),
                      ("OSINT", 14, "osint_item", "sim_o4", "어민 소형보트 목격 제보")],
            timeline=[("징후", 8, "어민 '레이더 미탐지 소형보트' 제보"), ("탐지", 30, "클러터 속 희미한 SAR 다중 탐지")])

    b.link("vessel", "sim_v_intr1", "zone", "sim_nll", "crossed", confidence=0.9)
    b.link("vessel", "sim_v_intr2", "facility", "sim_s_seolan2", "approaching", confidence=0.8, hypothesis=True)
    for i in range(4):
        b.link("vessel", f"sim_v_mil{i}", "facility", "sim_s_seolan2", "mustering_near", confidence=0.6, hypothesis=True)
    return b


PRESETS = {
    "west_sea_cable": (
        west_sea_cable,
        "서해 해저케이블 위협 (순싱39·STS 환적)",
        "West Sea cable threat (Shunxin-39, dark STS)",
        "2025-01 순싱39호 케이블 절단 의혹 + 덕성호/DE YI 제재회피 STS 재구성 (72h)",
    ),
    "baltic_shadow": (
        baltic_shadow,
        "발트해 그림자함대 (Eagle S·Yi Peng 3)",
        "Baltic shadow fleet (Eagle S, Yi Peng 3)",
        "2024-12 Estlink2 절단 및 C-Lion1 앵커드래그 사건 재구성 (72h)",
    ),
    "nll_intrusion": (
        nll_intrusion,
        "NLL 침범·회색지대 (민병대·소형목선)",
        "NLL intrusion / gray zone (militia, wooden boat)",
        "NLL 월선·PMZ 구조물 접근·해상민병 군집·저RCS 침투 재구성 (72h)",
    ),
}


def generate(conn, scenario_id: str, preset_name: str, seed: int | None = None) -> dict:
    builder_fn = PRESETS[preset_name][0]
    schema = pg.scenario_schema(scenario_id)
    conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
    conn.execute(
        sql.SQL("TRUNCATE {} CASCADE").format(
            sql.SQL(", ").join(sql.Identifier(schema, table) for table in TABLE_ORDER)
        )
    )
    builder = builder_fn(seed) if seed is not None else builder_fn()
    counts = {}
    for table in TABLE_ORDER:
        rows = builder.rows[table]
        if rows:
            counts[table] = pg.upsert(conn, table, rows, conflict=CONFLICTS[table])
    conn.execute("SET search_path TO public")
    return counts
