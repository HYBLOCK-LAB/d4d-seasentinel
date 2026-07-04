import { useEffect } from 'react'
import maplibregl from 'maplibre-gl'
import type * as GeoJSON from 'geojson'
import { useAppState, useAppDispatch, useRegion } from '../state/AppState'
import { api } from '../api/client'
import { useMap } from '../map/MapView'
import { LAYER_DEFS, COLORS } from './registry'
import type { LayerDef } from './registry'
import type { FeatureCollection, LayerId } from '../api/types'

const sourceId = (id: LayerId): string => `mda-${id}`

const layerIds = (id: LayerId): string[] => {
  if (id === 'alerts_geo') return [`${sourceId(id)}-halo`, `${sourceId(id)}-core`]
  return [sourceId(id)]
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function popupHtml(props: Record<string, unknown>): string {
  const mmsi = props.mmsi ?? '-'
  const ts = props.ts ?? props.timestamp ?? '-'
  const sog = props.sog ?? props.speed ?? '-'
  return `<div class="mono" style="font-size:11px;line-height:1.7;color:#eef3f9">
    <div>MMSI ${escapeHtml(String(mmsi))}</div>
    <div>${escapeHtml(String(ts))}</div>
    <div>SOG ${escapeHtml(String(sog))} kn</div>
  </div>`
}

function removeLayerFromMap(map: maplibregl.Map, id: LayerId): void {
  const src = sourceId(id)
  for (const lid of layerIds(id)) {
    if (map.getLayer(lid)) map.removeLayer(lid)
  }
  if (map.getSource(src)) map.removeSource(src)
}

function addLayerStyle(map: maplibregl.Map, def: LayerDef, onSelectThreat: (id: string) => void): void {
  const src = sourceId(def.id)

  switch (def.id) {
    case 'ais_points': {
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.5, 8, 3, 12, 5],
          'circle-color': COLORS.accent,
          'circle-opacity': 0.85,
        },
      })
      map.on('mouseenter', src, () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', src, () => {
        map.getCanvas().style.cursor = ''
      })
      map.on('click', src, (e) => {
        const f = e.features?.[0]
        if (!f || f.geometry.type !== 'Point') return
        const coords = f.geometry.coordinates.slice(0, 2) as [number, number]
        new maplibregl.Popup({ closeButton: false })
          .setLngLat(coords)
          .setHTML(popupHtml(f.properties ?? {}))
          .addTo(map)
      })
      break
    }
    case 'tracks': {
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: { 'line-color': COLORS.accent, 'line-width': 1, 'line-opacity': 0.45 },
      })
      break
    }
    case 'alerts_geo': {
      const halo = `${src}-halo`
      const core = `${src}-core`
      map.addLayer({
        id: halo,
        type: 'circle',
        source: src,
        paint: { 'circle-radius': 9, 'circle-color': COLORS.crit, 'circle-opacity': 0.18 },
      })
      map.addLayer({
        id: core,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': 4.5,
          'circle-color': COLORS.crit,
          'circle-stroke-color': '#0a1220',
          'circle-stroke-width': 1,
        },
      })
      map.on('mouseenter', core, () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', core, () => {
        map.getCanvas().style.cursor = ''
      })
      map.on('click', core, (e) => {
        const f = e.features?.[0]
        const alertId = f?.properties?.alert_id
        if (alertId != null) onSelectThreat(String(alertId))
      })
      break
    }
    case 'events': {
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: {
          'circle-radius': 4,
          'circle-color': COLORS.warn,
          'circle-opacity': 0.8,
          'circle-stroke-color': '#0a1220',
          'circle-stroke-width': 1,
        },
      })
      break
    }
    case 'zones': {
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: {
          'line-color': COLORS.steel,
          'line-width': 1,
          'line-dasharray': [2, 2],
          'line-opacity': 0.5,
        },
      })
      break
    }
    case 'cables': {
      map.addLayer({
        id: src,
        type: 'line',
        source: src,
        paint: { 'line-color': COLORS.steel, 'line-width': 0.8, 'line-opacity': 0.6 },
      })
      break
    }
    case 'ports': {
      map.addLayer({
        id: src,
        type: 'circle',
        source: src,
        paint: { 'circle-radius': 2, 'circle-color': COLORS.steel, 'circle-opacity': 0.5 },
      })
      break
    }
    default:
      break
  }
}

function ensureLayerData(
  map: maplibregl.Map,
  def: LayerDef,
  geojson: FeatureCollection,
  onSelectThreat: (id: string) => void,
): void {
  const src = sourceId(def.id)
  const existing = map.getSource(src) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(geojson as unknown as GeoJSON.FeatureCollection)
    return
  }
  map.addSource(src, { type: 'geojson', data: geojson as unknown as GeoJSON.FeatureCollection })
  addLayerStyle(map, def, onSelectThreat)
}

export default function DataLayers() {
  const map = useMap()
  const state = useAppState()
  const dispatch = useAppDispatch()
  const region = useRegion()

  useEffect(() => {
    if (!map) return
    let cancelled = false

    const onSelectThreat = (id: string) => dispatch({ type: 'selectThreat', id })

    for (const def of LAYER_DEFS) {
      const enabled = !!state.layersEnabled[def.id]
      if (!enabled) {
        removeLayerFromMap(map, def.id)
        continue
      }
      api
        .layer(def.id, { region: region.id, start: state.window.start, end: state.window.end })
        .then((geojson) => {
          if (cancelled) return
          ensureLayerData(map, def, geojson, onSelectThreat)
        })
        .catch((err) => {
          console.warn(`[DataLayers] failed to load layer ${def.id}`, err)
        })
    }

    return () => {
      cancelled = true
    }
  }, [map, region.id, state.window.start, state.window.end, state.layersEnabled, dispatch])

  useEffect(() => {
    return () => {
      if (!map) return
      for (const def of LAYER_DEFS) {
        removeLayerFromMap(map, def.id)
      }
    }
  }, [map])

  useEffect(() => {
    if (!map || !state.focusTarget) return
    const { lon, lat } = state.focusTarget
    map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 8), duration: 700 })
    dispatch({ type: 'focus', target: null })
  }, [map, state.focusTarget, dispatch])

  return null
}
