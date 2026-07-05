import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Panel, SectionHeader, Toggle } from '../design/components';
import { useAppState, useAppDispatch } from '../state/AppState';
import { LAYER_DEFS } from '../layers/registry';
import SitrepCard from '../panels/SitrepCard';
import ThreatsPanel from '../panels/ThreatsPanel';
import styles from './LeftRail.module.css';

const GROUP_ORDER = ['ACTIVITY', 'DETECTIONS', 'EVENTS', 'REFERENCE'] as const;

const WIDTH_KEY = 'seasentinel.railW';
const COLLAPSE_KEY = 'seasentinel.layersCollapsed';
const MIN_W = 220;
const DEFAULT_W = 320;

function clampWidth(w: number): number {
  const max = Math.max(MIN_W, Math.min(560, Math.round(window.innerWidth * 0.4)));
  return Math.min(max, Math.max(MIN_W, w));
}

function loadWidth(): number {
  const raw = Number(localStorage.getItem(WIDTH_KEY));
  return raw ? clampWidth(raw) : DEFAULT_W;
}

interface LayerRowProps {
  titleKo: string;
  kind: string;
  color: string;
  on: boolean;
  onChange: (on: boolean) => void;
}

function LayerRow({ titleKo, kind, color, on, onChange }: LayerRowProps) {
  return (
    <div className={styles.layerRow}>
      <span
        className={kind === 'line' ? styles.chipLine : styles.chipSquare}
        style={{
          background: kind === 'line' ? 'transparent' : color,
          borderColor: color,
        }}
      />
      <span className={styles.layerTitle}>{titleKo}</span>
      <span className={styles.spacer} />
      <Toggle on={on} onChange={onChange} />
    </div>
  );
}

function LayersPanel({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { layersEnabled } = useAppState();
  const dispatch = useAppDispatch();

  const groups = useMemo(
    () =>
      GROUP_ORDER.map((group) => ({
        group,
        items: LAYER_DEFS.filter((def) => def.group === group),
      })).filter((g) => g.items.length > 0),
    []
  );

  return (
    <Panel header={<SectionHeader title="LAYERS · 레이어" collapsed={collapsed} onToggle={onToggle} />}>
      {!collapsed && (
        <div className={styles.layersBody}>
          {groups.map(({ group, items }) => (
            <div key={group} className={styles.group}>
              <div className={`micro-label ${styles.groupCaption}`}>{group}</div>
              {items.map((def) => (
                <LayerRow
                  key={def.id}
                  titleKo={def.titleKo}
                  kind={def.legend.kind}
                  color={def.legend.color}
                  on={layersEnabled[def.id] ?? false}
                  onChange={(on) => dispatch({ type: 'layer', id: def.id, on })}
                />
              ))}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default function LeftRail() {
  const [width, setWidth] = useState(loadWidth);
  const [layersCollapsed, setLayersCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1'
  );
  const drag = useRef<{ startX: number; startW: number } | null>(null);

  const onMove = useCallback((e: PointerEvent) => {
    if (!drag.current) return;
    setWidth(clampWidth(drag.current.startW + (e.clientX - drag.current.startX)));
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

  function toggleLayers() {
    setLayersCollapsed((c) => {
      const next = !c;
      localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
      return next;
    });
  }

  return (
    <aside className={styles.rail} style={{ width }}>
      <SitrepCard />
      <div className={styles.threatsWrap}>
        <ThreatsPanel />
      </div>
      <div className={`${styles.layersWrap} ${layersCollapsed ? styles.layersCollapsed : ''}`}>
        <LayersPanel collapsed={layersCollapsed} onToggle={toggleLayers} />
      </div>
      <div
        className={styles.resizer}
        onPointerDown={startDrag}
        role="separator"
        aria-orientation="vertical"
        title="드래그하여 너비 조절"
      />
    </aside>
  );
}
