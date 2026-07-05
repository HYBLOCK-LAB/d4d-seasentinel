import type { LayerId } from '../api/types'

export interface LayerDef {
  id: LayerId
  group: 'ACTIVITY' | 'DETECTIONS' | 'EVENTS' | 'REFERENCE'
  title: string
  titleKo: string
  legend: { kind: 'point' | 'line' | 'outline'; color: string }
}

export const COLORS = {
  accent: '#35e0c2',
  warn: '#f5a623',
  crit: '#ff5a4d',
  steel: '#94b2d1',
  bright: '#e8f0f9',
  dim: '#6b7687',
  sat: '#b388ff',
}

export const LAYER_DEFS: LayerDef[] = [
  {
    id: 'gfw_events',
    group: 'ACTIVITY',
    title: 'Historical vessel events (GFW)',
    titleKo: '과거 선박 이벤트(GFW)',
    legend: { kind: 'point', color: COLORS.dim },
  },
  {
    id: 'ais_points',
    group: 'ACTIVITY',
    title: 'AIS positions',
    titleKo: 'AIS 위치',
    legend: { kind: 'point', color: COLORS.accent },
  },
  {
    id: 'tracks',
    group: 'ACTIVITY',
    title: 'Vessel tracks',
    titleKo: '항적',
    legend: { kind: 'line', color: COLORS.accent },
  },
  {
    id: 'sar',
    group: 'DETECTIONS',
    title: 'Satellite detections (SAR)',
    titleKo: '위성 탐지(SAR)',
    legend: { kind: 'outline', color: COLORS.sat },
  },
  {
    id: 'alerts_geo',
    group: 'DETECTIONS',
    title: 'Threat alerts',
    titleKo: '위협 경보',
    legend: { kind: 'point', color: COLORS.crit },
  },
  {
    id: 'events',
    group: 'EVENTS',
    title: 'Curated incidents',
    titleKo: '수집 사건',
    legend: { kind: 'point', color: COLORS.warn },
  },
  {
    id: 'zones',
    group: 'REFERENCE',
    title: 'Zones / AOI',
    titleKo: '구역·AOI',
    legend: { kind: 'outline', color: COLORS.steel },
  },
  {
    id: 'cables',
    group: 'REFERENCE',
    title: 'Submarine cables',
    titleKo: '해저케이블',
    legend: { kind: 'line', color: COLORS.steel },
  },
  {
    id: 'ports',
    group: 'REFERENCE',
    title: 'Ports',
    titleKo: '항만',
    legend: { kind: 'point', color: COLORS.bright },
  },
]
