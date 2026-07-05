import { useCallback, useEffect, useRef, useState } from 'react';
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

const WIDTH_KEY = 'seasentinel.drawerW';
const MIN_W = 320;
const DEFAULT_W = 380;

function clampWidth(w: number): number {
  const max = Math.max(MIN_W, Math.min(900, Math.round(window.innerWidth * 0.9)));
  return Math.min(max, Math.max(MIN_W, w));
}

function loadWidth(): number {
  const raw = Number(localStorage.getItem(WIDTH_KEY));
  return raw ? clampWidth(raw) : DEFAULT_W;
}

export function RightDrawer() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const [width, setWidth] = useState(loadWidth);
  const drag = useRef<{ startX: number; startW: number } | null>(null);

  const onMove = useCallback((e: PointerEvent) => {
    if (!drag.current) return;
    setWidth(clampWidth(drag.current.startW + (drag.current.startX - e.clientX)));
  }, []);

  const onUp = useCallback(() => {
    drag.current = null;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    setWidth((w) => {
      localStorage.setItem(WIDTH_KEY, String(w));
      return w;
    });
  }, []);

  useEffect(() => {
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    const onResize = () => setWidth((w) => clampWidth(w));
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('resize', onResize);
    };
  }, [onMove, onUp]);

  function startDrag(e: React.PointerEvent) {
    drag.current = { startX: e.clientX, startW: width };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }

  return (
    <aside className={styles.drawer} style={{ width }}>
      <div
        className={styles.resizer}
        onPointerDown={startDrag}
        role="separator"
        aria-orientation="vertical"
        title="드래그하여 너비 조절"
      />
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
