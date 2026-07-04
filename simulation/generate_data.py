#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEASENTINEL — Maritime Domain Awareness demo data generator.

Generates a large, realistic dataset grounded in REAL 2024-2026 incidents
(Shunxin-39/순싱39, Eagle S, 덕성호/Deoksong, Hui Xin, 천마산/Chonma San,
Yi Peng 3, 서해 PMZ 선란1/2 구조물, NLL 중국어선 선단) plus hundreds of
normal vessels so the multi-source feeds look production-grade.

Deterministic (seeded) so the demo is reproducible on stage.
Outputs JSON to ../public/data/.
"""
import json, math, random, os, datetime

random.seed(20260624)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "data"))
os.makedirs(OUT, exist_ok=True)

# Scenario window anchored to the presidential Yeonpyeong visit (2026-06-24)
T0 = datetime.datetime(2026, 6, 24, 0, 0, 0, tzinfo=datetime.timezone.utc)
WINDOW_H = 72
def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
def at(h): return iso(T0 + datetime.timedelta(hours=h))

# ---------------------------------------------------------------- regions
REGIONS = {
    "west_sea": {
        "id": "west_sea",
        "name_ko": "서해 / 황해 (NLL·잠정조치수역)",
        "name_en": "Yellow Sea (NLL / PMZ)",
        "bbox": [119.8, 32.2, 129.7, 38.9],   # lon_min, lat_min, lon_max, lat_max (콘텐츠 전체 포함: 칭다오~부산)
        "center": [124.8, 35.5],
        "theatre": "ROK — proving ground",
    },
    "baltic": {
        "id": "baltic",
        "name_ko": "발트해 (해저케이블 사보타주)",
        "name_en": "Baltic Sea (undersea-cable sabotage)",
        "bbox": [18.0, 57.6, 28.5, 60.8],
        "center": [23.2, 59.4],
        "theatre": "NATO — global proof",
    },
}

# coarse land polygons (recognizable, offline, no tiles)
GEO = {
    "west_sea": {
        "land": [
            {"name_ko": "한국(한반도)", "name_en": "Korea", "ring": [
                [126.0,38.6],[126.6,38.2],[126.9,37.7],[126.7,37.4],[126.9,37.0],
                [126.6,36.6],[126.4,36.0],[126.5,35.2],[126.2,34.6],[126.9,34.3],
                [127.2,34.4],[127.2,38.6]]},
            {"name_ko": "중국(산둥)", "name_en": "China (Shandong)", "ring": [
                [122.0,38.6],[122.0,34.8],[121.0,34.8],[121.0,38.6]]},
            {"name_ko": "연평도", "name_en": "Yeonpyeong", "ring": [
                [125.68,37.66],[125.74,37.66],[125.74,37.60],[125.68,37.60]]},
            {"name_ko": "백령도", "name_en": "Baengnyeong", "ring": [
                [124.62,37.98],[124.75,37.98],[124.75,37.90],[124.62,37.90]]},
        ],
    },
    "baltic": {
        "land": [
            {"name_ko": "핀란드", "name_en": "Finland", "ring": [
                [18.0,60.8],[28.5,60.8],[28.5,60.1],[25.0,60.0],[22.0,59.9],[19.5,60.1],[18.0,60.4]]},
            {"name_ko": "에스토니아", "name_en": "Estonia", "ring": [
                [21.8,59.0],[28.5,59.0],[28.5,57.6],[21.8,57.6]]},
            {"name_ko": "스웨덴", "name_en": "Sweden", "ring": [
                [18.0,60.4],[18.6,59.2],[18.2,58.2],[18.0,57.6],[18.0,60.4]]},
        ],
    },
}

# ---------------------------------------------------------------- ports & infra
PORTS = [
    {"id":"p_incheon","name_ko":"인천항","name_en":"Incheon","region":"west_sea","lonlat":[126.60,37.45],"country":"KR"},
    {"id":"p_nampo","name_ko":"남포항","name_en":"Nampo","region":"west_sea","lonlat":[125.40,38.72],"country":"KP","note":"북한 최대 석탄 반출항"},
    {"id":"p_pyeongtaek","name_ko":"평택항","name_en":"Pyeongtaek","region":"west_sea","lonlat":[126.82,36.96],"country":"KR"},
    {"id":"p_qingdao","name_ko":"칭다오항","name_en":"Qingdao","region":"west_sea","lonlat":[120.30,36.07],"country":"CN"},
    {"id":"p_busan","name_ko":"부산항","name_en":"Busan","region":"west_sea","lonlat":[129.03,35.09],"country":"KR","note":"순싱39호 입항 예정지"},
    {"id":"p_ustluga","name_ko":"우스트루가항","name_en":"Ust-Luga","region":"baltic","lonlat":[28.30,59.68],"country":"RU","note":"러 그림자함대 원유 적출항"},
    {"id":"p_helsinki","name_ko":"헬싱키항","name_en":"Helsinki","region":"baltic","lonlat":[24.95,60.15],"country":"FI"},
    {"id":"p_tallinn","name_ko":"탈린항","name_en":"Tallinn","region":"baltic","lonlat":[24.76,59.44],"country":"EE"},
]

# undersea cables (linestrings) + PMZ structures
CABLES = [
    {"id":"c_tpe","name":"TPE (Trans-Pacific Express)","region":"west_sea","owners":["KT(공동소유)","CT","NTT"],
     "path":[[126.6,37.3],[125.6,36.4],[125.6,34.6],[127.0,33.6],[128.6,34.4],[129.0,35.0]],"criticality":"high",
     "note":"국제 통신·금융 트래픽 경유; 순싱39호 절단 의혹 회선과 동일 계열"},
    {"id":"c_kj","name":"Korea–China cable segment","region":"west_sea","owners":["KT","China Telecom"],
     "path":[[126.5,37.3],[124.8,36.6],[122.5,36.2]],"criticality":"high"},
    {"id":"c_estlink2","name":"Estlink 2 (전력)","region":"baltic","owners":["Fingrid","Elering"],
     "path":[[26.9,60.30],[26.6,59.9],[26.35,59.55]],"criticality":"high",
     "note":"2024-12-25 Eagle S 앵커드래그 절단; 1016MW→358MW"},
    {"id":"c_clion1","name":"C-Lion1","region":"baltic","owners":["Cinia"],
     "path":[[24.95,60.05],[22.5,59.2],[20.0,58.4],[18.6,58.0]],"criticality":"high",
     "note":"핀란드–독일 유일 직결 통신선; 2024-11-17 Yi Peng 3 절단 의혹"},
    {"id":"c_bcs","name":"BCS East-West Interlink","region":"baltic","owners":["Telia"],
     "path":[[18.4,57.8],[20.6,56.9],[21.0,55.7]],"criticality":"med"},
]
STRUCTURES = [
    {"id":"s_seolan1","name_ko":"선란(深藍) 1호","name_en":"Shenlan-1","region":"west_sea","lonlat":[123.35,32.9],
     "kind":"aquaculture_platform","installed":"2018","detected":"2020-03","dims":"직경60m·높이35m",
     "note":"설치→식별 약 2년 지연 (원해 PMZ 감시 사각)"},
    {"id":"s_seolan2","name_ko":"선란(深藍) 2호","name_en":"Shenlan-2","region":"west_sea","lonlat":[123.62,33.15],
     "kind":"aquaculture_platform","installed":"2024-04","detected":"2024-05","dims":"직경70m·높이71.5m",
     "note":"2025-08 잠수복 착용 인원 5명 포착 → 군사활용 우려"},
    {"id":"s_platform","name_ko":"관리평대(管理平臺)","name_en":"Management platform","region":"west_sea","lonlat":[123.45,33.02],
     "kind":"fixed_rig","installed":"2022","dims":"100×80×50m, 헬기 이착륙장·시추리그식",
     "note":"해저 고정식 → 사실상 철거 불가"},
]
# 13 buoys (살라미식 순차 설치)
for i in range(13):
    STRUCTURES.append({"id":f"s_buoy{i+1}","name_ko":f"태양광 부표 #{i+1}","name_en":f"Solar buoy #{i+1}",
        "region":"west_sea","lonlat":[123.0+0.25*(i%5)+random.uniform(-0.05,0.05), 32.6+0.28*(i//5)+random.uniform(-0.05,0.05)],
        "kind":"buoy","installed":str(2018+i//3),"dims":"폭3m·높이6m","note":"살라미식 순차 설치 (개별 임계치 미달)"})

# geofences
GEOFENCES = [
    {"id":"nll","name_ko":"NLL(북방한계선)","region":"west_sea","kind":"line",
     "path":[[124.6,37.75],[125.2,37.68],[125.7,37.63],[126.0,37.56]]},
    {"id":"pmz","name_ko":"한중 잠정조치수역(PMZ)","region":"west_sea","kind":"polygon",
     "ring":[[122.6,32.3],[124.2,32.3],[124.2,34.2],[122.6,34.2]]},
    {"id":"special_zone","name_ko":"NLL 특정금지구역(꽃게철)","region":"west_sea","kind":"polygon",
     "ring":[[124.5,37.55],[125.9,37.5],[125.9,37.85],[124.5,37.9]]},
]

# ---------------------------------------------------------------- name pools
KR_FISH = ["대성호","해성호","동양호","금양호","제성호","한별호","광성호","태양호","만선호","성진호",
    "우성호","해동호","제일호","형제호","은성호","대양호","삼호","복성호","영진호","남성호"]
CN_FISH_PY = ["Lu Rong Yu","Liao Dan Yu","Su Yan Yu","Zhe Ling Yu","Min Shi Yu","Ji Dan Yu","Lu Wei Yu","Zhe Pu Yu"]
CARGO_NAMES = ["Ocean Pride","Silver Star","Golden Wave","Blue Horizon","Eastern Glory","Pacific Trust",
    "Star Harmony","Grand Fortune","Nova Trader","Sea Phoenix","Orient Victory","Crystal Voyager"]
FLAGS_NORMAL = ["KR","CN","PA","LR","MH","SG","HK","MT","CY","GR"]
SUSPECT_FLAGS = ["Cook Islands","Palau","Tanzania","Cameroon","Guyana","Sierra Leone","Comoros","Gabon","Togo","unregistered"]

def mmsi(): return str(random.randint(200000000, 799999999))
def imo(): return str(random.randint(7000000, 9899999))

# ---------------------------------------------------------------- vessel factory
vessels = []
tracks = {}
DARKINFO = {}   # vid -> {"gap":(g0,g1), "mid":(lon,lat)}  for aligned SAR placement

def dest_toward(lon, lat, tlon, tlat, frac):
    return [lon + (tlon-lon)*frac, lat + (tlat-lat)*frac]

def make_track(vid, start, waypoints, n, gap=None, jitter=0.01, base_sog=8.0):
    """waypoints: list of [lon,lat]; gap: (i_start,i_end) hours indices with AIS OFF."""
    pts = []
    segs = [start] + waypoints
    for k in range(n):
        f = k/(n-1)
        # piecewise along segs
        pos = f*(len(segs)-1)
        i = min(int(pos), len(segs)-2)
        lf = pos - i
        lon = segs[i][0] + (segs[i+1][0]-segs[i][0])*lf + random.uniform(-jitter,jitter)
        lat = segs[i][1] + (segs[i+1][1]-segs[i][1])*lf + random.uniform(-jitter,jitter)
        h = WINDOW_H * f
        dark = gap and (gap[0] <= h <= gap[1])
        if dark:
            continue  # AIS OFF: no report emitted (that's the whole point)
        sog = max(0.0, base_sog + random.uniform(-2,2))
        cog = random.uniform(0,360)
        pts.append({"t": at(round(h,2)), "lon": round(lon,4), "lat": round(lat,4),
                    "sog": round(sog,1), "cog": round(cog,1)})
    if gap:  # record dead-reckoned midpoint of the AIS-off window for aligned SAR placement
        hc = (gap[0]+gap[1])/2.0; f = hc/WINDOW_H; pos = f*(len(segs)-1)
        i = min(int(pos), len(segs)-2); lf = pos - i
        mlon = segs[i][0] + (segs[i+1][0]-segs[i][0])*lf
        mlat = segs[i][1] + (segs[i+1][1]-segs[i][1])*lf
        DARKINFO[vid] = {"gap": gap, "mid": (mlon, mlat)}
    tracks[vid] = pts
    return pts

def add_vessel(**kw):
    kw.setdefault("flag_history", [kw.get("flag","")])
    kw.setdefault("aliases", [])
    kw.setdefault("length_m", random.randint(18, 55))
    vessels.append(kw)
    return kw

# ---- NAMED REAL THREAT VESSELS (grounded in verified incidents) ----
NAMED = [
 dict(id="v_shunxin39", mmsi="413000039", imo="IMO-DUAL*", name_en="Shunxin-39", name_ko="순싱39호",
    flag="Cameroon", type="cargo", region="west_sea", length_m=125, threat="cable",
    flag_history=["Tanzania","Cameroon"], aliases=["Xing Shun-39","順興39"],
    owner="Jie Yang Trading (홍콩, 中 Guo Wenjie)", note="2025-01 대만 TPE 케이블 앵커드래그 절단 의혹; 부산 입항 예정이었음 (KT 공동소유 회선 포함)",
    start=[123.9,34.4], waypoints=[[124.6,33.4],[125.8,32.6],[127.4,33.1],[128.6,34.4],[129.0,34.95]], gap=(20,34)),
 dict(id="v_deoksong", mmsi="445120071", imo="8660071", name_en="Deoksong", name_ko="덕성호",
    flag="KP", type="cargo", region="west_sea", length_m=95, threat="sts_sanctions",
    flag_history=["KP"], aliases=[], owner="북한 국적선",
    note="2024-03 남포 인근 AIS-off, 무국적 위장선 DE YI와 석탄 4,500t 환적",
    start=[124.4,38.15], waypoints=[[124.1,37.8],[124.3,37.5]], gap=(28,44)),
 dict(id="v_deyi", mmsi="000000000", imo="unknown", name_en="DE YI", name_ko="DE YI(무국적)",
    flag="unregistered", type="cargo", region="west_sea", length_m=88, threat="sts_sanctions",
    flag_history=["Hong Kong","unregistered"], aliases=["HK Yilin ?"], owner="HK Yilin Shipping (실소유 불명)",
    note="신분세탁 무국적 위장선; 덕성호와 STS 랑데부 상대",
    start=[123.6,37.2], waypoints=[[124.2,37.4],[124.5,37.5]], gap=(26,46)),
 dict(id="v_huixin", mmsi="445200188", imo="9110188", name_en="Hui Xin", name_ko="후이신호",
    flag="KP", type="tanker", region="west_sea", length_m=110, threat="sts_sanctions",
    flag_history=["KP"], aliases=[], owner="제재 대상 유조선",
    note="2025-10 동중국해 AIS-off 후 신원미상 유조선과 석유 STS 환적 (MSMT 확인)",
    start=[124.0,33.2], waypoints=[[124.6,33.6],[125.2,34.0]], gap=(30,50)),
 dict(id="v_chonmasan", mmsi="445300565", imo="8916565", name_en="Chonma San", name_ko="천마산호",
    flag="KP", type="tanker", region="west_sea", length_m=100, threat="sanctions_listed",
    flag_history=["KP"], aliases=[], owner="유엔 1718 제재 등재 (2018-03)",
    note="AIS '켜고' 러 보스토치니↔북한 석유 반복 수송 — 집행 공백의 상징",
    start=[125.6,36.4], waypoints=[[125.0,37.0],[124.6,37.5]], gap=None),
 dict(id="v_eagles", mmsi="518998610", imo="9329760", name_en="Eagle S", name_ko="이글 S",
    flag="Cook Islands", type="tanker", region="baltic", length_m=228, threat="cable",
    flag_history=["Cook Islands"], aliases=[], owner="러 그림자함대 추정 (첩보장비 적재 보도)",
    note="2024-12-25 Estlink2 등 케이블 5개 절단; 닻 90~100km 끌린 흔적; 핀란드 특수부대 나포",
    start=[27.9,59.78], waypoints=[[27.0,59.82],[26.55,59.86],[26.1,59.72]], gap=(18,30)),
 dict(id="v_yipeng3", mmsi="412100003", imo="9224984", name_en="Yi Peng 3", name_ko="이펑3호",
    flag="CN", type="cargo", region="baltic", length_m=225, threat="cable",
    flag_history=["CN"], aliases=[], owner="중국 선적 벌크선",
    note="2024-11-17~18 C-Lion1·BCS 절단 의혹; 닻 내린 채 180km 항해",
    start=[27.3,59.98], waypoints=[[24.9,59.92],[22.5,59.2],[20.0,58.5]], gap=(22,40)),
 dict(id="v_vezhen", mmsi="229900123", imo="9420123", name_en="Vezhen", name_ko="베젠호",
    flag="Malta", type="cargo", region="baltic", length_m=200, threat="cable",
    flag_history=["Malta"], aliases=[], owner="몰타 선적 벌크선",
    note="2025-01-26 라트비아–고틀란드 케이블 절단 의혹 (스웨덴 나포 후 사고로 석방)",
    start=[19.5,58.0], waypoints=[[19.0,57.4],[18.6,57.0]], gap=None),
]
for nv in NAMED:
    st = nv.pop("start"); wp = nv.pop("waypoints"); gap = nv.pop("gap")
    nv["mismatch"] = bool(gap)
    add_vessel(**nv)
    make_track(nv["id"], st, wp, 48, gap=gap, base_sog=11.0)

# ---- NORMAL / BACKGROUND FLEET — keep vessels on water (point-in-land test) ----
try:
    COAST = json.load(open(os.path.join(OUT, "coast.json")))
except Exception:
    COAST = {}

def _pip(x, y, ring):
    inside = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def on_land(lon, lat, region):
    for c in COAST.get(region, []):
        for ring in c["rings"]:
            if _pip(lon, lat, ring): return True
    return False

def rand_pos(region, inset=0.15, lonmin=None):
    lo0, la0, lo1, la1 = REGIONS[region]["bbox"]
    lon = lat = None
    for _ in range(60):
        lon = random.uniform(lo0 + inset, lo1 - inset); lat = random.uniform(la0 + inset, la1 - inset)
        if lonmin and lon < lonmin: continue
        if not on_land(lon, lat, region): return [round(lon, 4), round(lat, 4)]
    return [round(lon, 4), round(lat, 4)]

def near_pos(p, region, spread=0.6):
    for _ in range(24):
        cand = [p[0] + random.uniform(-spread, spread), p[1] + random.uniform(-spread, spread)]
        lo0, la0, lo1, la1 = REGIONS[region]["bbox"]
        if lo0 < cand[0] < lo1 and la0 < cand[1] < la1 and not on_land(cand[0], cand[1], region):
            return [round(cand[0], 4), round(cand[1], 4)]
    return p

# Chinese fishing fleet clustering along NLL (the "clutter" that hides threats)
nll_cluster = [124.7,37.6]
for i in range(240):
    c = near_pos(nll_cluster, "west_sea", 0.62)
    v = add_vessel(id=f"v_cn{i}", mmsi=mmsi(), imo=imo(),
        name_en=random.choice(CN_FISH_PY)+f" {random.randint(1,9999)}",
        name_ko="중국어선", flag="CN", type="fishing", region="west_sea",
        length_m=random.randint(20,45), threat=None, owner="중국 어선(선단)",
        note="NLL 인근 조업 선단 — 정상 항적 클러터")
    make_track(v["id"], c, [near_pos(c, "west_sea", 0.08)], 8, base_sog=3.5)

# Korean fishing vessels (with V-Pass, cooperative)
for i in range(150):
    p = rand_pos("west_sea", lonmin=125.3)
    v = add_vessel(id=f"v_kr{i}", mmsi=mmsi(), imo=imo(),
        name_en="", name_ko=random.choice(KR_FISH)+f" {random.randint(1,99)}",
        flag="KR", type="fishing", region="west_sea", length_m=random.randint(8,29),
        threat=None, owner="한국 어선(V-Pass)")
    make_track(v["id"], p, [near_pos(p, "west_sea", 0.12)], 6, base_sog=4.0)

# commercial cargo/tanker traffic (west_sea)
for i in range(70):
    p = rand_pos("west_sea")
    v = add_vessel(id=f"v_cargoW{i}", mmsi=mmsi(), imo=imo(),
        name_en=random.choice(CARGO_NAMES)+f" {random.choice('IVX')}", name_ko="상선",
        flag=random.choice(FLAGS_NORMAL), type=random.choice(["cargo","tanker","bulk"]),
        region="west_sea", length_m=random.randint(120,260), threat=None, owner="상용 해운")
    make_track(v["id"], p, [near_pos(p, "west_sea", 0.7)], 10, base_sog=13.0)

# ROK patrol / navy (west_sea)
for i in range(12):
    p = near_pos([125.6, 37.3], "west_sea", 0.5)
    v = add_vessel(id=f"v_rok{i}", mmsi=mmsi(), imo=imo(), name_en=f"ROK Patrol {i+1}", name_ko=f"해경/해군 경비함 {i+1}",
        flag="KR", type="patrol", region="west_sea", length_m=random.randint(50,120), threat=None, owner="대한민국 해경/해군")
    make_track(v["id"], p, [[p[0]+random.uniform(-0.2,0.2),p[1]+random.uniform(-0.2,0.2)]], 12, base_sog=15.0)

# suspect Chinese fishing with flag/behaviour anomalies (militia candidates)
MILITIA = []
for i in range(9):
    c = near_pos(nll_cluster, "west_sea", 0.5)
    v = add_vessel(id=f"v_mil{i}", mmsi=mmsi(), imo=imo(),
        name_en=random.choice(CN_FISH_PY)+f" {random.randint(1,9999)}", name_ko="위장 의심 어선",
        flag="CN", type="fishing", region="west_sea", length_m=random.randint(35,55),
        threat="militia", owner="해상민병대 의심", flag_history=["CN"],
        note="정상 조업 대비 이상 군집·기동 (해상민병대 후보)", mismatch=random.random()<0.5)
    g = (random.randint(24,36), random.randint(40,52)) if v.get("mismatch") else None
    make_track(v["id"], c, [near_pos(c, "west_sea", 0.15)], 20, gap=g, base_sog=6.0)
    MILITIA.append(v["id"])

# Zone-intrusion scenario vessels — start OUTSIDE a zone, cross IN mid-window (H≈30-34)
# so during playback the threat board pops a live "구역 침범" alert in real time.
INTRUDERS = [
    dict(id="v_intr1", name_ko="미상 어선 (NLL 침범)", flag="CN", vtype="fishing", threat="militia",
         start=[125.35, 38.35], wp=[[125.15, 38.02], [125.0, 37.72], [124.85, 37.6]],
         note="NLL 이북에서 특정금지구역으로 남하 침범 (실시간 탐지)"),
    dict(id="v_intr2", name_ko="접근 미상선 (PMZ 구조물)", flag="unregistered", vtype="cargo", threat="sts_sanctions",
         start=[124.7, 35.7], wp=[[124.0, 34.4], [123.6, 33.4], [123.5, 33.1]],
         note="선란 구조물 방향 PMZ 진입 접근 (실시간 탐지)"),
]
for it in INTRUDERS:
    add_vessel(id=it["id"], mmsi=mmsi(), imo=imo(), name_en="", name_ko=it["name_ko"],
        flag=it["flag"], type=it["vtype"], region="west_sea", length_m=random.randint(30, 90),
        threat=it["threat"], owner="구역 침범 시나리오", note=it["note"], flag_history=[it["flag"]])
    make_track(it["id"], it["start"], it["wp"], 40, base_sog=8.0)

# NK small wooden boat (low-RCS, no AIS at all) — appears only in SAR
NK_BOAT = add_vessel(id="v_nkboat", mmsi="", imo="", name_en="unknown wooden boat", name_ko="북한 소형목선(미상)",
    flag="unknown", type="unknown", region="west_sea", length_m=7, threat="infiltration",
    owner="미상 (비협조 표적)", note="AIS/V-Pass 미탑재·저RCS; 어선 클러터에 은닉 (2025-03 어청도 사례형)", mismatch=True)
tracks["v_nkboat"] = []  # no AIS ever

# baltic background traffic
for i in range(200):
    p = rand_pos("baltic")
    v = add_vessel(id=f"v_balt{i}", mmsi=mmsi(), imo=imo(),
        name_en=random.choice(CARGO_NAMES)+f" {random.randint(1,99)}", name_ko="상선/여객선",
        flag=random.choice(FLAGS_NORMAL), type=random.choice(["cargo","tanker","ferry","bulk"]),
        region="baltic", length_m=random.randint(90,300), threat=None, owner="상용 해운")
    make_track(v["id"], p, [near_pos(p, "baltic", 0.7)], 10, base_sog=14.0)

# a few extra baltic shadow-fleet tankers (AIS gaps near cables)
for i in range(6):
    p = [27.5+random.uniform(-0.5,0.4), 59.9+random.uniform(-0.3,0.3)]
    v = add_vessel(id=f"v_shadow{i}", mmsi=mmsi(), imo=imo(), name_en=f"Dark Tanker {i+1}", name_ko="그림자함대 유조선",
        flag=random.choice(SUSPECT_FLAGS), type="tanker", region="baltic", length_m=random.randint(180,250),
        threat="sanctions_listed", owner="러 그림자함대 추정", flag_history=random.sample(SUSPECT_FLAGS,2),
        note="AIS 장기 두절(유럽선 대비 6배); 편의치적", mismatch=True)
    make_track(v["id"], p, [[25.0,59.4],[22.0,59.0]], 24, gap=(random.randint(16,26), random.randint(34,48)), base_sog=11.0)

# ---------------------------------------------------------------- SAR detections
# Non-cooperative detections; some match AIS, some DON'T (= SEASENTINEL / dark).
sar = []
sid = 0
def sar_det(lon, lat, h, matched_vessel=None, conf=0.8, region="west_sea", length_est=None):
    global sid; sid += 1
    return {"id": f"sar_{sid:04d}", "t": at(h), "lon": round(lon+random.uniform(-0.01,0.01),4),
            "lat": round(lat+random.uniform(-0.01,0.01),4), "region": region,
            "sensor": random.choice(["Sentinel-1","ICEYE","Capella","KOMPSAT-6"]),
            "length_est_m": length_est or random.randint(20,240),
            "confidence": round(conf,2), "matched_vessel": matched_vessel,
            "mismatch": matched_vessel is None}

# scatter matched detections over cooperative vessels (realistic background)
coop = [v for v in vessels if v["id"] in tracks and tracks[v["id"]] and not v.get("mismatch")]
for v in random.sample(coop, min(120, len(coop))):
    tp = random.choice(tracks[v["id"]])
    sar.append(sar_det(tp["lon"], tp["lat"], random.randint(0,WINDOW_H), matched_vessel=v["id"],
                       conf=random.uniform(0.7,0.95), region=v["region"], length_est=v["length_m"]))

# THE money shots: unmatched SAR detections placed at each dark vessel's own
# AIS-off window (time INSIDE the gap, position at the dead-reckoned midpoint) so
# scrubbing into the gap reliably confirms the SEASENTINEL.
for vid, info in DARKINFO.items():
    v = next((x for x in vessels if x["id"]==vid), None)
    if not v: continue
    g0, g1 = info["gap"]; mlon, mlat = info["mid"]
    for _ in range(random.randint(2,3)):
        h = random.uniform(g0+1, g1-1)
        sar.append(sar_det(mlon+random.uniform(-0.08,0.08), mlat+random.uniform(-0.06,0.06), h,
                           matched_vessel=None, conf=random.uniform(0.72,0.9),
                           region=v["region"], length_est=v["length_m"]))

# NK wooden boat: several faint SAR hits in the fishing clutter
for _ in range(4):
    sar.append(sar_det(124.8+random.uniform(-0.3,0.5), 37.6+random.uniform(-0.15,0.15),
                      random.randint(8,40), matched_vessel=None, conf=random.uniform(0.45,0.62),
                      region="west_sea", length_est=random.randint(6,10)))

# ---------------------------------------------------------------- OSINT feed
osint = [
 dict(id="o1", t=at(2), region="west_sea", kind="port_logistics", lang="ko",
   text="산둥 스다오항 유류·보급 반출량 평년 대비 급증 — 대형 선단 출항 정황", source="상용 위성/물류 데이터",
   entities=["China fishing fleet"], sentiment=-0.3, weight=0.7),
 dict(id="o2", t=at(6), region="west_sea", kind="social", lang="zh",
   text="어촌 커뮤니티서 '단기 선원 대규모 모집' 게시물 급증 (연평 인근 조업 언급)", source="SNS/포럼 마이닝",
   entities=["maritime militia"], sentiment=-0.5, weight=0.75),
 dict(id="o3", t=at(10), region="west_sea", kind="news", lang="ko",
   text="꽃게철 앞두고 NLL 특정금지구역 중국어선 일평균 98척 — 최근 5년 최다", source="해양경찰청 브리핑",
   entities=["China fishing fleet"], sentiment=-0.4, weight=0.6),
 dict(id="o4", t=at(14), region="west_sea", kind="sat_change", lang="en",
   text="Satellite change-detection: new activity around Shenlan-2 platform (small craft alongside)",
   source="상용 위성 변화탐지", entities=["s_seolan2"], sentiment=-0.6, weight=0.8),
 dict(id="o5", t=at(20), region="west_sea", kind="registry", lang="en",
   text="Vessel 'DE YI' shows registry gap; last known operator HK Yilin Shipping — flag lapsed",
   source="선박등록부(GISIS)", entities=["v_deyi"], sentiment=-0.7, weight=0.85),
 dict(id="o6", t=at(26), region="west_sea", kind="news", lang="ko",
   text="북·중·러 해상 협력 강화로 '합법-제재회피 구분 어려운 회색지대 물류통로' 형성 우려", source="RFA",
   entities=["v_deoksong","v_chonmasan"], sentiment=-0.5, weight=0.6),
 dict(id="o7", t=at(30), region="baltic", kind="ais_gap", lang="en",
   text="Russia-linked tanker AIS blackout rate 6x EU average; notable gaps up 2x YoY", source="Windward/FTM",
   entities=["v_eagles"], sentiment=-0.6, weight=0.7),
 dict(id="o8", t=at(34), region="baltic", kind="news", lang="en",
   text="NATO stands up 'Baltic Sentry' after 11 cables damaged in 15 months", source="Defense News",
   entities=["c_estlink2","c_clion1"], sentiment=-0.4, weight=0.65),
 dict(id="o9", t=at(40), region="west_sea", kind="port_logistics", lang="ko",
   text="순싱39호 부산항 입항 신고 접수 — 직전 항적에 대만 인근 케이블 구간 저속 배회 포함", source="항만 입출항 데이터",
   entities=["v_shunxin39","c_tpe"], sentiment=-0.8, weight=0.9),
 dict(id="o10", t=at(46), region="west_sea", kind="social", lang="ko",
   text="연평도 어민 '레이더에 안 잡히는 소형보트 목격' 다수 제보", source="지역 커뮤니티",
   entities=["v_nkboat"], sentiment=-0.5, weight=0.55),
]
# pad with routine background OSINT so the feed looks voluminous
BG = ["정기 어업지도선 순찰 보고","기상 악화 예보(시정 2km 이하)","상용 위성 재방문 스케줄 갱신",
      "AIS 기지국 커버리지 점검 완료","해상 교통량 정상 범위","항만 하역 실적 평이"]
for i in range(24):
    osint.append(dict(id=f"obg{i}", t=at(random.randint(0,WINDOW_H)),
        region=random.choice(["west_sea","baltic"]), kind="routine", lang="ko",
        text=random.choice(BG), source="자동 수집", entities=[], sentiment=0.0, weight=0.1))

# ---------------------------------------------------------------- ALERTS (engine output)
# Curated SEASENTINEL threat events with evidence chains + kill-chain timeline.
def alert(**k): return k
ALERTS = [
 alert(id="a_shunxin39", region="west_sea", vessel="v_shunxin39", score=94, level="CRITICAL",
   title_ko="순싱39호 — 케이블 근접 다크선박 + 신원세탁", title_en="Shunxin-39 — dark vessel near cable + identity laundering",
   category="critical_infrastructure",
   signals=["AIS_GAP","GEO_CABLE_PROXIMITY","IDENTITY_TAMPERING","LOITERING","INBOUND_KR_PORT"],
   why=["AIS 20–34h 두절(공백) 구간이 TPE 케이블 구간과 겹침",
        "동일 선체가 Cameroon↔Tanzania 이중선적 (Xing Shun-39 별칭)",
        "부산항 입항 신고 — 직전 항적 저속 배회(loitering)",
        "SAR 미매칭 탐지 3건이 공백 구간에 존재"],
   evidence=["sar:mismatch","osint:o9","registry:dual_flag","geofence:c_tpe"],
   timeline=[["전조", at(8), "SNS·물류 이상 없음, 정상 항적"],["기동", at(20), "AIS OFF (공백 진입)"],
             ["접촉", at(27), "TPE 케이블 구간 저속 배회 + SAR 미매칭 탐지"],["재출현", at(34), "AIS ON, 부산 침로"],
             ["전파", at(40), "부산 입항 신고 → KT 공동소유 회선 위험"]],
   propagation=["c_tpe(케이블)","p_busan(항만)","국제 통신·금융 트래픽"]),
 alert(id="a_deoksong", region="west_sea", vessel="v_deoksong", score=90, level="CRITICAL",
   title_ko="덕성호 ⇄ DE YI — 제재회피 STS 환적(석탄)", title_en="Deoksong ⇄ DE YI — sanctions STS transfer",
   category="sanctions_evasion",
   signals=["AIS_GAP","DARK_STS_RENDEZVOUS","STATELESS_PARTNER","PORT_ORIGIN_NAMPO"],
   why=["덕성호·DE YI 모두 동일 시간창에 AIS OFF 후 근접 랑데부",
        "DE YI 무국적(등록 공백) — 신분세탁 위장선",
        "출발항 남포(북한 최대 석탄 반출항)","SAR 미매칭 탐지가 랑데부 좌표와 일치"],
   evidence=["sar:mismatch","osint:o5","osint:o6","pair:v_deyi"],
   timeline=[["전조", at(18), "남포 출항, 정상 신고"],["기동", at(28), "양선 AIS OFF"],
             ["접촉", at(36), "공해상 STS 랑데부(석탄 4,500t)"],["재출현", at(46), "AIS ON, 산개"]],
   propagation=["유엔 제재 위반","북·중·러 회색지대 물류통로"]),
 alert(id="a_eagles", region="baltic", vessel="v_eagles", score=96, level="CRITICAL",
   title_ko="Eagle S — 앵커드래그 해저케이블 절단", title_en="Eagle S — anchor-drag cable cut",
   category="critical_infrastructure",
   signals=["AIS_GAP","GEO_CABLE_PROXIMITY","ANCHOR_DRAG","SHADOW_FLEET","LOW_SPEED"],
   why=["AIS 18–30h 공백이 Estlink2 경로와 정확히 교차","저속·비정상 침로(닻 끌림 패턴)",
        "Cook Islands 편의치적 그림자함대","공백 구간 SAR 미매칭 탐지"],
   evidence=["sar:mismatch","osint:o7","geofence:c_estlink2"],
   timeline=[["전조", at(12), "우스트루가 출항"],["기동", at(18), "AIS OFF, 케이블 접근"],
             ["접촉", at(24), "Estlink2 교차 + 저속 앵커드래그"],["피해", at(28), "전력 1016→358MW 급감"],
             ["대응", at(32), "핀란드 특수부대 나포"]],
   propagation=["Estlink2(전력)","핀란드-에스토니아 그리드","통신 케이블 4개"]),
 alert(id="a_yipeng3", region="baltic", vessel="v_yipeng3", score=88, level="HIGH",
   title_ko="Yi Peng 3 — 케이블 2개 근접 앵커드래그 의혹", title_en="Yi Peng 3 — dual cable anchor-drag",
   category="critical_infrastructure",
   signals=["AIS_GAP","GEO_CABLE_PROXIMITY","ANCHOR_DRAG","JURISDICTION_GAP"],
   why=["공백 구간이 C-Lion1·BCS 교차점과 겹침","닻 내린 채 약 180km 항해 패턴","기국 협조 없이는 수사 불가(관할권 공백)"],
   evidence=["sar:mismatch","osint:o8","geofence:c_clion1"],
   timeline=[["기동", at(22), "AIS OFF"],["접촉", at(30), "C-Lion1·BCS 근접"],["재출현", at(40), "카테가트서 억류"]],
   propagation=["C-Lion1(핀-독 유일 직결)","BCS East-West"]),
 alert(id="a_militia", region="west_sea", vessel=MILITIA[0] if MILITIA else "v_mil0", score=78, level="HIGH",
   title_ko="해상민병대 의심 군집 — 회색지대 전조", title_en="Suspected militia mustering — gray-zone precursor",
   category="gray_zone",
   signals=["ABNORMAL_CLUSTER","AIS_GAP","OSINT_RECRUITMENT","SAT_CHANGE"],
   why=["정상 조업 대비 이상 군집·동조 기동","선원 대규모 모집 SNS 급증(OSINT)","선란2 인근 소형정 활동 위성 변화탐지"],
   evidence=["osint:o2","osint:o4","cluster:nll"],
   timeline=[["전조", at(6), "SNS 선원 모집 급증"],["징후", at(14), "선란2 인근 소형정 포착"],["집결", at(30), "이상 군집 형성"]],
   propagation=["선란 구조물 상주화","서해 딥그레이존화"]),
 alert(id="a_nkboat", region="west_sea", vessel="v_nkboat", score=72, level="HIGH",
   title_ko="북한 소형목선 — 비협조·저RCS 표적(SAR 단독)", title_en="NK wooden boat — non-cooperative low-RCS (SAR-only)",
   category="infiltration",
   signals=["NO_AIS","SAR_ONLY","LOW_RCS","FISHING_CLUTTER"],
   why=["AIS/V-Pass 신호 전무","희미한 SAR 탐지만 존재(신뢰도 0.45~0.62)","중국어선 클러터에 은닉","2025-03 어청도(중국어선 200척 틈) 사례형"],
   evidence=["sar:mismatch","osint:o10"],
   timeline=[["징후", at(8), "어민 '레이더 미탐지 소형보트' 제보"],["탐지", at(30), "클러터 속 희미한 SAR 다중 탐지"]],
   propagation=["NLL 이남 침투","감시 공백 노출"]),
 alert(id="a_shadow", region="baltic", vessel="v_shadow0", score=69, level="MED",
   title_ko="그림자함대 유조선 — AIS 장기 두절", title_en="Shadow-fleet tanker — prolonged AIS blackout",
   category="sanctions_evasion",
   signals=["AIS_GAP","FLAG_HOPPING","SHADOW_FLEET"],
   why=["AIS 두절 유럽선 대비 6배","단기 다중 기국세탁","편의치적·불투명 소유"],
   evidence=["osint:o7","registry:flag_hopping"],
   timeline=[["기동", at(20), "AIS OFF"],["재출현", at(42), "AIS ON"]],
   propagation=["러 원유 제재 회피","임계 인프라 잠재 위협"]),
]

# ---------------------------------------------------------------- entity graph
# nodes: vessels, structures, cables, ports, orgs, flags; edges: relations
gnodes, gedges = [], []
seen = set()
def gnode(nid, label, ntype, meta=None):
    if nid in seen: return
    seen.add(nid); gnodes.append({"id":nid,"label":label,"type":ntype,"meta":meta or {}})
def gedge(a,b,rel): gedges.append({"source":a,"target":b,"rel":rel})

for vid in ["v_shunxin39","v_deoksong","v_deyi","v_huixin","v_chonmasan","v_eagles","v_yipeng3","v_vezhen"]:
    v = next(x for x in vessels if x["id"]==vid)
    gnode(vid, v["name_ko"] or v["name_en"], "vessel", {"flag":v["flag"],"threat":v.get("threat")})
    gnode("flag:"+v["flag"], v["flag"], "flag")
    gedge(vid, "flag:"+v["flag"], "current_flag")
    for fh in v.get("flag_history",[]):
        gnode("flag:"+fh, fh, "flag"); gedge(vid, "flag:"+fh, "was_flagged")
    for al in v.get("aliases",[]):
        gnode("alias:"+al, al, "alias"); gedge(vid, "alias:"+al, "aka")
# incident-specific edges
gedge("v_deoksong","v_deyi","sts_rendezvous")
gnode("c_tpe","TPE 케이블","cable"); gedge("v_shunxin39","c_tpe","anchor_proximity")
gnode("p_busan","부산항","port"); gedge("v_shunxin39","p_busan","inbound")
gnode("c_estlink2","Estlink 2","cable"); gedge("v_eagles","c_estlink2","cable_cut")
gnode("c_clion1","C-Lion1","cable"); gedge("v_yipeng3","c_clion1","anchor_proximity")
gnode("org:jieyang","Jie Yang Trading","org"); gedge("v_shunxin39","org:jieyang","owned_by")
gnode("org:hkyilin","HK Yilin Shipping","org"); gedge("v_deyi","org:hkyilin","last_operator")
gnode("s_seolan2","선란 2호","structure");
for m in MILITIA[:4]:
    v=next(x for x in vessels if x["id"]==m); gnode(m, v["name_ko"], "vessel", {"threat":"militia"}); gedge(m,"s_seolan2","mustering_near")

# ---------------------------------------------------------------- write files
def dump(name, obj):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",",":"))
    return os.path.getsize(p)

n_pts = sum(len(v) for v in tracks.values())
meta = {
    "generated_for": "D4D T4 — SEASENTINEL Maritime Intelligence demo",
    "scenario_window": {"start": iso(T0), "hours": WINDOW_H, "anchor":"2026-06-24 연평도 대통령 방문"},
    "counts": {"vessels": len(vessels), "ais_points": n_pts, "sar_detections": len(sar),
               "sar_mismatch": sum(1 for s in sar if s["mismatch"]), "osint": len(osint),
               "alerts": len(ALERTS), "cables": len(CABLES), "structures": len(STRUCTURES),
               "graph_nodes": len(gnodes), "graph_edges": len(gedges)},
    "sources": [
        "국방통계연보 2024 표3-7 (북한 해상도발)","해양경찰청 중국어선 출몰/나포 집계",
        "Global Fishing Watch API (SAR↔AIS 융합 모델 참조)","MSMT 대북제재 STS 보고(2025-10)",
        "아산정책연구원 이슈브리프 2025-13/15 (서해 구조물·해저케이블)",
        "핀란드/스웨덴 케이블 사보타주 수사(Eagle S, Yi Peng 3, Vezhen)"],
    "note": "합성 데이터 — 실제 검증 사건의 좌표·선명·수법을 반영해 재구성. 무대 시연용 오프라인 데이터셋.",
}

sizes = {}
sizes["regions.json"]=dump("regions.json", {"regions":REGIONS,"geofences":GEOFENCES})
sizes["geo.json"]=dump("geo.json", GEO)
sizes["vessels.json"]=dump("vessels.json", vessels)
sizes["tracks.json"]=dump("tracks.json", tracks)
sizes["sar.json"]=dump("sar.json", sar)
sizes["osint.json"]=dump("osint.json", osint)
sizes["infrastructure.json"]=dump("infrastructure.json", {"cables":CABLES,"structures":STRUCTURES,"ports":PORTS})
sizes["alerts.json"]=dump("alerts.json", ALERTS)
sizes["graph.json"]=dump("graph.json", {"nodes":gnodes,"edges":gedges})
sizes["meta.json"]=dump("meta.json", meta)

print("=== SEASENTINEL dataset generated ===")
for k,v in meta["counts"].items(): print(f"  {k:16s}: {v}")
print("--- files ---")
for k,v in sizes.items(): print(f"  {k:22s}: {v/1024:.1f} KB")
print("total KB:", round(sum(sizes.values())/1024,1))
