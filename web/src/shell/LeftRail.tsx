import { useMemo } from 'react';
import { Panel, SectionHeader, Toggle } from '../design/components';
import { useAppState, useAppDispatch } from '../state/AppState';
import { LAYER_DEFS } from '../layers/registry';
import SitrepCard from '../panels/SitrepCard';
import ThreatsPanel from '../panels/ThreatsPanel';
import styles from './LeftRail.module.css';

const GROUP_ORDER = ['ACTIVITY', 'DETECTIONS', 'EVENTS', 'REFERENCE'] as const;

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

function LayersPanel() {
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
    <Panel header={<SectionHeader title="LAYERS · 레이어" />}>
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
    </Panel>
  );
}

export default function LeftRail() {
  return (
    <aside className={styles.rail}>
      <SitrepCard />
      <div className={styles.threatsWrap}>
        <ThreatsPanel />
      </div>
      <div className={styles.layersWrap}>
        <LayersPanel />
      </div>
    </aside>
  );
}
