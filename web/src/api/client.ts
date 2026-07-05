import type {
  Changes,
  DatasetList,
  FeatureCollection,
  ScoringConfig,
  ScoringDetector,
  LayerId,
  Meta,
  OntologyRows,
  OntologyTable,
  Threat,
  ThreatEvidence,
  TimelineBucket,
} from './types'

let currentDataset = ''

export function setDataset(id: string): void {
  currentDataset = id === 'live' ? '' : id
}

export function activeDataset(): string {
  return currentDataset
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const entries = Object.entries({ dataset: currentDataset, ...params }).filter(
    ([, v]) => v !== undefined && v !== '',
  )
  const qs = entries.length
    ? '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
    : ''
  const res = await fetch(`/api${path}${qs}`)
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { method: 'POST' })
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json() as Promise<T>
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json() as Promise<T>
}

export interface WindowParams {
  region: string
  start: string
  end: string
}

export const api = {
  meta: () => get<Meta>('/meta'),
  changes: (region: string) => get<Changes>('/changes', { region }),
  threats: (p: WindowParams) => get<{ threats: Threat[] }>('/threats', { ...p }),
  explain: (id: string) =>
    post<{ summary_ko?: string | null }>(`/threats/${encodeURIComponent(id)}/explain`),
  evidence: (id: string) => get<ThreatEvidence>(`/threats/${encodeURIComponent(id)}/evidence`),
  layer: (id: LayerId, p: WindowParams) =>
    get<FeatureCollection>(`/layers/${id}`, { ...p, track_minutes: id === 'tracks' ? 60 : undefined }),
  timeline: (p: WindowParams, bucket: 'hour' | 'day') =>
    get<{ buckets: TimelineBucket[] }>('/timeline', { ...p, bucket }),
  ontologyTables: () => get<OntologyTable[]>('/ontology/tables'),
  ontologyRows: (table: string, limit: number, offset: number) =>
    get<OntologyRows>(`/ontology/${table}`, { limit, offset }),
  models: () => get<{ models: string[]; default: string }>('/models'),
  datasets: () => get<DatasetList>('/datasets'),
  scoringConfig: () => get<ScoringConfig>('/scoring/config'),
  updateScoring: (detectors: Array<Partial<ScoringDetector> & { name: string }>) =>
    putJson<{ updated: number }>('/scoring/config', { detectors }),
  rerunScoring: () => post<{ started: boolean }>('/scoring/rerun'),
}

export async function copilotStream(
  body: { query: string; context: string; model?: string },
  onDelta: (text: string) => void,
): Promise<void> {
  const res = await fetch('/api/copilot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) throw new Error(`copilot ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload || payload === '[DONE]') continue
      try {
        const delta = JSON.parse(payload).choices?.[0]?.delta?.content
        if (delta) onDelta(delta)
      } catch {
        // partial SSE frame — skipped
      }
    }
  }
}
