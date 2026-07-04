import { Database, MessageSquareText } from 'lucide-react'
import { IconButton, Kpi } from '../design/components'
import { useAppDispatch, useAppState } from '../state/AppState'
import styles from './TopBar.module.css'

function fmtWindow(start: string, end: string): string {
  const f = (s: string) => s.slice(0, 16).replace('T', ' ')
  return `${f(start)} → ${f(end)}Z`
}

export function TopBar({ kpis }: { kpis?: { tracked: number; threats: number; critical: number } }) {
  const state = useAppState()
  const dispatch = useAppDispatch()
  return (
    <header className={styles.bar}>
      <div className={styles.brand}>
        MDA<b>SENTINEL</b>
        <span className={styles.dot} />
        <span className={styles.sub}>Maritime Domain Awareness · Ontology Layer</span>
      </div>
      <select
        className={styles.region}
        value={state.regionId}
        onChange={(e) => dispatch({ type: 'region', regionId: e.target.value })}
      >
        {state.regions.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>
      <span className={[styles.window, 'mono'].join(' ')}>{fmtWindow(state.window.start, state.window.end)}</span>
      <div className={styles.spacer} />
      {kpis && (
        <div className={styles.kpis}>
          <Kpi value={kpis.tracked} label="tracked" />
          <Kpi value={kpis.threats} label="threats" tone="warn" />
          <Kpi value={kpis.critical} label="critical" tone="crit" />
        </div>
      )}
      <div className={styles.actions}>
        <IconButton
          title="온톨로지 원본"
          active={state.rightPanel === 'ontology'}
          onClick={() => dispatch({ type: 'rightPanel', panel: state.rightPanel === 'ontology' ? null : 'ontology' })}
        >
          <Database size={14} />
        </IconButton>
        <IconButton
          title="코파일럿"
          active={state.rightPanel === 'copilot'}
          onClick={() => dispatch({ type: 'rightPanel', panel: state.rightPanel === 'copilot' ? null : 'copilot' })}
        >
          <MessageSquareText size={14} />
        </IconButton>
      </div>
    </header>
  )
}
