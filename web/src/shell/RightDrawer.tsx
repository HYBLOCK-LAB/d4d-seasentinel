import { X } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppState, useAppDispatch, type RightPanel } from '../state/AppState';
import { OntologyPanel } from '../panels/OntologyPanel';
import { CopilotPanel } from '../panels/CopilotPanel';
import { OsintPanel } from '../panels/OsintPanel';
import { SettingsPanel } from '../panels/SettingsPanel';
import styles from './RightDrawer.module.css';

const TABS: Array<{ id: Exclude<RightPanel, null>; label: string }> = [
  { id: 'ontology', label: 'ONTOLOGY · 원본' },
  { id: 'osint', label: 'OSINT · 첩보' },
  { id: 'copilot', label: 'COPILOT · 질의' },
  { id: 'settings', label: '설정' },
];

export function RightDrawer() {
  const state = useAppState();
  const dispatch = useAppDispatch();

  return (
    <aside className={styles.drawer}>
      <div className={styles.header}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.tab} ${state.rightPanel === tab.id ? styles.tabActive : ''}`}
            onClick={() => dispatch({ type: 'rightPanel', panel: tab.id })}
          >
            {tab.label}
          </button>
        ))}
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
