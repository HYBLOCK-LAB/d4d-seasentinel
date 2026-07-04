import { useEffect, useMemo, useState } from 'react';
import { Panel, SectionHeader, Badge, ScoreBar } from '../design/components';
import { useAppState, useAppDispatch } from '../state/AppState';
import { api } from '../api/client';
import type { Threat } from '../api/types';
import EvidenceList from './EvidenceList';
import styles from './ThreatsPanel.module.css';

export default function ThreatsPanel() {
  const { regionId, window: timeWindow, selectedThreatId } = useAppState();
  const dispatch = useAppDispatch();
  const [threats, setThreats] = useState<Threat[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .threats({ region: regionId, start: timeWindow.start, end: timeWindow.end })
      .then((res) => {
        if (cancelled) return;
        setThreats(res.threats);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [regionId, timeWindow.start, timeWindow.end]);

  const sorted = useMemo(() => [...threats].sort((a, b) => b.score - a.score), [threats]);

  function handleClick(threat: Threat) {
    const next = selectedThreatId === threat.id ? null : threat.id;
    dispatch({ type: 'selectThreat', id: next });
    if (next && threat.lon != null && threat.lat != null) {
      dispatch({ type: 'focus', target: { lon: threat.lon, lat: threat.lat } });
    }
  }

  return (
    <Panel
      className={styles.panel}
      header={
        <SectionHeader
          title="THREATS · 위협 우선순위"
          actions={<span className={`mono ${styles.count}`}>{sorted.length}</span>}
        />
      }
    >
      {loading && sorted.length === 0 && <div className={styles.empty}>로딩 중...</div>}
      {!loading && sorted.length === 0 && (
        <div className={styles.empty}>표시할 데이터 없음</div>
      )}
      {sorted.map((threat) => {
        const selected = selectedThreatId === threat.id;
        const meta =
          threat.kind === 'vessel'
            ? [threat.type, threat.vessel_id, threat.generated_at?.slice(0, 16)]
                .filter(Boolean)
                .join(' · ')
            : [threat.type, threat.aoi_id, threat.date].filter(Boolean).join(' · ');
        return (
          <div key={threat.id} className={styles.rowWrap}>
            <div
              className={`${styles.row} ${selected ? styles.rowSelected : ''}`}
              onClick={() => handleClick(threat)}
            >
              <div className={styles.line1}>
                <Badge level={threat.level}>{threat.level}</Badge>
                <span className={styles.title}>{threat.title_ko}</span>
                <span className={`mono ${styles.score}`}>{threat.score.toFixed(1)}</span>
              </div>
              <ScoreBar score={threat.score} />
              <div className={`mono ${styles.meta}`}>{meta}</div>
            </div>
            {selected && <EvidenceList threatId={threat.id} />}
          </div>
        );
      })}
    </Panel>
  );
}
