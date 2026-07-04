import type { StyleSpecification } from 'maplibre-gl'

export const BASE_STYLE: StyleSpecification = {
  version: 8,
  glyphs: 'https://invalid.local/{fontstack}/{range}',
  sources: {
    land50: { type: 'geojson', data: '/geo/ne_50m_land.json' },
    land10: { type: 'geojson', data: '/geo/ne_10m_east_asia.json' },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0a1220' } },
    {
      id: 'land50-fill',
      type: 'fill',
      source: 'land50',
      maxzoom: 5,
      paint: { 'fill-color': '#1b2a44' },
    },
    {
      id: 'land10-fill',
      type: 'fill',
      source: 'land10',
      minzoom: 5,
      paint: { 'fill-color': '#1b2a44' },
    },
    {
      id: 'land50-line',
      type: 'line',
      source: 'land50',
      maxzoom: 5,
      paint: { 'line-color': 'rgba(148,178,209,0.35)', 'line-width': 0.6 },
    },
    {
      id: 'land10-line',
      type: 'line',
      source: 'land10',
      minzoom: 5,
      paint: { 'line-color': 'rgba(148,178,209,0.35)', 'line-width': 0.8 },
    },
  ],
}
