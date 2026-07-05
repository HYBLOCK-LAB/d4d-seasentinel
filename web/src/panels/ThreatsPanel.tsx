import { useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Panel, SectionHeader, Badge, ScoreBar } from '../design/components';
import { useAppState, useAppDispatch } from '../state/AppState';
import { api } from '../api/client';
import type { Threat } from '../api/types';
import EvidenceList from './EvidenceList';
import styles from './ThreatsPanel.module.css';

function Sparkline({ trend }: { trend?: Threat['trend'] }) {
  if (!trend || trend.length < 2) return null;
  const points = [...trend].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
  const values = points.map((item) => item.score);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const xAt = (index: number) => (index / Math.max(points.length - 1, 1)) * 46 + 1;
  const path = points
    .map((item, index) => {
      const y = 15 - ((item.score - min) / span) * 13;
      return `${xAt(index).toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  // Weight-set changes are marked so a score jump caused by re-tuned criteria
  // is not mistaken for a real threat change.
  const configMarks = points
    .map((item, index) => {
      const prev = index > 0 ? points[index - 1] : undefined;
      return prev?.config_hash && item.config_hash && item.config_hash !== prev.config_hash
        ? xAt(index)
        : null;
    })
    .filter((x): x is number => x != null);
  return (
    <svg className={styles.sparkline} viewBox="0 0 48 16" aria-hidden="true">
      {configMarks.map((x) => (
        <line key={x} x1={x} x2={x} y1={1} y2={15} stroke="#f5a623" strokeWidth={0.8} strokeDasharray="1.5 1.5" />
      ))}
      <polyline points={path} />
    </svg>
  );
}

export default function ThreatsPanel() {
  const { regionId, window: timeWindow, selectedThreatId, threatsRefreshSeq } = useAppState();
  const dispatch = useAppDispatch();
  const [threats, setThreats] = useState<Threat[]>([]);
  const [loading, setLoading] = useState(false);
  const [explain, setExplain] = useState<Record<string, { loading: boolean; error?: string }>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .threats({ region: regionId, start: timeWindow.start, end: timeWindow.end })
      .then((res) => {
        if (cancelled) return;
        setThreats(res.threats);
        dispatch({ type: 'threatsLoaded', threats: res.threats });
      })
      .catch(() => {
        if (!cancelled) {
          setThreats([]);
          dispatch({ type: 'threatsLoaded', threats: [] });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [regionId, timeWindow.start, timeWindow.end, threatsRefreshSeq, dispatch]);

  const sorted = useMemo(() => [...threats].sort((a, b) => b.score - a.score), [threats]);

  function handleClick(threat: Threat) {
    const next = selectedThreatId === threat.id ? null : threat.id;
    dispatch({ type: 'selectThreat', id: next });
    if (next && threat.lon != null && threat.lat != null) {
      dispatch({ type: 'focus', target: { lon: threat.lon, lat: threat.lat } });
    }
  }

  function handleExplain(event: MouseEvent<HTMLButtonElement>, threatId: string) {
    event.stopPropagation();
    setExplain((current) => ({ ...current, [threatId]: { loading: true } }));
    api
      .explain(threatId)
      .then((res) => {
        const summary = res.summary_ko ?? null;
        setThreats((current) =>
          current.map((threat) => (threat.id === threatId ? { ...threat, summary_ko: summary } : threat)),
        );
        setExplain((current) => ({
          ...current,
          [threatId]: summary ? { loading: false } : { loading: false, error: '생성된 설명 없음' },
        }));
      })
      .catch((err) => {
        const msg = String(err instanceof Error ? err.message : err);
        const unsupported = msg.includes('404') || msg.includes('501');
        setExplain((current) => ({
          ...current,
          [threatId]: { loading: false, error: unsupported ? '설명 생성 미지원' : '설명 생성 실패' },
        }));
      });
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
            : threat.kind === 'zone'
              ? [threat.type, threat.zone_id, threat.generated_at?.slice(0, 16)].filter(Boolean).join(' · ')
            : [threat.type, threat.aoi_id, threat.date].filter(Boolean).join(' · ');
        const explainState = explain[threat.id];
        return (
          <div key={threat.id} className={styles.rowWrap}>
            <div
              className={`${styles.row} ${selected ? styles.rowSelected : ''}`}
              onClick={() => handleClick(threat)}
            >
              <div className={styles.line1}>
                <Badge level={threat.level}>{threat.level}</Badge>
                {threat.type === 'precursor' && <Badge level="WATCH">사전 징후</Badge>}
                <span className={styles.title}>{threat.title_ko}</span>
                <Sparkline trend={threat.trend} />
                <span className={`mono ${styles.score}`}>{threat.score.toFixed(1)}</span>
              </div>
              <ScoreBar score={threat.score} />
              <div className={`mono ${styles.meta}`}>{meta}</div>
            </div>
            {selected && (
              <>
                <div className={styles.selectedBody}>
                  {threat.summary_ko ? (
                    <p className={styles.summary}>{threat.summary_ko}</p>
                  ) : (
                    <div className={styles.explainRow}>
                      <button
                        type="button"
                        className={styles.explainButton}
                        disabled={explainState?.loading}
                        onClick={(event) => handleExplain(event, threat.id)}
                      >
                        {explainState?.loading ? '설명 생성 중...' : '설명 생성'}
                      </button>
                      {explainState?.error && <span className={styles.explainError}>{explainState.error}</span>}
                    </div>
                  )}
                </div>
                <EvidenceList threatId={threat.id} />
              </>
            )}
          </div>
        );
      })}
    </Panel>
  );
}
