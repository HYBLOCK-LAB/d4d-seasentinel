import { Database, MessageSquareText, Rss, Settings } from 'lucide-react'
import { IconButton, Kpi } from '../design/components'
import { useAppDispatch, useAppState } from '../state/AppState'
import styles from './TopBar.module.css'

function fmtWindow(start: string, end: string): string {
  const f = (s: string) => s.slice(0, 16).replace('T', ' ')
  return `${f(start)} → ${f(end)}Z`
}

export function TopBar() {
  const state = useAppState()
  const dispatch = useAppDispatch()
  const counts = state.meta?.counts
  return (
    <header className={styles.bar}>
      <div className={styles.brand}>
        SEA<b>SENTINEL</b>
        <span className={styles.dot} />
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
      {counts && (
        <div className={styles.kpis}>
          <Kpi value={counts.vessel ?? 0} label="선박" />
          <Kpi value={counts.ais_position ?? 0} label="AIS" tone="accent" />
          <Kpi value={counts.osint_item ?? 0} label="OSINT" />
          <Kpi value={counts.alert ?? 0} label="경보" tone={counts.alert ? 'warn' : undefined} />
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
          title="OSINT 첩보"
          active={state.rightPanel === 'osint'}
          onClick={() => dispatch({ type: 'rightPanel', panel: state.rightPanel === 'osint' ? null : 'osint' })}
        >
          <Rss size={14} />
        </IconButton>
        <IconButton
          title="코파일럿"
          active={state.rightPanel === 'copilot'}
          onClick={() => dispatch({ type: 'rightPanel', panel: state.rightPanel === 'copilot' ? null : 'copilot' })}
        >
          <MessageSquareText size={14} />
        </IconButton>
        <IconButton
          title="설정"
          active={state.rightPanel === 'settings'}
          onClick={() => dispatch({ type: 'rightPanel', panel: state.rightPanel === 'settings' ? null : 'settings' })}
        >
          <Settings size={14} />
        </IconButton>
      </div>
    </header>
  )
}
