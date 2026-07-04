// SEASENTINEL — Maritime Domain Awareness demo (zero-dependency, offline)
let T0 = Date.parse("2026-06-24T00:00:00Z");
let WINDOW_H = 72;
const SVGNS = "http://www.w3.org/2000/svg";
const $ = (s, r = document) => r.querySelector(s);
const el = (t, a = {}, ...kids) => { const e = document.createElement(t); for (const k in a) k === "html" ? (e.innerHTML = a[k]) : e.setAttribute(k, a[k]); kids.flat().forEach(c => e.append(c)); return e; };
const S = (t, a = {}) => { const e = document.createElementNS(SVGNS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
const hourOf = iso => (Date.parse(iso) - T0) / 3600000;
const fmtH = h => { const d = new Date(T0 + h * 3600000); return d.toISOString().slice(5, 16).replace("T", " ") + "Z"; };

const state = { region: "west_sea", H: 27, playing: false, sel: null, tab: "detail", ent: null, watch: new Set(), tasked: [], dispatch: [], log: [], speed: 1, zoneMem: {}, liveAlerts: [], zoneReady: false, aiOsint: [], aiGraph: null, triage: true };
const SPEEDS = [0.5, 1, 2, 4];
const TRIAGE_THRESHOLD = 60;   // 이 점수 이상만 "확인 대상"으로 승격
let TRIAGE = null;             // 최근 triage 결과 (drawDynamic ↔ renderAlerts 공유)
let D = null; // dataset
let byId = {};
const HERO = new Set(["v_shunxin39", "v_deoksong", "v_deyi", "v_huixin", "v_chonmasan", "v_eagles", "v_yipeng3", "v_vezhen"]);
let CFG_MODEL = "LLM";
let SEL_MODEL = null;   // user-selected LLM model (null = server default)

async function loadAll() {
  const names = ["regions", "coast", "vessels", "tracks", "sar", "osint", "infrastructure", "alerts", "graph", "meta"];
  const res = await Promise.all(names.map(n => fetch(`data/${n}.json`, { cache: "no-store" }).then(r => r.json())));
  const [regions, coast, vessels, tracks, sar, osint, infra, alerts, graph, meta] = res;
  if (meta && meta.window && meta.window.start && meta.window.end) {
    T0 = Date.parse(meta.window.start);
    WINDOW_H = Math.max(1, Math.ceil((Date.parse(meta.window.end) - T0) / 3600000));
    state.H = WINDOW_H;
  }
  for (const id in tracks) tracks[id].forEach(p => p.h = hourOf(p.t));
  sar.forEach(s => s.h = hourOf(s.t));
  osint.forEach(o => o.h = hourOf(o.t));
  D = { regions: regions.regions, geofences: regions.geofences, coast, vessels, tracks, sar, osint, infra, alerts, graph, meta };
  vessels.forEach(v => byId[v.id] = v);
}

// ---------- projection ----------
let PROJ = null;
function buildProjection() {
  const wrap = $(".mapwrap"); const W = Math.max(320, wrap.clientWidth), Hh = Math.max(280, wrap.clientHeight), pad = 34;
  const r = D.regions[state.region]; const [lo0, la0, lo1, la1] = r.bbox;
  const latS = Math.cos((r.center[1]) * Math.PI / 180);
  const spanLon = (lo1 - lo0) * latS, spanLat = (la1 - la0);
  const scale = Math.min((W - 2 * pad) / spanLon, (Hh - 2 * pad) / spanLat);
  const drawnW = spanLon * scale, drawnH = spanLat * scale;
  const ox = (W - drawnW) / 2, oy = (Hh - drawnH) / 2;
  PROJ = { W, Hh, project: (lon, lat) => [ox + (lon - lo0) * latS * scale, oy + (la1 - lat) * scale] };
}

// ---------- zoom / pan (viewBox based) ----------
let VIEW = { x: 0, y: 0, w: 0, h: 0 };
function applyView() { const svg = $("svg.map"); svg.setAttribute("viewBox", `${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`); const zl = $("#zoomlvl"); if (zl) zl.textContent = (PROJ.W / VIEW.w).toFixed(1) + "×"; }
function resetView() { VIEW = { x: 0, y: 0, w: PROJ.W, h: PROJ.Hh }; applyView(); }
function clampView() { VIEW.w = Math.min(VIEW.w, PROJ.W); VIEW.h = VIEW.w * (PROJ.Hh / PROJ.W); VIEW.x = Math.max(0, Math.min(PROJ.W - VIEW.w, VIEW.x)); VIEW.y = Math.max(0, Math.min(PROJ.Hh - VIEW.h, VIEW.y)); }
function zoomBy(factor, px = 0.5, py = 0.5) {
  const sx = VIEW.x + px * VIEW.w, sy = VIEW.y + py * VIEW.h;
  let nw = VIEW.w * factor; nw = Math.max(PROJ.W / 14, Math.min(PROJ.W, nw));
  VIEW.w = nw; VIEW.h = nw * (PROJ.Hh / PROJ.W);
  VIEW.x = sx - px * VIEW.w; VIEW.y = sy - py * VIEW.h; clampView(); applyView();
}

// ---------- vessel state at time H ----------
// A vessel is "dark" ONLY if it has a genuine AIS-off intent (v.mismatch) AND
// the current time falls inside its real signal gap. Sparsely-sampled normal
// vessels are interpolated and shown as cooperative.
function stateAt(v, H) {
  const pts = D.tracks[v.id]; if (!pts || !pts.length) return null;
  const first = pts[0].h, last = pts[pts.length - 1].h;
  if (H < first - 1 || H > last + 1) return null;
  let before = null, after = null;
  for (const p of pts) {
    if (p.h <= H && (!before || p.h > before.h)) before = p;
    if (p.h >= H && (!after || p.h < after.h)) after = p;
  }
  let lon, lat;
  if (before && after) { const f = after.h === before.h ? 0 : (H - before.h) / (after.h - before.h); lon = before.lon + (after.lon - before.lon) * f; lat = before.lat + (after.lat - before.lat) * f; }
  else { const p = before || after; lon = p.lon; lat = p.lat; }
  let dark = false;
  if (v.mismatch) {
    let g0 = null, g1 = null, best = 0;
    for (let i = 1; i < pts.length; i++) { const g = pts[i].h - pts[i - 1].h; if (g > best) { best = g; g0 = pts[i - 1]; g1 = pts[i]; } }
    if (best > 4 && g0 && H > g0.h + 0.5 && H < g1.h - 0.5) dark = true;
  }
  return { lon, lat, status: dark ? "dark" : "coop" };
}

// ---------- TRIAGE engine: 컨택트 홍수 → 확인할 소수 ----------
// 이미 들어오는 신호(레이더/AIS)만으로 '확인 가치 있는 소수'를 자동 랭킹.
// 저RCS·무AIS 목선처럼 클러터에 묻힐 신호는 행동·맥락으로 재점수화해 끌어올린다.
function triageScore(v, st) {
  const al = D.alerts.find(a => a.vessel === v.id);
  let score = 0; const reasons = [];
  if (al) { score = al.score; reasons.push(al.title_ko.split(" — ")[0].split("(")[0].trim()); }
  if (v.id === "v_nkboat" || v.threat === "infiltration") { if (score < 78) score = 78; reasons.push("저RCS·무AIS — 해면클러터 신호 재점수화"); }
  if (st && st.status === "dark") { if (score < 72) score = 72; reasons.push("AIS 공백(다크선박)"); }
  if (["cable", "sts_sanctions", "sanctions_listed"].includes(v.threat)) { if (score < 84) score = 84; reasons.push("제재·임계인프라 위협"); }
  if (v.threat === "militia") { if (score < 66) score = 66; reasons.push("위장 의심 군집"); }
  if (state.zoneMem[v.id]) { if (score < 70) score = 70; reasons.push("감시구역 침범"); }
  if (v.flag_history && v.flag_history.length > 1) { score += 6; reasons.push("기국세탁"); }
  if (v.flag === "unregistered" || v.flag === "unknown") { score += 6; reasons.push("무국적/미상"); }
  return { score: Math.min(99, Math.round(score)), reasons: [...new Set(reasons)] };
}
function triageContacts() {
  const region = state.region; let total = 0; const flagged = [];
  for (const v of D.vessels) {
    if (v.region !== region) continue;
    const st = v.id === "v_nkboat" ? { status: "sar" } : stateAt(v, state.H);
    if (!st) continue;
    total++;
    const s = triageScore(v, st);
    if (s.score >= TRIAGE_THRESHOLD) flagged.push({ v, st, score: s.score, reasons: s.reasons });
  }
  flagged.sort((a, b) => b.score - a.score);
  const pct = total ? Math.round((1 - flagged.length / total) * 1000) / 10 : 0;
  return { total, flagged, pct };
}

// ---------- zone intrusion (real-time popup) ----------
function pipJS(x, y, ring) { let ins = false, n = ring.length, j = n - 1; for (let i = 0; i < n; i++) { const [xi, yi] = ring[i], [xj, yj] = ring[j]; if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) ins = !ins; j = i; } return ins; }
function checkIntrusions() {
  const gz = D.geofences.filter(g => g.region === state.region && g.kind === "polygon");
  let changed = false;
  for (const v of D.vessels) {
    if (v.region !== state.region) continue;
    if (!(v.threat || state.watch.has(v.id))) continue;   // 감시 대상(위협·관심표적)만
    const st = stateAt(v, state.H);
    let zone = null;
    if (st) for (const g of gz) { if (pipJS(st.lon, st.lat, g.ring)) { zone = g; break; } }
    const prevId = state.zoneMem[v.id] || null, zoneId = zone ? zone.id : null;
    if (zoneId !== prevId) {
      state.liveAlerts = state.liveAlerts.filter(a => a.vid !== v.id);
      if (zone) {
        const score = (v.threat === "cable" || v.threat === "sts_sanctions") ? 92 : v.threat === "militia" ? 82 : v.threat === "infiltration" ? 79 : 75;
        state.liveAlerts.unshift({ vid: v.id, zone: zone.id, zoneName: zone.name_ko, t: fmtH(state.H), name: v.name_ko || v.name_en, flag: v.flag, threat: v.threat, score });
        state.liveAlerts = state.liveAlerts.slice(0, 8);
        if (state.zoneReady) { toast(`🚨 구역 침범 — ${v.name_ko || v.name_en} · ${zone.name_ko}`); logAction(v.id, `구역 침범: ${zone.name_ko}`); }
      }
      changed = true;
    }
    state.zoneMem[v.id] = zoneId;
  }
  state.zoneReady = true;
  if (changed) renderAlerts();
}

// ---------- static map layers ----------
let gStatic, gDyn;
function drawStatic() {
  const svg = $("svg.map"); svg.innerHTML = "";
  VIEW = { x: 0, y: 0, w: PROJ.W, h: PROJ.Hh };
  svg.setAttribute("viewBox", `0 0 ${PROJ.W} ${PROJ.Hh}`);
  const zl = $("#zoomlvl"); if (zl) zl.textContent = "1.0×";
  svg.onclick = e => { if (e.target === svg || e.target.tagName === "polygon") closeEntity(); };
  gStatic = S("g"); gDyn = S("g"); svg.append(gStatic, gDyn);
  const P = PROJ.project;
  // graticule
  const r = D.regions[state.region], [lo0, la0, lo1, la1] = r.bbox;
  for (let lo = Math.ceil(lo0); lo < lo1; lo++) { const [x, y0] = P(lo, la0), [, y1] = P(lo, la1); gStatic.append(S("line", { x1: x, y1: y0, x2: x, y2: y1, stroke: "#12203a", "stroke-width": .5 })); }
  for (let la = Math.ceil(la0); la < la1; la++) { const [x0, y] = P(lo0, la), [x1] = P(lo1, la); gStatic.append(S("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: "#12203a", "stroke-width": .5 })); }
  // land (real coastline, clipped Natural Earth)
  (D.coast[state.region] || []).forEach(C => {
    let big = null, bigA = 0;
    C.rings.forEach(ring => {
      const pts = ring.map(([lo, la]) => P(lo, la).join(",")).join(" ");
      gStatic.append(S("polygon", { points: pts, fill: "#0e1a2a", stroke: "#274162", "stroke-width": 1, "fill-opacity": .95 }));
      if (ring.length > bigA) { bigA = ring.length; big = ring; }
    });
    if (big) { const c = big.reduce((a, p) => [a[0] + p[0], a[1] + p[1]], [0, 0]).map(x => x / big.length); const [tx, ty] = P(c[0], c[1]); const t = S("text", { x: tx, y: ty, fill: "#43597a", "font-size": 13, "text-anchor": "middle", "font-family": "var(--mono)", "letter-spacing": "1px" }); t.textContent = C.name; gStatic.append(t); }
  });
  // geofences
  D.geofences.filter(g => g.region === state.region).forEach(g => {
    if (g.kind === "line") { const d = g.path.map(([lo, la], i) => (i ? "L" : "M") + P(lo, la).join(" ")).join(" "); gStatic.append(S("path", { d, fill: "none", stroke: "#ff5a5f", "stroke-width": 1.6, "stroke-dasharray": "7 5", opacity: .9 })); const [lx, ly] = P(...g.path[0]); const t = S("text", { x: lx - 4, y: ly - 6, fill: "#ff8a8f", "font-size": 11, "text-anchor": "end" }); t.textContent = g.name_ko; gStatic.append(t); }
    else { const pts = g.ring.map(([lo, la]) => P(lo, la).join(",")).join(" "); gStatic.append(S("polygon", { points: pts, fill: "#f5a62310", stroke: "#f5a623", "stroke-width": 1, "stroke-dasharray": "4 4", opacity: .7 })); const [tx, ty] = P(g.ring[0][0], g.ring[0][1]); const t = S("text", { x: tx + 4, y: ty + 13, fill: "#f5a623", "font-size": 10 }); t.textContent = g.name_ko; gStatic.append(t); }
  });
  // cables (clickable)
  D.infra.cables.filter(c => c.region === state.region).forEach(c => {
    const d = c.path.map(([lo, la], i) => (i ? "L" : "M") + P(lo, la).join(" ")).join(" ");
    const hit = S("path", { d, fill: "none", stroke: "#000", "stroke-width": 12, opacity: 0, class: "clickable" }); hit.onclick = () => selectEntity("cable", c.id); gStatic.append(hit);
    gStatic.append(S("path", { d, fill: "none", stroke: "#4ad3c8", "stroke-width": 2, opacity: .55, "stroke-dasharray": "1 0" }));
    const [mx, my] = P(...c.path[Math.floor(c.path.length / 2)]); const t = S("text", { x: mx, y: my - 5, fill: "#4ad3c8", "font-size": 10, "text-anchor": "middle" }); t.textContent = "⌁ " + c.name.split(" ")[0]; gStatic.append(t);
  });
  // structures (clickable)
  D.infra.structures.filter(s => s.region === state.region).forEach(s => {
    const [x, y] = P(...s.lonlat); const big = s.kind !== "buoy";
    const r = S("rect", { x: x - (big ? 5 : 3), y: y - (big ? 5 : 3), width: big ? 10 : 6, height: big ? 10 : 6, fill: big ? "#f5a623" : "#8a6d1e", stroke: "#1a1204", "stroke-width": 1, transform: `rotate(45 ${x} ${y})`, opacity: .95, class: "clickable" });
    r.onclick = () => selectEntity("structure", s.id); gStatic.append(r);
    if (big) { const t = S("text", { x: x + 8, y: y + 3, fill: "#f5c66a", "font-size": 10, class: "clickable" }); t.textContent = s.name_ko; t.onclick = () => selectEntity("structure", s.id); gStatic.append(t); }
  });
  // ports (clickable)
  D.infra.ports.filter(p => p.region === state.region).forEach(p => {
    const [x, y] = P(...p.lonlat); const r = S("rect", { x: x - 3.5, y: y - 3.5, width: 7, height: 7, fill: "#9fb4d0", stroke: "#050a12", class: "clickable" }); r.onclick = () => selectEntity("port", p.id); gStatic.append(r);
    const t = S("text", { x: x + 6, y: y + 3, fill: "#9fb4d0", "font-size": 10 }); t.textContent = "⚓ " + p.name_ko; gStatic.append(t);
  });
}

// ---------- dynamic layer (vessels, sar, mismatch, selected track) ----------
function drawDynamic() {
  if (!gDyn) return; gDyn.innerHTML = ""; const P = PROJ.project; const H = state.H;
  const region = state.region; let coop = 0, dark = 0, mism = 0;
  const sel = state.sel ? D.alerts.find(a => a.id === state.sel) : null;

  // selected vessel full track
  if (sel) {
    const v = byId[sel.vessel]; const pts = (D.tracks[v?.id] || []);
    if (pts.length) {
      // solid coop path
      const dPath = pts.map((p, i) => (i ? "L" : "M") + P(p.lon, p.lat).join(" ")).join(" ");
      gDyn.append(S("path", { d: dPath, fill: "none", stroke: "#38bdf8", "stroke-width": 1.4, opacity: .5 }));
      // dashed gap segment (bridge across biggest hole)
      let hole = null, best = 0; for (let i = 1; i < pts.length; i++) { const g = pts[i].h - pts[i - 1].h; if (g > best) { best = g; hole = [pts[i - 1], pts[i]]; } }
      if (hole && best > 2) { const d2 = "M" + P(hole[0].lon, hole[0].lat).join(" ") + "L" + P(hole[1].lon, hole[1].lat).join(" "); gDyn.append(S("path", { d: d2, fill: "none", stroke: "#ff4d4f", "stroke-width": 1.6, "stroke-dasharray": "5 5" })); const mx = (hole[0].lon + hole[1].lon) / 2, my = (hole[0].lat + hole[1].lat) / 2; const [gx, gy] = P(mx, my); const t = S("text", { x: gx, y: gy - 6, fill: "#ff6b6e", "font-size": 10, "text-anchor": "middle" }); t.textContent = "AIS OFF"; gDyn.append(t); }
    }
    // highlight cable evidence
    (sel.evidence || []).forEach(ev => { if (ev.startsWith("geofence:c_")) { const cid = ev.split(":")[1]; const c = D.infra.cables.find(x => x.id === cid); if (c) { const dd = c.path.map(([lo, la], i) => (i ? "L" : "M") + P(lo, la).join(" ")).join(" "); gDyn.append(S("path", { d: dd, fill: "none", stroke: "#ff4d4f", "stroke-width": 3, opacity: .8 })); } } });
  }

  // TRIAGE: 확인 대상 소수만 스포트라이트, 나머지 홍수는 흐리게
  TRIAGE = state.triage ? triageContacts() : null;
  const flaggedSet = TRIAGE ? new Set(TRIAGE.flagged.map(f => f.v.id)) : null;
  const rankMap = {}; if (TRIAGE) TRIAGE.flagged.forEach((f, i) => rankMap[f.v.id] = i + 1);

  // vessels
  for (const v of D.vessels) {
    if (v.region !== region) continue;
    const st = stateAt(v, H); if (!st) continue;
    const [x, y] = P(st.lon, st.lat);
    const hero = HERO.has(v.id);
    const flaggedV = !TRIAGE || flaggedSet.has(v.id);
    if (TRIAGE && !flaggedV) {   // 확인 부하에서 제외된 정상 컨택트 → 흐리게
      if (st.status === "coop") coop++;
      gDyn.append(S("circle", { cx: x, cy: y, r: 1.5, fill: "#3a475e", opacity: .28 }));
      const h0 = S("circle", { cx: x, cy: y, r: 6, fill: "#000", opacity: 0, class: "clickable" }); h0.onclick = ev => { ev.stopPropagation(); selectEntity("vessel", v.id); }; gDyn.append(h0);
      continue;
    }
    const label = hero || (sel && sel.vessel === v.id) || (TRIAGE && flaggedV);
    if (st.status === "dark") {
      dark++;
      gDyn.append(S("circle", { cx: x, cy: y, r: 6.5, fill: "none", stroke: "#ff4d4f", "stroke-width": 1.6, "stroke-dasharray": "3 2", class: "sarpulse" }));
      gDyn.append(S("circle", { cx: x, cy: y, r: 2, fill: "#ff4d4f" }));
    } else {
      coop++;
      let col = "#5b7089", rr = 1.7;
      if (v.type === "fishing") { col = v.flag === "KR" ? "#3f7d5f" : "#6b7688"; }
      if (v.type === "patrol") { col = "#38bdf8"; rr = 2.4; }
      if (v.type === "tanker" || v.type === "cargo" || v.type === "bulk") { col = "#7f93b5"; rr = 2.1; }
      if (v.threat === "militia") { col = "#f5a623"; rr = 2.6; }
      if (["cable", "sts_sanctions", "sanctions_listed"].includes(v.threat)) { col = "#ff4d4f"; rr = hero ? 3 : 2.4; }
      gDyn.append(S("circle", { cx: x, cy: y, r: rr, fill: col, opacity: v.threat ? 1 : .82 }));
    }
    if (label) {
      const t = S("text", { x: x + 7, y: y + 3, fill: st.status === "dark" ? "#ff8a8f" : "#ffd0d2", "font-size": 10.5, "font-weight": 700 }); t.textContent = v.name_ko || v.name_en; gDyn.append(t);
    }
    if (state.watch.has(v.id)) { gDyn.append(S("circle", { cx: x, cy: y, r: 9, fill: "none", stroke: "#ffd43b", "stroke-width": 1.5 })); const st2 = S("text", { x: x, y: y - 11, fill: "#ffd43b", "font-size": 11, "text-anchor": "middle" }); st2.textContent = "★"; gDyn.append(st2); }
    if (state.ent && state.ent.kind === "vessel" && state.ent.id === v.id) gDyn.append(S("circle", { cx: x, cy: y, r: 11, fill: "none", stroke: "#38bdf8", "stroke-width": 1.5, "stroke-dasharray": "4 3" }));
    if (rankMap[v.id]) { gDyn.append(S("circle", { cx: x + 10, cy: y - 9, r: 7, fill: "#ff3b47", stroke: "#0a0e17", "stroke-width": 1 })); const rt = S("text", { x: x + 10, y: y - 6, fill: "#fff", "font-size": 9, "font-weight": 700, "text-anchor": "middle" }); rt.textContent = rankMap[v.id]; gDyn.append(rt); }
    const hit = S("circle", { cx: x, cy: y, r: 8, fill: "#000", opacity: 0, class: "clickable" }); hit.onclick = ev => { ev.stopPropagation(); selectEntity("vessel", v.id); }; gDyn.append(hit);
  }

  // SAR detections near current time
  for (const s of D.sar) {
    if (s.region !== region) continue; if (Math.abs(s.h - H) > 3) continue;
    const [x, y] = P(s.lon, s.lat);
    if (s.mismatch) { gDyn.append(S("rect", { x: x - 4, y: y - 4, width: 8, height: 8, fill: "none", stroke: "#ff4d4f", "stroke-width": 1.4, class: "sarpulse", transform: `rotate(45 ${x} ${y})` })); }
    else { gDyn.append(S("rect", { x: x - 2.5, y: y - 2.5, width: 5, height: 5, fill: "none", stroke: "#4a6a8a", "stroke-width": 1 })); }
  }

  // SEASENTINEL confirmation: dark vessel + nearby SAR mismatch → link
  let bannerName = null, bannerSel = null;
  for (const v of D.vessels) {
    if (v.region !== region) continue; const st = stateAt(v, H); if (!st || st.status !== "dark") continue;
    let hit = null, hd = 0.6;
    for (const s of D.sar) { if (!s.mismatch || s.region !== region || Math.abs(s.h - H) > 10) continue; const dd = Math.hypot(s.lon - st.lon, s.lat - st.lat); if (dd < hd) { hd = dd; hit = s; } }
    if (hit) { mism++; const [vx, vy] = P(st.lon, st.lat), [sx, sy] = P(hit.lon, hit.lat); gDyn.append(S("line", { x1: vx, y1: vy, x2: sx, y2: sy, stroke: "#ff4d4f", "stroke-width": 1, "stroke-dasharray": "2 2", opacity: .9 })); if (["cable", "sts_sanctions", "sanctions_listed"].includes(v.threat)) { const nm = v.name_ko || v.name_en; if (sel && sel.vessel === v.id) bannerSel = nm; else if (!bannerName) bannerName = nm; } }
  }
  bannerName = bannerSel || bannerName;

  // banner
  const banner = $(".banner");
  if (bannerName) { banner.classList.add("show"); $(".banner .txt").textContent = `위협 확정 — ${bannerName} (AIS 공백 ∩ SAR 탐지)`; }
  else banner.classList.remove("show");

  // action overlays: dispatch vectors + tasked ISR detections
  state.dispatch.filter(d => d.region === region).forEach(d => {
    const [x1, y1] = P(d.from[0], d.from[1]), [x2, y2] = P(d.to[0], d.to[1]);
    gDyn.append(S("line", { x1, y1, x2, y2, stroke: "#38bdf8", "stroke-width": 1.6, "stroke-dasharray": "6 4", class: "sarpulse" }));
    gDyn.append(S("polygon", { points: `${x2},${y2 - 5} ${x2 - 4},${y2 + 4} ${x2 + 4},${y2 + 4}`, fill: "#38bdf8" }));
    const t = S("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 4, fill: "#7fd6ff", "font-size": 9.5, "text-anchor": "middle" }); t.textContent = d.label; gDyn.append(t);
  });
  state.tasked.filter(t => t.region === region).forEach(tk => {
    const [x, y] = P(tk.lon, tk.lat);
    gDyn.append(S("rect", { x: x - 6, y: y - 6, width: 12, height: 12, fill: "none", stroke: "#38bdf8", "stroke-width": 1.6, transform: `rotate(45 ${x} ${y})`, class: "sarpulse" }));
    const t = S("text", { x: x, y: y + 16, fill: "#7fd6ff", "font-size": 9, "text-anchor": "middle" }); t.textContent = "ISR TASKED"; gDyn.append(t);
  });

  checkIntrusions();

  // KPIs
  setKPI("k-track", coop + dark); setKPI("k-dark", dark); setKPI("k-mism", mism);
  setKPI("k-alerts", D.alerts.filter(a => a.region === region).length);
}
function setKPI(id, v) { const e = document.getElementById(id); if (e) e.textContent = v; }

// ---------- alerts board ----------
function renderAlerts() {
  const box = $("#alerts"); box.innerHTML = "";
  // 실시간 구역 침범 팝업 (최상단)
  state.liveAlerts.filter(a => byId[a.vid] && byId[a.vid].region === state.region).forEach(a => {
    const node = el("div", { class: "alert live" },
      el("div", { class: "row1" },
        el("span", { class: "livetag" }, "⚠ 구역 침범"),
        el("div", { class: "meta", style: "margin-left:auto;font-family:var(--mono)" }, a.t)),
      el("div", { class: "ttl" }, `${a.name} → ${a.zoneName}`),
      el("div", { class: "meta" }, `${a.flag || ""} · 위험도 ${a.score} · 즉시 대응 요망`));
    node.onclick = () => { const al = D.alerts.find(x => x.vessel === a.vid); if (al) selectAlert(al.id); else selectEntity("vessel", a.vid); };
    box.append(node);
  });
  // TRIAGE 뷰: 확인 부하 메트릭 + 확인할 소수 랭킹
  if (state.triage) {
    const tr = triageContacts();
    box.append(el("div", { class: "triage-metric" },
      el("div", { class: "tm-top" }, el("span", {}, "확인 대상 컨택트"), el("span", { class: "tm-cut" }, `${tr.total} → ${tr.flagged.length}`)),
      el("div", { class: "tm-pct" }, `확인 부하 ${tr.pct}% ↓`),
      el("div", { class: "tm-sub" }, "레이더 증설 없이 · 이미 들어온 신호만으로 자동 우선순위")));
    if (!tr.flagged.length) box.append(el("div", { class: "alert", html: '<div class="meta">확인 대상 없음</div>' }));
    tr.flagged.forEach((f, i) => {
      const v = f.v; const al = D.alerts.find(a => a.vessel === v.id);
      const node = el("div", { class: "alert triage" + (al && state.sel === al.id ? " sel" : "") },
        el("div", { class: "row1" },
          el("span", { class: "trank" }, "#" + (i + 1)),
          el("div", { class: "score", style: `color:${f.score >= 90 ? "#ff3b47" : f.score >= 80 ? "#f5a623" : "#eab308"};margin-left:6px` }, String(f.score)),
          el("div", { class: "meta", style: "margin-left:auto" }, f.st.status === "dark" ? "DARK" : f.st.status === "sar" ? "SAR단독" : v.type)),
        el("div", { class: "ttl" }, v.name_ko || v.name_en || "미상 컨택트"),
        el("div", { class: "meta" }, `${v.flag || "-"} · 확인 사유`),
        el("div", { class: "chips" }, f.reasons.slice(0, 3).map(rr => el("span", { class: "chip warn" }, rr))));
      node.onclick = () => { if (al) selectAlert(al.id); else selectEntity("vessel", v.id); };
      box.append(node);
    });
    return;
  }
  const list = D.alerts.filter(a => a.region === state.region).sort((a, b) => b.score - a.score);
  if (!list.length && !state.liveAlerts.length) box.append(el("div", { class: "alert", html: '<div class="meta">이 해역 활성 경보 없음</div>' }));
  list.forEach(a => {
    const v = byId[a.vessel];
    const node = el("div", { class: "alert" + (state.sel === a.id ? " sel" : ""), "data-id": a.id },
      el("div", { class: "row1" },
        el("div", { class: "score", style: `color:${a.score >= 90 ? "#ff3b47" : a.score >= 80 ? "#f5a623" : "#eab308"}` }, String(a.score)),
        el("span", { class: "lvl " + a.level }, a.level),
        el("div", { class: "meta", style: "margin-left:auto" }, a.category)),
      el("div", { class: "ttl" }, a.title_ko),
      el("div", { class: "meta" }, `${v ? (v.name_ko || v.name_en) : a.vessel} · ${v ? v.flag : ""}`),
      el("div", { class: "chips" }, a.signals.map(s => el("span", { class: "chip" + (/GAP|DARK|TAMPER|ANCHOR|NO_AIS|CLUSTER/.test(s) ? " warn" : "") }, s))));
    node.onclick = () => selectAlert(a.id);
    box.append(node);
  });
}
function selectAlert(id) {
  state.sel = id; state.graphFocus = null; const a = D.alerts.find(x => x.id === id);
  if (a && a.region !== state.region) { state.region = a.region; onRegionChanged(false); }
  renderAlerts(); renderDetail(); renderGraph(); drawDynamic(); switchTab("detail");
}

// ---------- detail (kill-chain) ----------
function renderDetail() {
  const box = $("#pane-detail"); box.innerHTML = "";
  const a = state.sel ? D.alerts.find(x => x.id === state.sel) : null;
  if (!a) { box.append(el("div", { class: "meta", html: "좌측 위협 카드를 선택하면 근거·킬체인·전파 분석이 표시됩니다." })); return; }
  const v = byId[a.vessel];
  box.append(el("div", { class: "sec-t" }, "표적 · TARGET"));
  if (v) box.append(el("div", { class: "vfacts", html:
    `<div><span class="k">선명</span> <b>${v.name_ko}</b> / ${v.name_en || "-"}</div>
     <div><span class="k">기국</span> <span class="${v.flag_history && v.flag_history.length > 1 ? "warn" : ""}">${v.flag}${v.flag_history && v.flag_history.length > 1 ? " ⚠ 세탁이력 " + v.flag_history.join("→") : ""}</span></div>
     <div><span class="k">IMO/MMSI</span> ${v.imo} / ${v.mmsi}</div>
     <div><span class="k">유형·전장</span> ${v.type} · ${v.length_m}m</div>
     <div><span class="k">별칭</span> <span class="warn">${(v.aliases && v.aliases.join(", ")) || "-"}</span></div>
     <div><span class="k">소유·운영</span> ${v.owner || "-"}</div>
     ${v.note ? `<div style="margin-top:6px;color:#9fb0c8">${v.note}</div>` : ""}` }));
  box.append(el("div", { class: "sec-t" }, `판정 근거 · WHY (score ${a.score})`));
  box.append(el("ul", { class: "why" }, a.why.map(w => el("li", {}, w))));
  box.append(el("div", { class: "sec-t" }, "킬체인 타임머신 · KILL-CHAIN"));
  box.append(el("div", { class: "tl" }, a.timeline.map(([ph, t, ds]) =>
    el("div", { class: "ev" + (/접촉|피해|전파/.test(ph) ? " hot" : "") },
      el("span", { class: "ph" }, ph), el("span", { class: "tt" }, "  " + t.slice(5, 16).replace("T", " ")),
      el("div", { class: "ds" }, ds)))));
  box.append(el("div", { class: "sec-t" }, "N차 전파 · PROPAGATION"));
  const prop = el("div", { class: "prop" });
  a.propagation.forEach((p, i) => { if (i) prop.append(el("span", { class: "ar" }, "→")); prop.append(el("span", { class: "n" }, p)); });
  box.append(prop);
  box.append(el("div", { class: "sec-t" }, "근거 소스 · EVIDENCE"));
  box.append(el("div", { class: "chips" }, a.evidence.map(e => el("span", { class: "chip" }, e))));
}

// ---------- entity graph ----------
async function genGraph() {
  const focus = state.graphFocus || (state.sel ? (D.alerts.find(a => a.id === state.sel) || {}).vessel : "v_shunxin39") || "v_shunxin39";
  const v = byId[focus];
  const ctx = v ? `표적: ${v.name_ko || v.name_en} (id ${focus}). 기국 ${v.flag}${v.flag_history && v.flag_history.length > 1 ? ", 세탁이력 " + v.flag_history.join("→") : ""}. 별칭 ${(v.aliases || []).join(", ") || "없음"}. 소유 ${v.owner || "-"}. ${v.note || ""}` : `표적 id ${focus}`;
  const btn = $("#ai-graph-btn"); if (btn) { btn.disabled = true; btn.textContent = "🧠 AI 확장 중…"; }
  try {
    const res = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task: "graph", context: ctx, model: SEL_MODEL }) });
    const j = await res.json();
    if (j.ok && j.data && Array.isArray(j.data.nodes)) { state.aiGraph = { focus, nodes: j.data.nodes, edges: j.data.edges || [] }; toast(`🧠 AI 관계 ${j.data.nodes.length}개 노드 확장`); }
    else toast("AI 관계 확장 실패");
  } catch (e) { toast("AI 관계 확장 실패 (LLM 미연결)"); }
  renderGraph();
}
function renderGraph() {
  const box = $("#pane-graph"); box.innerHTML = "";
  const a = state.sel ? D.alerts.find(x => x.id === state.sel) : null;
  const focus = state.graphFocus || (a ? a.vessel : "v_shunxin39");
  const nodeMap = {}; D.graph.nodes.forEach(n => nodeMap[n.id] = n);
  let edges = D.graph.edges.filter(e => e.source === focus || e.target === focus).map(e => ({ ...e }));
  const ids = new Set([focus]); edges.forEach(e => { ids.add(e.source); ids.add(e.target); });
  const focusName = byId[focus] ? (byId[focus].name_ko || byId[focus].name_en) : focus;
  const ai = state.aiGraph && state.aiGraph.focus === focus ? state.aiGraph : null;
  if (ai) {
    ai.nodes.forEach(n => {
      if (n.id === focus) return;
      if (n.type === "vessel" && focusName && (n.label || "").includes(focusName)) return;
      if (!nodeMap[n.id]) nodeMap[n.id] = { ...n, ai: true };
      ids.add(n.id);
    });
    (ai.edges || []).forEach(e => { if (ids.has(e.source) && ids.has(e.target) && e.source !== e.target) edges.push({ ...e, ai: true }); });
    ai.nodes.forEach(n => { if (!ids.has(n.id) || n.id === focus) return; if (!edges.some(e => e.source === n.id || e.target === n.id)) edges.push({ source: focus, target: n.id, rel: "AI 가설", ai: true }); });
  }
  box.append(el("div", { class: "sec-t" }, "동일선박 해소 · ENTITY RESOLUTION"));
  const gbtn = el("button", { class: "ai-gen-btn", id: "ai-graph-btn" }, "🧠 AI 관계 확장 (LLM)"); gbtn.onclick = genGraph; box.append(gbtn);
  if (ids.size <= 1) { box.append(el("div", { class: "meta", style: "margin-top:8px" }, "확인된 관계 데이터가 없습니다. 위 버튼으로 AI 확장을 시도하세요.")); return; }
  const W = 340, Hh = 270, cx = W / 2, cy = Hh / 2;
  const svg = S("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh });
  const others = [...ids].filter(i => i !== focus);
  const pos = { [focus]: [cx, cy] };
  others.forEach((id, i) => { const ang = (i / others.length) * Math.PI * 2 - Math.PI / 2; pos[id] = [cx + Math.cos(ang) * 118, cy + Math.sin(ang) * 100]; });
  edges.forEach(e => { const p1 = pos[e.source], p2 = pos[e.target]; if (!p1 || !p2) return; svg.append(S("line", { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1], stroke: e.ai ? "#7c5cff" : "#2a3d59", "stroke-width": 1.2, "stroke-dasharray": e.ai ? "3 3" : "" })); const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2; const t = S("text", { x: mx, y: my, fill: e.ai ? "#a690ff" : "#5b7089", "font-size": 8, "text-anchor": "middle" }); t.textContent = e.rel; svg.append(t); });
  [...ids].forEach(id => {
    const n = nodeMap[id] || { label: id, type: "?" };
    const [x, y] = pos[id]; const isF = id === focus;
    const col = n.ai ? "#a78bfa" : n.type === "flag" ? "#f5a623" : n.type === "cable" ? "#4ad3c8" : n.type === "port" ? "#9fb4d0" : n.type === "org" ? "#a78bfa" : n.type === "alias" ? "#f5a623" : "#ff4d4f";
    svg.append(S("circle", { cx: x, cy: y, r: isF ? 9 : 6, fill: isF ? "#ff4d4f" : "#0d1420", stroke: col, "stroke-width": 1.6, "stroke-dasharray": n.ai ? "2 2" : "" }));
    const t = S("text", { x, y: y + (isF ? 22 : 15), fill: isF ? "#ffd0d2" : n.ai ? "#c9bcff" : "#aebdd4", "font-size": isF ? 10.5 : 9, "text-anchor": "middle", "font-weight": isF ? 700 : 400 }); t.textContent = n.label; svg.append(t);
  });
  box.append(svg);
  box.append(el("div", { class: "meta", style: "margin-top:8px", html: ai ? "<b style='color:#a78bfa'>보라색 점선</b> = LLM 추론 관계 가설(검증 필요) · 실선 = 확인된 관계." : "동일 선체가 <b style='color:#f5a623'>기국·별칭·소유</b>를 바꿔도 하나의 실체로 묶어냅니다. 위 버튼으로 AI 잠재연계 확장 가능." }));
}

// ---------- osint ----------
async function genOsint() {
  const btn = $("#ai-osint-btn"); if (btn) { btn.disabled = true; btn.textContent = "🧠 AI 분석 중…"; }
  try {
    const res = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task: "osint", context: buildCopilotContext(), model: SEL_MODEL }) });
    const j = await res.json();
    if (j.ok && Array.isArray(j.data)) { state.aiOsint = j.data.map(o => ({ ...o, ai: true, region: state.region, h: state.H })); toast(`🧠 AI OSINT 첩보 가설 ${j.data.length}건 생성`); }
    else toast("AI OSINT 생성 실패");
  } catch (e) { toast("AI OSINT 생성 실패 (LLM 미연결)"); }
  renderOsint();
}
function renderOsint() {
  const box = $("#pane-osint"); box.innerHTML = "";
  const aiBtn = el("button", { class: "ai-gen-btn", id: "ai-osint-btn" }, "🧠 AI OSINT 첩보 가설 생성"); aiBtn.onclick = genOsint;
  box.append(aiBtn);
  const ai = state.aiOsint.filter(o => o.region === state.region);
  if (ai.length) {
    box.append(el("div", { class: "sec-t" }, `AI 추론 첩보 (검증 필요) · ${ai.length}건`));
    ai.forEach(o => box.append(el("div", { class: "osint aiitem" },
      el("div", { class: "oh" }, el("span", { class: "badge ai" }, "AI " + (o.kind || "")), el("span", {}, fmtH(o.h)),
        el("span", { class: "sent", style: `color:${(o.sentiment || 0) < -0.4 ? "#ff6b6e" : "#f5a623"}` }, `sig ${o.weight ?? "-"}`)),
      el("div", { class: "ot" }, o.text),
      el("div", { class: "oh", style: "margin-top:4px" }, el("span", {}, "▸ " + (o.source || "AI 추정") + " · LLM 생성")))));
  }
  const list = D.osint.filter(o => o.region === state.region).sort((a, b) => b.h - a.h);
  box.append(el("div", { class: "sec-t" }, `OSINT 융합 피드 · ${list.length}건`));
  list.forEach(o => {
    const warn = o.weight >= 0.6;
    box.append(el("div", { class: "osint" },
      el("div", { class: "oh" },
        el("span", { class: "badge " + (warn ? "warn" : "k") }, o.kind),
        el("span", {}, fmtH(o.h)),
        el("span", { class: "sent", style: `color:${o.sentiment < -0.4 ? "#ff6b6e" : o.sentiment < 0 ? "#f5a623" : "#5b7089"}` }, o.sentiment ? `sig ${o.weight}` : "routine")),
      el("div", { class: "ot" }, o.text),
      el("div", { class: "oh", style: "margin-top:4px" }, el("span", {}, "▸ " + o.source))));
  });
}

// ---------- copilot ----------
const PRESETS = [
  "지난 24시간 해저케이블 인근 다크선박 있나?",
  "부산 입항 예정 선박 중 최고위험 표적은?",
  "제재회피 STS 환적 정황을 요약해줘",
  "이 해역에서 지금 가장 위험한 표적 3개는?",
];
function copilotAnswer(q) {
  const region = state.region; const A = D.alerts.filter(a => a.region === region).sort((a, b) => b.score - a.score);
  const brief = a => { const v = byId[a.vessel]; return `▸ [${a.score}/${a.level}] ${a.title_ko}\n   선박: ${v ? v.name_ko : a.vessel} (${v ? v.flag : ""})\n   근거: ${a.why[0]}\n   전파: ${a.propagation.join(" → ")}`; };
  let body, cites;
  if (/케이블|cable|해저/.test(q)) { const hits = A.filter(a => a.category === "critical_infrastructure"); body = hits.length ? `해저케이블 위협 표적 ${hits.length}건 탐지:\n\n` + hits.map(brief).join("\n\n") : "현재 해역에 케이블 위협 경보 없음."; cites = "MSMT·아산 이슈브리프 2025-15·핀란드 케이블 수사"; }
  else if (/부산|입항|port|busan/.test(q)) { const h = A.find(a => (a.evidence || []).some(e => e.includes("o9")) || a.vessel === "v_shunxin39"); body = h ? brief(h) + `\n\n⚠ 부산 입항 신고 접수 — 직전 항적에 TPE 케이블 저속 배회. KT 공동소유 회선 위험.` : "부산 입항 관련 고위험 표적 없음."; cites = "항만 입출항 데이터·동아일보 2025.1.7"; }
  else if (/제재|sts|환적|sanction/.test(q)) { const h = A.filter(a => a.category === "sanctions_evasion"); body = h.length ? h.map(brief).join("\n\n") : "제재회피 정황 경보 없음."; cites = "MSMT 2025-10·RFA 대북제재 보도"; }
  else if (/위험|top|3|가장/.test(q)) { body = A.slice(0, 3).map(brief).join("\n\n"); cites = "SEASENTINEL 엔진 위험도 스코어링"; }
  else { const h = A.find(a => q && (a.title_ko.includes(q.slice(0, 2)) || (byId[a.vessel] && (byId[a.vessel].name_ko || "").includes(q.slice(0, 2))))); body = h ? brief(h) : "질의를 위협보드/OSINT와 대조했으나 직접 매칭 없음. 현재 최고위험 표적:\n\n" + brief(A[0]); cites = "SEASENTINEL 융합 데이터"; }
  return { body, cites };
}
function buildCopilotContext() {
  const region = D.regions[state.region].name_ko;
  const alerts = D.alerts.filter(a => a.region === state.region).sort((a, b) => b.score - a.score);
  const al = alerts.map(a => { const v = byId[a.vessel]; return `- [위험도 ${a.score}/${a.level}] ${a.title_ko} | 선박:${v ? v.name_ko : a.vessel}(${v ? v.flag : ""})${v && v.flag_history && v.flag_history.length > 1 ? " 기국세탁 " + v.flag_history.join("→") : ""} | 시그널:${a.signals.join(",")} | 근거:${a.why.join("; ")} | N차전파:${a.propagation.join("→")}`; }).join("\n");
  const osint = D.osint.filter(o => o.region === state.region && o.weight >= 0.5).sort((a, b) => b.h - a.h).slice(0, 8).map(o => `- (${o.kind}) ${o.text} [출처 ${o.source}]`).join("\n");
  const ent = state.ent ? (() => { const m = entityModel(state.ent.kind, state.ent.id); return `\n\n[지휘관이 현재 선택한 객체] ${m.title} — ${m.sub}${m.note ? " · " + m.note : ""}`; })() : "";
  const kpi = `추적 ${$("#k-track").textContent}척 · 다크선박(AIS off) ${$("#k-dark").textContent} · 위협확정 ${$("#k-mism").textContent} · 활성경보 ${$("#k-alerts").textContent}`;
  const watch = state.watch.size ? `\n관심표적: ${[...state.watch].map(id => byId[id] ? byId[id].name_ko : id).join(", ")}` : "";
  return `해역: ${region}\n시각: T+${state.H}h (${fmtH(state.H)}) · 시나리오 앵커 2026-06-24 연평도\n상황판: ${kpi}${watch}\n\n[활성 위협 경보]\n${al || "없음"}\n\n[OSINT 주요 신호]\n${osint || "없음"}${ent}`;
}

async function runCopilot(q) {
  const out = $("#cp-out"); out.innerHTML = "";
  const ans = el("div", { class: "cp-ans" },
    el("div", { class: "q" }, "Q. " + q),
    el("div", { class: "cp-badge", id: "cp-badge" }, "● LLM 연결 중…"),
    el("div", { class: "cp-text", id: "cp-text" }, ""));
  out.append(ans);
  const textNode = $("#cp-text"), badge = $("#cp-badge");
  const ctx = buildCopilotContext();
  const ctrl = new AbortController(); const to = setTimeout(() => ctrl.abort(), 60000);
  try {
    const res = await fetch("/api/copilot", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, context: ctx, model: SEL_MODEL }), signal: ctrl.signal });
    if (!res.ok || !res.body) throw new Error("http " + res.status);
    badge.textContent = "● 실시간 LLM";
    const reader = res.body.getReader(); const dec = new TextDecoder();
    let buf = "", acc = "", model = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        try { const j = JSON.parse(data); model = j.model || model; const d = j.choices && j.choices[0] && j.choices[0].delta && j.choices[0].delta.content; if (d) { acc += d; textNode.textContent = acc; out.scrollTop = out.scrollHeight; } } catch (e) { }
      }
    }
    clearTimeout(to);
    if (!acc.trim()) throw new Error("empty");
    badge.textContent = "● 실시간 LLM · " + (model || CFG_MODEL);
    badge.classList.add("live");
  } catch (e) {
    clearTimeout(to);
    const { body, cites } = copilotAnswer(q);
    badge.textContent = "● 오프라인 규칙기반 (LLM 미연결)"; badge.classList.add("offline");
    textNode.textContent = body + "\n\n— 출처: " + cites;
  }
}

// ---------- tabs / region / time ----------
function switchTab(t) { state.tab = t; document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t)); document.querySelectorAll(".tabpane").forEach(p => p.classList.toggle("on", p.id === "pane-" + t)); }
function onRegionChanged(reset = true) {
  state.ent = null; state.graphFocus = null; state.zoneMem = {}; state.liveAlerts = []; state.zoneReady = false; state.aiGraph = null; state.aiOsint = []; const ec = $("#entcard"); if (ec) ec.classList.remove("show");
  document.querySelectorAll(".region-tog button").forEach(b => b.classList.toggle("on", b.dataset.r === state.region));
  $("#regionName").textContent = D.regions[state.region].name_ko;
  $("#theatre").textContent = D.regions[state.region].theatre;
  buildProjection(); drawStatic(); drawDynamic(); renderAlerts(); renderOsint(); renderGraph();
  if (reset) { state.sel = null; renderDetail(); }
}
function setH(h) { state.H = Math.max(0, Math.min(WINDOW_H, h)); $("#scrub").value = state.H; $("#tlabel").innerHTML = `T+<span class="h">${state.H.toFixed(0)}</span>h · ${fmtH(state.H)}`; drawDynamic(); }
let playIv = null;
function togglePlay() {
  state.playing = !state.playing; const b = $("#play"); b.textContent = state.playing ? "❚❚" : "▶"; b.classList.toggle("on", state.playing);
  if (state.playing) { playIv = setInterval(() => { let n = +(state.H + 0.2 * state.speed).toFixed(2); if (n > WINDOW_H) n = 0; setH(n); }, 220); }
  else clearInterval(playIv);
}
function cycleSpeed() { state.speed = SPEEDS[(SPEEDS.indexOf(state.speed) + 1) % SPEEDS.length]; const b = $("#speed"); if (b) b.textContent = state.speed + "×"; }

// ---------- entity selection + Palantir-style actions ----------
function getVesselPos(id, H) { const v = byId[id]; if (!v) return null; const st = stateAt(v, H); return st ? [st.lon, st.lat] : null; }
function nearestPatrol(lon, lat, region) {
  let best = null, bd = 1e9;
  for (const v of D.vessels) { if (v.region !== region || v.type !== "patrol") continue; const st = stateAt(v, state.H); if (!st) continue; const d = Math.hypot(st.lon - lon, st.lat - lat); if (d < bd) { bd = d; best = { v, pos: [st.lon, st.lat], d }; } }
  return best;
}
function entityModel(kind, id) {
  if (kind === "vessel") { const v = byId[id]; const al = D.alerts.find(a => a.vessel === id); return { kind, id, title: v.name_ko || v.name_en, sub: `${v.type} · ${v.flag}`, threat: v.threat, alert: al, facts: [["기국", v.flag + (v.flag_history && v.flag_history.length > 1 ? ` ⚠${v.flag_history.join("→")}` : "")], ["IMO/MMSI", `${v.imo} / ${v.mmsi}`], ["전장", v.length_m + "m"], ["별칭", (v.aliases && v.aliases.join(", ")) || "-"], ["소유", v.owner || "-"]], note: v.note }; }
  if (kind === "structure") { const s = D.infra.structures.find(x => x.id === id); return { kind, id, title: s.name_ko, sub: `${s.kind} · 설치 ${s.installed}`, threat: "structure", facts: [["규모", s.dims], ["설치", s.installed], ["식별", s.detected || "-"]], note: s.note }; }
  if (kind === "cable") { const c = D.infra.cables.find(x => x.id === id); return { kind, id, title: c.name, sub: `해저케이블 · ${c.criticality}`, threat: "cable", facts: [["소유", c.owners.join(", ")], ["중요도", c.criticality]], note: c.note }; }
  const p = D.infra.ports.find(x => x.id === id); return { kind, id, title: p.name_ko, sub: `항만 · ${p.country}`, threat: "port", facts: [["국가", p.country]], note: p.note };
}
function selectEntity(kind, id) { state.ent = { kind, id }; renderEntityCard(); drawDynamic(); }
function closeEntity() { state.ent = null; $("#entcard").classList.remove("show"); drawDynamic(); }

const ACTIONS = [
  { k: "watch", ic: "🎯", label: "관심표적 지정", kinds: ["vessel", "structure"] },
  { k: "isr", ic: "🛰️", label: "ISR 재촬영 요청", kinds: ["vessel", "structure", "cable"] },
  { k: "vector", ic: "🚨", label: "경비함 유도·차단", kinds: ["vessel", "structure"] },
  { k: "dossier", ic: "📦", label: "채증 패키지 생성", kinds: ["vessel", "structure", "cable"] },
  { k: "graph", ic: "🔗", label: "관계 확장", kinds: ["vessel"] },
  { k: "brief", ic: "🧠", label: "AI 브리핑", kinds: ["vessel", "structure", "cable"] },
  { k: "escalate", ic: "⬆️", label: "지휘보고·경보상향", kinds: ["vessel", "structure", "cable", "port"] },
];

function renderEntityCard() {
  const m = entityModel(state.ent.kind, state.ent.id); const card = $("#entcard"); card.classList.add("show");
  const tcol = ["cable", "sts_sanctions", "sanctions_listed", "infiltration"].includes(m.threat) ? "#ff4d4f" : m.threat === "militia" || m.threat === "structure" ? "#f5a623" : "#38bdf8";
  card.innerHTML = "";
  const hd = el("div", { class: "ec-hd" }, el("div", { class: "ec-ttl" }, el("span", { class: "ec-dot", style: `background:${tcol}` }), el("b", {}, m.title)), el("button", { class: "ec-x" }, "✕"));
  hd.querySelector(".ec-x").onclick = closeEntity; card.append(hd);
  card.append(el("div", { class: "ec-sub" }, m.sub));
  card.append(el("div", { class: "ec-facts" }, m.facts.map(([k, v]) => el("div", {}, el("span", { class: "k" }, k), document.createTextNode(v)))));
  if (m.note) card.append(el("div", { class: "ec-note" }, m.note));
  if (m.alert) { const a = el("div", { class: "ec-alertlink" }, `⚠ 연계 경보: ${m.alert.title_ko} (${m.alert.score})`); a.onclick = () => selectAlert(m.alert.id); card.append(a); }
  card.append(el("div", { class: "ec-actt" }, "실행 · ACTIONS"));
  const acts = el("div", { class: "ec-acts" });
  ACTIONS.filter(a => a.kinds.includes(m.kind)).forEach(a => { const b = el("button", { class: "ec-act" + (a.k === "watch" && state.watch.has(m.id) ? " on" : "") }, `${a.ic} ${a.label}`); b.onclick = () => runAction(a.k, m); acts.append(b); });
  card.append(acts);
  const hist = state.log.filter(l => l.eid === m.id);
  if (hist.length) { card.append(el("div", { class: "ec-actt" }, "조치 이력")); card.append(el("div", { class: "ec-hist" }, hist.slice(-4).reverse().map(l => el("div", {}, el("span", { class: "t" }, l.t + " "), document.createTextNode(l.msg))))); }
}

function logAction(eid, msg) { state.log.push({ eid, t: fmtH(state.H).slice(6), msg }); renderActionLog(); }
function renderActionLog() { const box = $("#log-body"); if (!box) return; box.innerHTML = ""; state.log.slice(-8).reverse().forEach(l => box.append(el("div", { class: "logrow" }, el("span", { class: "lt" }, l.t), document.createTextNode(l.msg)))); $("#log-count").textContent = state.log.length; $("#actionlog").classList.toggle("show", state.log.length > 0); }

function runAction(k, m) {
  const H = state.H, region = state.region;
  if (k === "watch") { state.watch.add(m.id); toast(`🎯 관심표적 지정 — ${m.title}`); logAction(m.id, `관심표적 지정: ${m.title}`); renderEntityCard(); drawDynamic(); }
  else if (k === "isr") {
    const pos = m.kind === "vessel" ? getVesselPos(m.id, H) : (m.kind === "structure" ? D.infra.structures.find(s => s.id === m.id).lonlat : D.infra.cables.find(c => c.id === m.id).path[1]);
    toast(`🛰️ ISR 재촬영 지시 — 상용 SAR 위성 태스킹…`); logAction(m.id, `ISR 재촬영 요청: ${m.title}`);
    setTimeout(() => { if (pos) state.tasked.push({ lon: pos[0], lat: pos[1], region, label: m.title }); toast(`🛰️ ISR 재촬영 완료 — SAR 신규 탐지 (신뢰도 0.88)`); logAction(m.id, `ISR 결과: SAR 신규 탐지 획득`); drawDynamic(); if (state.ent) renderEntityCard(); }, 1100);
  }
  else if (k === "vector") {
    const pos = m.kind === "vessel" ? getVesselPos(m.id, H) : D.infra.structures.find(s => s.id === m.id).lonlat;
    if (!pos) { toast("대상 위치 확인 불가"); return; }
    const np = nearestPatrol(pos[0], pos[1], region);
    if (np) { const nm = Math.round(np.d * 60); state.dispatch.push({ from: np.pos, to: pos, region, label: `${np.v.name_ko} 유도` }); toast(`🚨 경비함 유도 — ${np.v.name_ko} → 대상 (약 ${nm}해리)`); logAction(m.id, `경비함 유도: ${np.v.name_ko} (${nm}해리)`); }
    else { toast(`🚨 인접 경비함 없음 — 위성·항공 ISR 대체 권고`); logAction(m.id, `유도 불가: 인접 자산 없음 → ISR 대체`); }
    drawDynamic();
  }
  else if (k === "dossier") { openDossier(m); logAction(m.id, `채증 패키지 생성: ${m.title}`); }
  else if (k === "graph") { const al = D.alerts.find(a => a.vessel === m.id); if (al) { state.sel = al.id; renderAlerts(); renderDetail(); } state.graphFocus = m.id; switchTab("graph"); renderGraph(); toast("🔗 관계 그래프 확장"); }
  else if (k === "brief") { switchTab("copilot"); logAction(m.id, `AI 브리핑 요청: ${m.title}`); runCopilot(`선택 표적 "${m.title}"을(를) 정밀 평가하고, 위협 근거·우선순위·권고 조치를 지휘관용으로 브리핑해줘.`); }
  else if (k === "escalate") { toast(`⬆️ 지휘보고 전송 — ${m.title} · 경보 상향`); logAction(m.id, `지휘보고·경보상향: ${m.title}`); }
}

function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }

function openDossier(m) {
  const modal = $("#dossier"); const a = m.alert;
  const rows = m.facts.map(([k, v]) => `<div><span class="dk">${k}</span> ${v}</div>`).join("");
  const why = a ? `<div class="ds-sec">판정 근거</div><ul>${a.why.map(w => `<li>${w}</li>`).join("")}</ul>` : "";
  const tl = a ? `<div class="ds-sec">킬체인 타임라인</div>` + a.timeline.map(([p, t, d]) => `<div class="ds-tl"><b>${p}</b> <span>${t.slice(5, 16).replace("T", " ")}</span> — ${d}</div>`).join("") : "";
  const sig = a ? `<div class="ds-sec">탐지 시그널</div><div class="ds-chips">${a.signals.map(s => `<span>${s}</span>`).join("")}</div>` : "";
  const src = `<div class="ds-sec">근거 소스 (court-ready)</div><div class="ds-src">AIS 원항적 · SAR 미매칭 탐지 · 선박등록부(GISIS) · OSINT 융합 · 국방통계연보/해경 집계</div>`;
  modal.innerHTML = `<div class="ds-card">
    <div class="ds-hd"><div><div class="ds-badge">채증 패키지 · EVIDENCE DOSSIER</div><h2>${m.title}</h2><div class="ds-sub">${m.sub}${a ? ` · 위험도 ${a.score}/${a.level}` : ""}</div></div><button class="ds-x">✕</button></div>
    <div class="ds-body"><div class="ds-facts">${rows}</div>${m.note ? `<div class="ds-note">${m.note}</div>` : ""}${why}${tl}${sig}${src}</div>
    <div class="ds-ft"><span>생성 ${fmtH(state.H)} · SEASENTINEL 엔진 · 무결성 해시 0x${(m.id.length * 48271 % 65536).toString(16).padStart(4, "0")}…</span><div><button class="ds-dl">⬇ PDF 내보내기</button><button class="ds-close">닫기</button></div></div>
  </div>`;
  modal.classList.add("show");
  modal.querySelector(".ds-x").onclick = modal.querySelector(".ds-close").onclick = () => modal.classList.remove("show");
  modal.querySelector(".ds-dl").onclick = () => toast("⬇ 채증 패키지 PDF 내보내기 (데모)");
  modal.onclick = e => { if (e.target === modal) modal.classList.remove("show"); };
}

function openPipeline() {
  const modal = $("#dossier");
  modal.innerHTML = `<div class="ds-card">
    <div class="ds-hd"><div><div class="ds-badge">시스템 파이프라인 · SOURCES & MODELS</div><h2>SEASENTINEL 처리 파이프라인</h2><div class="ds-sub">협조신호 ⊕ 비협조탐지 → 융합 → 이상탐지 → 동일선박 해소 → 결심지원</div></div><button class="ds-x">✕</button></div>
    <div class="ds-body">
      <div class="ds-sec">데이터 소스 · DATA SOURCES</div>
      <div class="ds-facts">
        <div><span class="dk">AIS(협조)</span> Global Fishing Watch API · MarineCadastre(USCG) · 해수부 V-Pass · Spire 위성AIS</div>
        <div><span class="dk">비협조 탐지</span> Sentinel-1 SAR (Copernicus, 무료) · ICEYE / Capella SAR · HawkEye 360 RF</div>
        <div><span class="dk">선박 신원</span> IMO GISIS 선박등록부 · Equasis · 제재 리스트(UN 1718 / OFAC)</div>
        <div><span class="dk">OSINT</span> 뉴스·SNS·지역포럼 · 항만 입출항/물류 · 상용 위성 변화탐지</div>
        <div><span class="dk">지도/지형</span> Natural Earth 해안선 · 해저케이블 경로(TeleGeography)</div>
      </div>
      <div class="ds-sec">모델 · 알고리즘 · MODELS</div>
      <div class="ds-facts">
        <div><span class="dk">항적 예측</span> TrAISformer (Transformer, arXiv:2109.03958) — 예측 이탈 = 이상</div>
        <div><span class="dk">이상 탐지</span> 규칙엔진(AIS 갭·지오펜스·다크 STS) + LSTM Autoencoder</div>
        <div><span class="dk">센서 퓨전</span> SAR ↔ AIS 시공간 상관 매칭 (미매칭 = 다크선박)</div>
        <div><span class="dk">동일선박 해소</span> IMO·항적·관계 기반 그래프 Entity Resolution (flag-hopping 대응)</div>
        <div><span class="dk">위험도</span> 다신호 가중 스코어링 (0–100)</div>
        <div><span class="dk">결심 지원</span> LLM 코파일럿 (RAG + tool-calling, 출처 인용)</div>
      </div>
      <div class="ds-note">이 데모는 위 파이프라인 구조를 그대로 반영하되, 무대 오프라인·재현성을 위해 실제 검증 사건
      (순싱39호·Eagle S·덕성호·후이신·Yi Peng 3·서해 PMZ 구조물 등)의 좌표·선명·수법을 반영한
      <b>합성 재구성 데이터셋(696척)</b>으로 구동됩니다. 운영 전환 시 위 실데이터 소스로 그대로 대체됩니다.</div>
      <div class="ds-sec">근거 리서치 · PROVENANCE</div>
      <div class="ds-src">국방통계연보 2024(북한 해상도발) · 해양경찰청 중국어선 출몰/나포 집계 · MSMT 대북제재 STS 보고(2025-10) · 아산정책연구원 이슈브리프 2025-13/15 · 핀란드·스웨덴 케이블 사보타주 수사</div>
    </div>
    <div class="ds-ft"><span>SEASENTINEL v0.1 · D4D T4 · 오프라인 데모</span><div><button class="ds-close">닫기</button></div></div>
  </div>`;
  modal.classList.add("show");
  modal.querySelector(".ds-x").onclick = modal.querySelector(".ds-close").onclick = () => modal.classList.remove("show");
  modal.onclick = e => { if (e.target === modal) modal.classList.remove("show"); };
}

// ---------- boot ----------
async function boot() {
  await loadAll();
  fetch("/api/health").then(r => r.json()).then(h => { if (h && h.model) CFG_MODEL = h.model; }).catch(() => { });
  fetch("/api/models").then(r => r.json()).then(m => {
    const sel = $("#cp-model"); if (!sel || !m.models) return;
    SEL_MODEL = m.default || m.models[0];
    m.models.forEach(id => { const o = el("option", { value: id }, id); if (id === SEL_MODEL) o.selected = true; sel.append(o); });
    sel.onchange = () => { SEL_MODEL = sel.value; CFG_MODEL = sel.value; toast("LLM 모델 → " + sel.value); };
  }).catch(() => { });
  // KPIs meta
  $("#meta-line").innerHTML = `추적 선박 <b>${D.meta.counts.vessels}</b> · AIS <b>${D.meta.counts.ais_points.toLocaleString()}</b> · SAR <b>${D.meta.counts.sar_detections}</b>(미매칭 ${D.meta.counts.sar_mismatch}) · OSINT <b>${D.meta.counts.osint}</b>`;
  // region toggle
  document.querySelectorAll(".region-tog button").forEach(b => b.onclick = () => { state.region = b.dataset.r; onRegionChanged(true); });
  // tabs
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  // time
  $("#scrub").max = WINDOW_H;
  $("#scrub").oninput = e => { if (state.playing) togglePlay(); setH(+e.target.value); };
  $("#play").onclick = togglePlay;
  $("#speed").onclick = cycleSpeed;
  $("#triage-tog").onclick = () => { state.triage = !state.triage; $("#triage-tog").classList.toggle("on", state.triage); drawDynamic(); renderAlerts(); toast(state.triage ? "⚡ TRIAGE 켜짐 — 확인할 소수만 스포트라이트" : "TRIAGE 꺼짐 — 전체 컨택트 표시"); };
  // copilot
  const presetBox = $("#cp-presets"); PRESETS.forEach(p => { const b = el("button", {}, p); b.onclick = () => { $("#cp-q").value = p; runCopilot(p); }; presetBox.append(b); });
  $("#cp-send").onclick = () => { const q = $("#cp-q").value.trim(); if (q) runCopilot(q); };
  $("#cp-q").onkeydown = e => { if (e.key === "Enter") { const q = e.target.value.trim(); if (q) runCopilot(q); } };
  window.addEventListener("resize", () => { buildProjection(); drawStatic(); drawDynamic(); });
  // zoom / pan
  const mw = $(".mapwrap"), svg = $("svg.map");
  mw.addEventListener("wheel", e => { e.preventDefault(); const r = mw.getBoundingClientRect(); zoomBy(e.deltaY < 0 ? 0.85 : 1 / 0.85, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height); }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", e => { if (e.target.classList && e.target.classList.contains("clickable")) return; drag = { sx: e.clientX, sy: e.clientY, vx: VIEW.x, vy: VIEW.y }; svg.style.cursor = "grabbing"; });
  window.addEventListener("pointermove", e => { if (!drag) return; const r = mw.getBoundingClientRect(); VIEW.x = drag.vx - (e.clientX - drag.sx) / r.width * VIEW.w; VIEW.y = drag.vy - (e.clientY - drag.sy) / r.height * VIEW.h; clampView(); applyView(); });
  window.addEventListener("pointerup", () => { if (drag) { drag = null; svg.style.cursor = ""; } });
  $("#zin").onclick = () => zoomBy(0.7); $("#zout").onclick = () => zoomBy(1 / 0.7); $("#zreset").onclick = () => resetView();
  $("#pipeline-btn").onclick = openPipeline;
  onRegionChanged(true); setH(state.H); switchTab("detail");
  renderActionLog();
  if (D.alerts && D.alerts[0]) selectAlert(D.alerts[0].id);
  runCopilot(PRESETS[0]);
}
boot();
