import { useEffect, useState } from 'react';
import { useAppDispatch } from '../state/AppState';
import { api } from '../api/client';
import type { Evidence } from '../api/types';
import styles from './EvidenceList.module.css';

interface EvidenceListProps {
  threatId: string;
}

export default function EvidenceList({ threatId }: EvidenceListProps) {
  const dispatch = useAppDispatch();
  const [evidence, setEvidence] = useState<Evidence[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvidence(null);
    api.evidence(threatId).then((res) => {
      if (!cancelled) setEvidence(res.evidence);
    });
    return () => {
      cancelled = true;
    };
  }, [threatId]);

  const total = (evidence ?? []).reduce((sum, e) => sum + e.points, 0);

  return (
    <div className={styles.wrap}>
      <div className={`micro-label ${styles.header}`}>근거 EVIDENCE — 점수 분해</div>
      {evidence === null && <div className={styles.loading}>로딩 중...</div>}
      {evidence !== null && evidence.length === 0 && (
        <div className={styles.loading}>근거 행 없음 — scoring 파이프라인 미실행 가능성</div>
      )}
      {evidence !== null &&
        evidence.map((e, i) => (
          <div
            key={`${e.src_table}-${e.src_id}-${i}`}
            className={styles.row}
            onClick={() =>
              dispatch({ type: 'ontologyFocus', focus: { table: e.src_table, srcId: e.src_id } })
            }
          >
            <div className={styles.line1}>
              <span className={styles.term}>{e.term}</span>
              <span className={`mono ${styles.points}`}>
                {e.points >= 0 ? '+' : ''}
                {e.points.toFixed(1)}
              </span>
            </div>
            {e.detail && <div className={styles.detail}>{e.detail}</div>}
            <div className={`mono ${styles.provenance}`}>
              {e.src_table}:{e.src_id}
              {e.provenance?.fetched_at ? ` ${e.provenance.fetched_at.slice(0, 16)}` : ''}
            </div>
          </div>
        ))}
      {evidence !== null && evidence.length > 0 && (
        <div className={`mono ${styles.total}`}>{`Σ ${total.toFixed(1)}`}</div>
      )}
    </div>
  );
}
