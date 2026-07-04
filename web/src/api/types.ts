export interface Region {
  id: string
  name: string
  bbox: [number, number, number, number]
  theatre?: string | null
  priority?: string | null
}

export interface TimeWindow {
  start: string
  end: string
}

export interface Meta {
  regions: Region[]
  default_region: string
  window: TimeWindow
  counts: Record<string, number>
  sources: string[]
}

export type ThreatKind = 'vessel' | 'area'
export type ThreatLevel = 'CRITICAL' | 'HIGH' | 'MED' | 'ALERT' | 'WATCH'

export interface Threat {
  id: string
  kind: ThreatKind
  type: string
  level: ThreatLevel
  score: number
  title_ko: string
  title_en: string
  region?: string | null
  vessel_id?: string | null
  aoi_id?: string | null
  date?: string | null
  generated_at?: string | null
  lon?: number | null
  lat?: number | null
}

export interface Provenance {
  source_id?: string | null
  collector?: string | null
  fetched_at?: string | null
  raw_ref?: string | null
}

export interface Evidence {
  term: string
  points: number
  detail?: string | null
  src_table: string
  src_id: string
  src_summary?: Record<string, unknown> | null
  provenance?: Provenance | null
}

export interface ThreatEvidence {
  threat: Threat
  evidence: Evidence[]
}

export interface TimelineBucket {
  t: string
  ais: number
  osint: number
  alerts: number
}

export interface OntologyTable {
  table: string
  count: number
}

export interface OntologyRows {
  columns: string[]
  rows: unknown[][]
  total: number
}

export type LayerId =
  | 'ais_points'
  | 'tracks'
  | 'ports'
  | 'cables'
  | 'zones'
  | 'events'
  | 'alerts_geo'

export interface FeatureCollection {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    geometry: { type: string; coordinates: unknown }
    properties: Record<string, unknown>
  }>
}
