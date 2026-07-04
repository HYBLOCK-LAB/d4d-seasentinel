import { X } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppState, useAppDispatch } from '../state/AppState';
import { OntologyPanel } from '../panels/OntologyPanel';
import { CopilotPanel } from '../panels/CopilotPanel';
import styles from './RightDrawer.module.css';

export function RightDrawer() {
  const state = useAppState();
  const dispatch = useAppDispatch();

  return (
    <aside className={styles.drawer}>
      <div className={styles.header}>
        <button
          type="button"
          className={`${styles.tab} ${state.rightPanel === 'ontology' ? styles.tabActive : ''}`}
          onClick={() => dispatch({ type: 'rightPanel', panel: 'ontology' })}
        >
          ONTOLOGY · 원본
        </button>
        <button
          type="button"
          className={`${styles.tab} ${state.rightPanel === 'copilot' ? styles.tabActive : ''}`}
          onClick={() => dispatch({ type: 'rightPanel', panel: 'copilot' })}
        >
          COPILOT · 질의
        </button>
        <div className={styles.spacer} />
        <IconButton title="닫기" onClick={() => dispatch({ type: 'rightPanel', panel: null })}>
          <X size={14} />
        </IconButton>
      </div>
      <div className={styles.body}>
        {state.rightPanel === 'ontology' ? <OntologyPanel /> : <CopilotPanel />}
      </div>
    </aside>
  );
}
