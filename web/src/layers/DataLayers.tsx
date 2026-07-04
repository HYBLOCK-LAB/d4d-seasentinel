import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import type * as GeoJSON from 'geojson'
import { useAppState, useAppDispatch, useRegion } from '../state/AppState'
import { api } from '../api/client'
import { useMap } from '../map/MapView'
import { COLORS, LAYER_DEFS } from './registry'
import type { LayerDef } from './registry'
import type { FeatureCollection, LayerId } from '../api/types'

const sourceId = (id: LayerId): string => `mda-${id}`

const layerIdsOf = (id: LayerId): string[] =>
  id === 'alerts_geo' ? [`${sourceId(id)}-halo`, `${sourceId(id)}-core`] : [sourceId(id)]

const CLICKABLE = LAYER_DEFS.map((d) =>
  d.id === 'alerts_geo' ? `${sourceId(d.id)}-core` : sourceId(d.id),
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
}

function popupSpec(layerId: LayerId, p: Record<string, unknown>): PopupSpec {
  switch (layerId) {
    case 'ais_points':
      return {
        title: 'AIS 선박',
        color: COLORS.accent,
        rows: [
          ['MMSI', p.mmsi],
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
    case 'zones':
      return {
        title: '구역',
        color: COLORS.steel,
        rows: [
          ['명칭', p.name],
          ['종류', p.kind],
        ],
        table: 'zone',
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
  return `<div style="display:flex;flex-direction:column;gap:2px">
    <div style="font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:${spec.color};margin-bottom:2px">${esc(spec.title)}</div>
    ${rows}${note}
    <button style="font-size:11px;color:#35e0c2;background:rgba(53,224,194,.14);border:1px solid rgba(53,224,194,.4);border-radius:2px;padding:2px 8px;cursor:pointer;margin-top:6px;align-self:flex-start">온톨로지 원본 보기</button>
  </div>`
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
    case 'zones':
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: {
          'line-color': COLORS.steel,
          'line-width': 1,
          'line-dasharray': [2, 2],
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
        paint: { 'circle-radius': 2.5, 'circle-color': COLORS.bright, 'circle-opacity': 0.75 },
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

export default function DataLayers() {
  const map = useMap()
  const state = useAppState()
  const dispatch = useAppDispatch()
  const region = useRegion()
  const popupRef = useRef<maplibregl.Popup | null>(null)

  useEffect(() => {
    if (!map) return
    let cancelled = false
    for (const def of LAYER_DEFS) {
      if (!state.layersEnabled[def.id]) {
        removeLayer(map, def.id)
        continue
      }
      api
        .layer(def.id, { region: region.id, start: state.window.start, end: state.window.end })
        .then((fc) => {
          if (!cancelled && map.getStyle()) ensureData(map, def, fc)
        })
        .catch((err) => console.warn(`layer ${def.id}`, err))
    }
    return () => {
      cancelled = true
    }
  }, [map, region.id, state.window.start, state.window.end, state.layersEnabled])

  useEffect(() => {
    if (!map) return
    const visible = () => CLICKABLE.filter((l) => map.getLayer(l))

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const layers = visible()
      if (!layers.length) return
      const feature = map.queryRenderedFeatures(e.point, { layers })[0]
      if (!feature) return
      const layerId = feature.layer.id.replace(/^mda-/, '').replace(/-core$/, '') as LayerId
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
      popup
        .getElement()
        .querySelector('button')
        ?.addEventListener('click', () => {
          dispatch({ type: 'ontologyFocus', focus: { table: spec.table, srcId: spec.srcId } })
          popup.remove()
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
      for (const def of LAYER_DEFS) {
        if (map.getStyle()) removeLayer(map, def.id)
      }
    }
  }, [map, dispatch])

  useEffect(() => {
    const endMs = new Date(state.window.end).getTime()
    if (Date.now() - endMs > 2 * 3600_000) return
    const id = window.setInterval(() => {
      dispatch({
        type: 'window',
        window: { start: state.window.start, end: new Date().toISOString() },
      })
    }, 60_000)
    return () => window.clearInterval(id)
  }, [state.window.start, state.window.end, dispatch])

  useEffect(() => {
    if (!map || !state.focusTarget) return
    map.flyTo({
      center: [state.focusTarget.lon, state.focusTarget.lat],
      zoom: Math.max(map.getZoom(), 8),
      duration: 700,
    })
    dispatch({ type: 'focus', target: null })
  }, [map, state.focusTarget, dispatch])

  return null
}
