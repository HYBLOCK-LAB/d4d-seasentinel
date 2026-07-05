import { X } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppState, useAppDispatch, type RightPanel } from '../state/AppState';
import { OntologyPanel } from '../panels/OntologyPanel';
import { CopilotPanel } from '../panels/CopilotPanel';
import { OsintPanel } from '../panels/OsintPanel';
import { SettingsPanel } from '../panels/SettingsPanel';
import styles from './RightDrawer.module.css';

const TITLES: Record<Exclude<RightPanel, null>, string> = {
  ontology: 'ONTOLOGY · 원본',
  osint: 'OSINT · 첩보',
  copilot: 'COPILOT · 질의',
  settings: '설정',
};

export function RightDrawer() {
  const state = useAppState();
  const dispatch = useAppDispatch();

  return (
    <aside className={styles.drawer}>
      <div className={styles.header}>
        <span className={styles.title}>{state.rightPanel ? TITLES[state.rightPanel] : ''}</span>
        <div className={styles.spacer} />
        <IconButton title="닫기" onClick={() => dispatch({ type: 'rightPanel', panel: null })}>
          <X size={14} />
        </IconButton>
      </div>
      <div className={styles.body}>
        {state.rightPanel === 'copilot' ? (
          <CopilotPanel />
        ) : state.rightPanel === 'osint' ? (
          <OsintPanel />
        ) : state.rightPanel === 'settings' ? (
          <SettingsPanel />
        ) : (
          <OntologyPanel />
        )}
      </div>
    </aside>
  );
}
