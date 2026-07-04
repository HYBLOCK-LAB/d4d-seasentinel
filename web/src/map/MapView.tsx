import maplibregl, { Map as MlMap, NavigationControl, ScaleControl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useRegion, useSettings } from '../state/AppState'
import { BASE_STYLE, MAP_THEME } from './baseStyle'
import styles from './MapView.module.css'

const MapCtx = createContext<MlMap | null>(null)

export function useMap(): MlMap | null {
  return useContext(MapCtx)
}

export function MapView({ children }: { children?: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MlMap | null>(null)
  const region = useRegion()
  const { theme } = useSettings()
  const [cursor, setCursor] = useState<{ lon: number; lat: number } | null>(null)

  useEffect(() => {
    if (!map) return
    const t = MAP_THEME[theme]
    map.setPaintProperty('bg', 'background-color', t.bg)
    for (const id of ['land50-fill', 'land10-fill']) map.setPaintProperty(id, 'fill-color', t.land)
    for (const id of ['land50-line', 'land10-line']) map.setPaintProperty(id, 'line-color', t.coast)
  }, [map, theme])

  useEffect(() => {
    if (!containerRef.current) return
    const m = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      attributionControl: false,
      dragRotate: false,
    })
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
    m.on('mousemove', (e) => setCursor({ lon: e.lngLat.lng, lat: e.lngLat.lat }))
    m.on('load', () => setMap(m))
    return () => {
      setMap(null)
      m.remove()
    }
  }, [])

  useEffect(() => {
    if (!map) return
    const [minLon, minLat, maxLon, maxLat] = region.bbox
    map.fitBounds(
      [
        [minLon, minLat],
        [maxLon, maxLat],
      ],
      { padding: 48, duration: 600 },
    )
  }, [map, region])

  return (
    <div className={styles.wrap}>
      <div ref={containerRef} className={styles.map} />
      {cursor && (
        <div className={styles.coords}>
          {cursor.lat.toFixed(4)}°N {cursor.lon.toFixed(4)}°E
        </div>
      )}
      <MapCtx.Provider value={map}>{map ? children : null}</MapCtx.Provider>
    </div>
  )
}
