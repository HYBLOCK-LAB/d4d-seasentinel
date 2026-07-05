import { useCallback, useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import type * as GeoJSON from 'geojson'
import { useAppState, useAppDispatch, useRegion, useSettings } from '../state/AppState'
import { api } from '../api/client'
import { mapAlive, useMap } from '../map/MapView'
import { COLORS, LAYER_DEFS } from './registry'
import type { LayerDef } from './registry'
import type { Changes, FeatureCollection, LayerId, Threat, TimeWindow } from '../api/types'

const sourceId = (id: LayerId): string => `mda-${id}`

// Ports render near-white by default; on the light basemap they must be dark to
// stay visible. Kept as a module var so the async layer styler reads the theme
// current at add-time, and the theme effect repaints an existing layer.
const PORT_COLOR_LIGHT = '#0b1220'
let portFill: string = COLORS.bright
const AIS_LAYER_IDS = new Set<LayerId>(['ais_points', 'tracks'])
const HIGHLIGHT_SOURCE = 'ontology-highlight'
const HIGHLIGHT_LAYERS = [
  `${HIGHLIGHT_SOURCE}-fill`,
  `${HIGHLIGHT_SOURCE}-line`,
  `${HIGHLIGHT_SOURCE}-point`,
]

const layerIdsOf = (id: LayerId): string[] =>
  id === 'alerts_geo'
    ? [`${sourceId(id)}-halo`, `${sourceId(id)}-core`]
    : id === 'zones'
      ? [
          `${sourceId(id)}-gray-fill`,
          `${sourceId(id)}-gray-outline`,
          `${sourceId(id)}-eez`,
          `${sourceId(id)}-outline`,
        ]
      : [sourceId(id)]

const CLICKABLE = LAYER_DEFS.flatMap((d) =>
  d.id === 'alerts_geo' ? [`${sourceId(d.id)}-core`] : layerIdsOf(d.id),
)

function esc(value: unknown): string {
  return String(value ?? '·')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

interface PopupSpec {
  title: string
  color: string
  rows: Array<[string, unknown]>
  table: string
  srcId?: string
  note?: string
  zoneThreat?: { enabled: boolean; zoneId?: string }
}

function popupSpec(layerId: LayerId, p: Record<string, unknown>): PopupSpec {
  switch (layerId) {
    case 'ais_points':
      return {
        title: 'AIS 선박',
        color: COLORS.accent,
        rows: [
          ['MMSI', p.mmsi],
          ['선명', p.name],
          ['VESSEL', p.vessel_id],
          ['시각', typeof p.ts === 'string' ? `${p.ts.slice(0, 16)}Z` : p.ts],
          ['SOG', p.sog != null ? `${p.sog} kn` : null],
          ['COG', p.cog != null ? `${p.cog}°` : null],
        ],
        table: 'ais_position',
        srcId: p.vessel_id ? String(p.vessel_id) : undefined,
      }
    case 'tracks':
      return {
        title: '항적',
        color: COLORS.accent,
        rows: [
          ['VESSEL', p.vessel_id],
          ['위치 수', p.n],
        ],
        table: 'ais_position',
        srcId: p.vessel_id ? String(p.vessel_id) : undefined,
      }
    case 'sar':
      return {
        title: '위성 탐지(SAR)',
        color: COLORS.sat,
        rows: [
          ['센서', p.sensor],
          ['신뢰도', typeof p.confidence === 'number' ? p.confidence.toFixed(2) : p.confidence],
          ['추정 길이', p.length_est_m != null ? `${p.length_est_m} m` : null],
          ['AIS 매칭', p.matched ? `있음 (${p.vessel_id ?? '·'})` : '없음 (다크)'],
          ['시각', typeof p.ts === 'string' ? `${p.ts.slice(0, 16)}Z` : p.ts],
        ],
        table: 'sar_detection',
        srcId: p.detection_id ? String(p.detection_id) : undefined,
      }
    case 'alerts_geo':
      return {
        title: '위협 경보',
        color: COLORS.crit,
        rows: [
          ['제목', p.title_ko],
          ['유형', p.alert_type],
          ['레벨', p.level],
          ['점수', p.score],
        ],
        table: 'alert',
        srcId: p.alert_id ? String(p.alert_id) : undefined,
      }
    case 'events':
      return {
        title: '수집 사건',
        color: COLORS.warn,
        rows: [
          ['사건', p.name],
          ['유형', p.event_type],
          ['일자', p.event_date],
        ],
        table: 'event',
        note: typeof p.description === 'string' ? p.description.slice(0, 160) : undefined,
      }
    case 'gfw_events':
      return {
        title: '과거 선박 이벤트 (GFW)',
        color: COLORS.dim,
        rows: [
          ['유형', p.event_type],
          ['선박', p.name],
          ['일자', p.event_date],
        ],
        table: 'event',
      }
    case 'zones':
      return {
        title: '구역',
        color: p.kind === 'gray_zone' ? COLORS.warn : COLORS.steel,
        rows: [
          ['명칭', p.name],
          ['종류', p.kind],
          ['ZONE', p.zone_id ?? p.id],
        ],
        table: 'zone',
        srcId: p.zone_id ? String(p.zone_id) : p.id ? String(p.id) : undefined,
        zoneThreat: {
          enabled: p.kind === 'gray_zone',
          zoneId: p.zone_id ? String(p.zone_id) : p.id ? String(p.id) : p.aoi_id ? String(p.aoi_id) : undefined,
        },
      }
    case 'cables':
      return { title: '해저케이블', color: COLORS.steel, rows: [['명칭', p.name]], table: 'zone' }
    case 'ports':
      return {
        title: '항만',
        color: COLORS.steel,
        rows: [
          ['명칭', p.name],
          ['국가', p.country],
        ],
        table: 'facility',
      }
  }
}

function buildHtml(spec: PopupSpec): string {
  const rows = spec.rows
    .filter(([, v]) => v != null && v !== '')
    .map(
      ([label, value]) =>
        `<div style="display:flex;gap:8px;align-items:baseline">
          <span style="font-size:10px;letter-spacing:.08em;color:#5b6b85;min-width:34px">${esc(label)}</span>
          <span class="mono" style="font-size:11px">${esc(value)}</span>
        </div>`,
    )
    .join('')
  const note = spec.note
    ? `<div style="font-size:11px;color:#8fa3bd;line-height:1.5;margin-top:4px">${esc(spec.note)}</div>`
    : ''
  const zoneThreat = spec.zoneThreat?.enabled
    ? `<button data-action="zone-threat" style="font-size:11px;color:#f5a623;background:rgba(245,166,35,.14);border:1px solid rgba(245,166,35,.42);border-radius:2px;padding:2px 8px;cursor:pointer;margin-top:6px;align-self:flex-start">위협 분석</button>
       <span data-role="zone-status" style="font-size:10px;color:#8fa3bd;margin-top:2px"></span>`
    : ''
  return `<div style="display:flex;flex-direction:column;gap:2px">
    <div style="font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:${spec.color};margin-bottom:2px">${esc(spec.title)}</div>
    ${rows}${note}
    <button data-action="ontology" style="font-size:11px;color:#35e0c2;background:rgba(53,224,194,.14);border:1px solid rgba(53,224,194,.4);border-radius:2px;padding:2px 8px;cursor:pointer;margin-top:6px;align-self:flex-start">온톨로지 원본 보기</button>
    ${zoneThreat}
  </div>`
}

function renderedLayerToLayerId(renderedId: string): LayerId {
  if (renderedId.startsWith(`${sourceId('zones')}-`)) return 'zones'
  if (renderedId.startsWith(`${sourceId('alerts_geo')}-`)) return 'alerts_geo'
  return renderedId.replace(/^mda-/, '') as LayerId
}

function inWindow(prop: string, startMs: number, endMs: number): unknown[] {
  const v = ['coalesce', ['get', prop], 0]
  return ['all', ['>=', v, startMs], ['<=', v, endMs]]
}

// In-window features keep their alert colors; anything outside the selected
// window (before or after) collapses to small dim-gray context dots.
function applyWindowPaint(map: maplibregl.Map, window: TimeWindow): void {
  const s = new Date(window.start).getTime()
  const e = new Date(window.end).getTime()
  const set = (layer: string, prop: string, value: unknown): void => {
    if (map.getLayer(layer)) map.setPaintProperty(layer, prop, value as never)
  }
  const aisIn = inWindow('ts_ms', s, e)
  const ais = sourceId('ais_points')
  set(ais, 'circle-color', ['case', aisIn, COLORS.accent, COLORS.dim])
  // A zoom "interpolate" curve requires constant stop outputs, so the in/out
  // choice must wrap the whole curve (case -> interpolate), not sit inside the
  // stops — otherwise setPaintProperty is rejected and the base big radius
  // sticks, producing big gray dots for out-of-window fixes.
  set(ais, 'circle-radius', [
    'case',
    aisIn,
    ['interpolate', ['linear'], ['zoom'], 4, 2.5, 8, 4, 12, 6],
    ['interpolate', ['linear'], ['zoom'], 4, 1.4, 8, 2, 12, 3],
  ])
  set(ais, 'circle-opacity', ['case', aisIn, 0.9, 0.4])
  set(ais, 'circle-stroke-width', ['case', aisIn, 1, 0])
  const gfwIn = inWindow('date_ms', s, e)
  const gfw = sourceId('gfw_events')
  set(gfw, 'circle-color', ['case', gfwIn, COLORS.warn, COLORS.dim])
  set(gfw, 'circle-radius', [
    'case',
    gfwIn,
    ['interpolate', ['linear'], ['zoom'], 4, 2, 8, 3, 12, 4.5],
    ['interpolate', ['linear'], ['zoom'], 4, 1.2, 8, 2, 12, 3],
  ])
  set(gfw, 'circle-opacity', ['case', gfwIn, 0.8, 0.35])
  const sarIn = inWindow('ts_ms', s, e)
  const sar = sourceId('sar')
  set(sar, 'circle-stroke-opacity', [
    'case',
    sarIn,
    ['case', ['get', 'matched'], 0.5, 0.95],
    0.25,
  ])
  set(sar, 'circle-radius', [
    'case',
    sarIn,
    ['interpolate', ['linear'], ['zoom'], 4, 4, 8, 5.5, 12, 7.5],
    ['interpolate', ['linear'], ['zoom'], 4, 2.5, 8, 3.5, 12, 4.5],
  ])
  const alIn = inWindow('gen_ms', s, e)
  set(`${sourceId('alerts_geo')}-core`, 'circle-color', ['case', alIn, COLORS.crit, COLORS.dim])
  set(`${sourceId('alerts_geo')}-core`, 'circle-radius', ['case', alIn, 5, 3])
  set(`${sourceId('alerts_geo')}-halo`, 'circle-opacity', ['case', alIn, 0.2, 0])
}

function featureCentroid(feature: GeoJSON.Feature): [number, number] | null {
  const pts: Array<[number, number]> = []
  const walk = (v: unknown): void => {
    if (!Array.isArray(v)) return
    if (v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number') {
      pts.push([v[0], v[1]])
      return
    }
    v.forEach(walk)
  }
  const geom = feature.geometry
  if (!geom) return null
  if (geom.type === 'GeometryCollection') geom.geometries.forEach((g) => walk((g as { coordinates?: unknown }).coordinates))
  else walk((geom as { coordinates?: unknown }).coordinates)
  if (!pts.length) return null
  const [sx, sy] = pts.reduce(([ax, ay], [x, y]) => [ax + x, ay + y], [0, 0])
  return [sx / pts.length, sy / pts.length]
}

function tsAdvanced(prev: string | null, next: string | null): boolean {
  if (!next) return false
  if (!prev) return true
  return new Date(next).getTime() > new Date(prev).getTime()
}

function isWindowLive(end: string): boolean {
  return Math.abs(Date.now() - new Date(end).getTime()) <= 2 * 3600_000
}

function findZoneThreat(threats: Threat[], zoneId?: string): Threat | undefined {
  if (!zoneId) return undefined
  return threats.find((threat) => threat.kind === 'zone' && threat.zone_id === zoneId)
}

function addLayerStyle(map: maplibregl.Map, def: LayerDef): void {
  const src = sourceId(def.id)
  switch (def.id) {
    case 'ais_points':
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 2.5, 8, 4, 12, 6],
          'circle-color': COLORS.accent,
          'circle-opacity': 0.9,
          'circle-stroke-color': '#0a1220',
          'circle-stroke-width': 1,
        },
      })
      break
    case 'tracks':
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: { 'line-color': COLORS.accent, 'line-width': 1.2, 'line-opacity': 0.5 },
      })
      break
    case 'sar':
      // Satellite (SAR) detections as hollow rings so they read as distinct from
      // filled AIS dots. Unmatched detections (no AIS) are the dark-vessel signal
      // — thicker, brighter ring; matched ones are thin/subtle.
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 4, 8, 5.5, 12, 7.5],
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': COLORS.sat,
          'circle-stroke-width': ['case', ['get', 'matched'], 1, 2.2],
          'circle-stroke-opacity': ['case', ['get', 'matched'], 0.5, 0.95],
        },
      })
      break
    case 'alerts_geo':
      map.addLayer({
        id: `${src}-halo`,
        type: 'circle',
        source: src,
        paint: { 'circle-radius': 10, 'circle-color': COLORS.crit, 'circle-opacity': 0.2 },
      })
      map.addLayer({
        id: `${src}-core`,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': 5,
          'circle-color': COLORS.crit,
          'circle-stroke-color': '#0a1220',
          'circle-stroke-width': 1,
        },
      })
      break
    case 'events':
      // Curated incidents stay yellow regardless of the time window — they are
      // distinct from the gray GFW history, not window-dimmed context.
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': 5,
          'circle-color': COLORS.warn,
          'circle-opacity': 0.9,
          'circle-stroke-color': '#0a1220',
          'circle-stroke-width': 1,
        },
      })
      break
    case 'gfw_events':
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.2, 8, 2, 12, 3],
          'circle-color': COLORS.dim,
          'circle-opacity': 0.45,
        },
      })
      break
    case 'zones':
      map.addLayer({
        id: `${src}-gray-fill`,
        type: 'fill',
        source: src,
        filter: ['==', ['get', 'kind'], 'gray_zone'],
        paint: {
          'fill-color': COLORS.warn,
          'fill-opacity': 0.14,
        },
      })
      map.addLayer({
        id: `${src}-gray-outline`,
        type: 'line',
        source: src,
        filter: ['==', ['get', 'kind'], 'gray_zone'],
        paint: {
          'line-color': COLORS.warn,
          'line-width': 1.2,
          'line-opacity': 0.85,
        },
      })
      map.addLayer({
        id: `${src}-eez`,
        type: 'line',
        source: src,
        filter: ['==', ['get', 'kind'], 'eez'],
        paint: {
          'line-color': COLORS.steel,
          'line-width': 1,
          'line-dasharray': [2, 2],
          'line-opacity': 0.55,
        },
      })
      map.addLayer({
        id: `${src}-outline`,
        type: 'line',
        source: src,
        filter: ['all', ['!=', ['get', 'kind'], 'eez'], ['!=', ['get', 'kind'], 'gray_zone']],
        paint: {
          'line-color': COLORS.steel,
          'line-width': 1,
          'line-opacity': 0.55,
        },
      })
      break
    case 'cables':
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: { 'line-color': COLORS.steel, 'line-width': 1, 'line-opacity': 0.65 },
      })
      break
    case 'ports':
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: { 'circle-radius': 2.5, 'circle-color': portFill, 'circle-opacity': 0.75 },
      })
      break
  }
}

function removeLayer(map: maplibregl.Map, id: LayerId): void {
  for (const lid of layerIdsOf(id)) {
    if (map.getLayer(lid)) map.removeLayer(lid)
  }
  if (map.getSource(sourceId(id))) map.removeSource(sourceId(id))
}

function ensureData(map: maplibregl.Map, def: LayerDef, fc: FeatureCollection): void {
  const src = sourceId(def.id)
  const existing = map.getSource(src) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(fc as unknown as GeoJSON.FeatureCollection)
    return
  }
  map.addSource(src, { type: 'geojson', data: fc as unknown as GeoJSON.FeatureCollection })
  addLayerStyle(map, def)
}

function removeHighlight(map: maplibregl.Map): void {
  for (const id of HIGHLIGHT_LAYERS) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  if (map.getSource(HIGHLIGHT_SOURCE)) map.removeSource(HIGHLIGHT_SOURCE)
}

function ensureHighlight(map: maplibregl.Map, feature: GeoJSON.Feature): void {
  const fc: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [feature] }
  const existing = map.getSource(HIGHLIGHT_SOURCE) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(fc)
    return
  }
  map.addSource(HIGHLIGHT_SOURCE, { type: 'geojson', data: fc })
  map.addLayer({
    id: `${HIGHLIGHT_SOURCE}-fill`,
    type: 'fill',
    source: HIGHLIGHT_SOURCE,
    paint: {
      'fill-color': COLORS.warn,
      'fill-opacity': 0.22,
    },
  })
  map.addLayer({
    id: `${HIGHLIGHT_SOURCE}-line`,
    type: 'line',
    source: HIGHLIGHT_SOURCE,
    paint: {
      'line-color': COLORS.warn,
      'line-width': 3,
      'line-opacity': 0.95,
    },
  })
  map.addLayer({
    id: `${HIGHLIGHT_SOURCE}-point`,
    type: 'circle',
    source: HIGHLIGHT_SOURCE,
    paint: {
      'circle-radius': 8,
      'circle-color': COLORS.warn,
      'circle-opacity': 0.95,
      'circle-stroke-color': '#0a1220',
      'circle-stroke-width': 2,
    },
  })
}

interface LayerRequestState {
  inFlight: boolean
  pending: boolean
}

interface LatestLayerContext {
  map: maplibregl.Map | null
  regionId: string
  window: TimeWindow
  layersEnabled: Record<string, boolean>
  threats: Threat[]
}

interface LayerDeps {
  regionId: string
  start: string
  end: string
  layersEnabled: Record<string, boolean>
}

export default function DataLayers() {
  const map = useMap()
  const state = useAppState()
  const dispatch = useAppDispatch()
  const region = useRegion()
  const { theme } = useSettings()
  portFill = theme === 'light' ? PORT_COLOR_LIGHT : COLORS.bright

  useEffect(() => {
    if (!mapAlive(map)) return
    const id = sourceId('ports')
    if (map.getLayer(id)) map.setPaintProperty(id, 'circle-color', portFill)
  }, [map, theme])
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const latestRef = useRef<LatestLayerContext>({
    map,
    regionId: region.id,
    window: state.window,
    layersEnabled: state.layersEnabled,
    threats: state.threats,
  })
  const layerReqRef = useRef<Partial<Record<LayerId, LayerRequestState>>>({})
  const layerDepsRef = useRef<LayerDeps | null>(null)
  const changesRef = useRef<Changes | null>(null)

  latestRef.current = {
    map,
    regionId: region.id,
    window: state.window,
    layersEnabled: state.layersEnabled,
    threats: state.threats,
  }

  const requestLayer = useCallback((id: LayerId) => {
    const ctx = latestRef.current
    const targetMap = ctx.map
    if (!targetMap || !ctx.layersEnabled[id]) return
    const def = LAYER_DEFS.find((item) => item.id === id)
    if (!def) return
    const slot = (layerReqRef.current[id] ??= { inFlight: false, pending: false })
    if (slot.inFlight) {
      slot.pending = true
      return
    }
    slot.inFlight = true
    const params = { region: ctx.regionId, start: ctx.window.start, end: ctx.window.end }
    api
      .layer(id, params)
      .then((fc) => {
        const latest = latestRef.current
        if (!mapAlive(latest.map) || !latest.layersEnabled[id]) return
        if (
          latest.regionId !== params.region ||
          latest.window.start !== params.start ||
          latest.window.end !== params.end
        ) {
          slot.pending = true
          return
        }
        ensureData(latest.map, def, fc)
        applyWindowPaint(latest.map, latest.window)
      })
      .catch((err) => console.warn(`layer ${id}`, err))
      .finally(() => {
        slot.inFlight = false
        if (slot.pending) {
          slot.pending = false
          requestLayer(id)
        }
      })
  }, [])

  useEffect(() => {
    if (!mapAlive(map)) return
    const prev = layerDepsRef.current
    const next = {
      regionId: region.id,
      start: state.window.start,
      end: state.window.end,
      layersEnabled: state.layersEnabled,
    }
    const enabledChanged =
      !prev || LAYER_DEFS.some((def) => prev.layersEnabled[def.id] !== next.layersEnabled[def.id])
    const regionChanged = !prev || prev.regionId !== next.regionId
    const windowChanged = !prev || prev.start !== next.start || prev.end !== next.end
    const liveAisOnly =
      Boolean(prev) &&
      state.windowRefreshScope === 'ais' &&
      windowChanged &&
      !enabledChanged &&
      !regionChanged

    for (const def of LAYER_DEFS) {
      if (!state.layersEnabled[def.id]) {
        removeLayer(map, def.id)
        continue
      }
      if (liveAisOnly && !AIS_LAYER_IDS.has(def.id)) continue
      requestLayer(def.id)
    }
    layerDepsRef.current = next
  }, [
    map,
    region.id,
    state.window.start,
    state.window.end,
    state.layersEnabled,
    state.windowRefreshScope,
    requestLayer,
  ])

  useEffect(() => {
    changesRef.current = null
  }, [region.id])

  useEffect(() => {
    if (!mapAlive(map)) return
    applyWindowPaint(map, state.window)
  }, [map, state.window])

  useEffect(() => {
    if (!map) return
    const visible = () => CLICKABLE.filter((l) => map.getLayer(l))

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const layers = visible()
      if (!layers.length) return
      const feature = map.queryRenderedFeatures(e.point, { layers })[0]
      if (!feature) return
      const layerId = renderedLayerToLayerId(feature.layer.id)
      const props = (feature.properties ?? {}) as Record<string, unknown>
      const spec = popupSpec(layerId, props)
      if (layerId === 'alerts_geo' && props.alert_id != null) {
        dispatch({ type: 'selectThreat', id: String(props.alert_id) })
      }
      const anchor =
        feature.geometry.type === 'Point'
          ? (feature.geometry.coordinates.slice(0, 2) as [number, number])
          : e.lngLat
      popupRef.current?.remove()
      const popup = new maplibregl.Popup({ closeButton: true, maxWidth: '300px' })
        .setLngLat(anchor)
        .setHTML(buildHtml(spec))
        .addTo(map)
      popup.getElement().querySelector('[data-action="ontology"]')?.addEventListener('click', () => {
        dispatch({ type: 'ontologyFocus', focus: { table: spec.table, srcId: spec.srcId } })
        popup.remove()
      })
      popup.getElement().querySelector('[data-action="zone-threat"]')?.addEventListener('click', () => {
        const threat = findZoneThreat(latestRef.current.threats, spec.zoneThreat?.zoneId)
        if (threat) {
          dispatch({ type: 'selectThreat', id: threat.id })
          if (threat.lon != null && threat.lat != null) {
            dispatch({ type: 'focus', target: { lon: threat.lon, lat: threat.lat } })
          }
          popup.remove()
          return
        }
        const status = popup.getElement().querySelector('[data-role="zone-status"]')
        if (status) status.textContent = '존 위협 미산출'
      })
      popupRef.current = popup
    }

    const onMove = (e: maplibregl.MapMouseEvent) => {
      const layers = visible()
      const hit = layers.length ? map.queryRenderedFeatures(e.point, { layers }).length > 0 : false
      map.getCanvas().style.cursor = hit ? 'pointer' : ''
    }

    map.on('click', onClick)
    map.on('mousemove', onMove)
    return () => {
      map.off('click', onClick)
      map.off('mousemove', onMove)
      popupRef.current?.remove()
      if (!mapAlive(map)) return
      removeHighlight(map)
      for (const def of LAYER_DEFS) {
        removeLayer(map, def.id)
      }
    }
  }, [map, dispatch])

  useEffect(() => {
    if (!state.settings.autoRefresh || !isWindowLive(state.window.end)) return
    let cancelled = false
    const poll = () => {
      const ctx = latestRef.current
      if (!state.settings.autoRefresh || !isWindowLive(ctx.window.end)) return
      api
        .changes(ctx.regionId)
        .then((next) => {
          if (cancelled) return
          dispatch({
            type: 'liveStats',
            stats: {
              active_vessels_10m: next.active_vessels_10m,
              ais_rows_1h: next.ais_rows_1h,
              ais_max_ts: next.ais_max_ts,
            },
          })
          const prev = changesRef.current
          changesRef.current = next
          if (!prev) return
          if (tsAdvanced(prev.ais_max_ts, next.ais_max_ts)) {
            dispatch({
              type: 'window',
              window: { start: ctx.window.start, end: new Date().toISOString() },
              refreshScope: 'ais',
            })
          }
          if (tsAdvanced(prev.alerts_max_ts, next.alerts_max_ts)) {
            requestLayer('alerts_geo')
            dispatch({ type: 'triggerThreatsRefresh' })
          }
          if (tsAdvanced(prev.events_max_ts, next.events_max_ts)) {
            requestLayer('events')
            requestLayer('gfw_events')
          }
        })
        .catch((err) => console.warn('changes', err))
    }
    poll()
    const id = window.setInterval(poll, 2_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [state.settings.autoRefresh, state.window.end, dispatch, requestLayer])

  useEffect(() => {
    if (!mapAlive(map)) return
    if (!state.highlight) {
      removeHighlight(map)
      return
    }
    ensureHighlight(map, state.highlight.feature)
    const popupInfo = state.highlight.popup
    if (popupInfo) {
      const anchor = featureCentroid(state.highlight.feature)
      if (anchor) {
        popupRef.current?.remove()
        const popup = new maplibregl.Popup({ closeButton: true, maxWidth: '300px' })
          .setLngLat(anchor)
          .setHTML(
            buildHtml({
              title: popupInfo.title,
              color: COLORS.accent,
              rows: popupInfo.rows,
              table: popupInfo.table,
              srcId: popupInfo.srcId,
            }),
          )
          .addTo(map)
        popup.getElement().querySelector('[data-action="ontology"]')?.addEventListener('click', () => {
          dispatch({ type: 'ontologyFocus', focus: { table: popupInfo.table, srcId: popupInfo.srcId } })
          popup.remove()
        })
        popupRef.current = popup
      }
    }
    const id = window.setTimeout(() => dispatch({ type: 'highlight', feature: null }), 5_000)
    return () => window.clearTimeout(id)
  }, [map, state.highlight, dispatch])

  useEffect(() => {
    if (!mapAlive(map) || !state.focusTarget) return
    map.flyTo({
      center: [state.focusTarget.lon, state.focusTarget.lat],
      zoom: Math.max(map.getZoom(), 8),
      duration: 700,
    })
    dispatch({ type: 'focus', target: null })
  }, [map, state.focusTarget, dispatch])

  return null
}
