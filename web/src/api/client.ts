import type {
  FeatureCollection,
  LayerId,
  Meta,
  OntologyRows,
  OntologyTable,
  Threat,
  ThreatEvidence,
  TimelineBucket,
} from './types'

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = params
    ? '?' +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
        .join('&')
    : ''
  const res = await fetch(`/api${path}${qs}`)
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
  threats: (p: WindowParams) => get<{ threats: Threat[] }>('/threats', { ...p }),
  evidence: (id: string) => get<ThreatEvidence>(`/threats/${encodeURIComponent(id)}/evidence`),
  layer: (id: LayerId, p: WindowParams) => get<FeatureCollection>(`/layers/${id}`, { ...p }),
  timeline: (p: WindowParams, bucket: 'hour' | 'day') =>
    get<{ buckets: TimelineBucket[] }>('/timeline', { ...p, bucket }),
  ontologyTables: () => get<OntologyTable[]>('/ontology/tables'),
  ontologyRows: (table: string, limit: number, offset: number) =>
    get<OntologyRows>(`/ontology/${table}`, { limit, offset }),
  models: () => get<{ models: string[]; default: string }>('/models'),
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
