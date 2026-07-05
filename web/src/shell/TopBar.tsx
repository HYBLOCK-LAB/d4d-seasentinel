import { Database, MessageSquareText, Rss, Settings } from 'lucide-react'
import { IconButton, Kpi } from '../design/components'
import { useAppDispatch, useAppState } from '../state/AppState'
import styles from './TopBar.module.css'

function fmtWindow(start: string, end: string): string {
  const f = (s: string) => s.slice(0, 16).replace('T', ' ')
  return `${f(start)} → ${f(end)}Z`
}

function fmtNum(value: number | undefined): string {
  return (value ?? 0).toLocaleString('ko-KR')
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return '·'
  return value.slice(11, 19)
}

export function TopBar() {
  const state = useAppState()
  const dispatch = useAppDispatch()
  const counts = state.meta?.counts
  const activeVessels = state.liveStats?.active_vessels_10m ?? counts?.vessel_active_10m ?? 0
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
      {state.settings.dataset && (
        <span className={styles.simBadge}>
          SIMULATION · {state.settings.datasetLabel || state.settings.dataset}
        </span>
      )}
      <div className={styles.spacer} />
      {(counts || state.liveStats) && (
        <div className={styles.kpis}>
          <Kpi value={fmtNum(activeVessels)} label="인지 선박(10분)" tone="accent" />
          <div className={styles.secondaryKpis}>
            <span>
              누적 선박 <b className="mono">{fmtNum(counts?.vessel)}</b>
            </span>
            <span>
              AIS 행수 <b className="mono">{fmtNum(state.liveStats?.ais_rows_1h ?? counts?.ais_position)}</b>
            </span>
            <span>
              최근 AIS <b className="mono">{fmtTime(state.liveStats?.ais_max_ts)}</b>
            </span>
          </div>
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
