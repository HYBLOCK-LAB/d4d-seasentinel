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
}

export const LAYER_DEFS: LayerDef[] = [
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
    legend: { kind: 'point', color: COLORS.steel },
  },
]
