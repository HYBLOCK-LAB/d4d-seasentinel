import { useEffect, useRef, useState } from 'react';
import { activeDataset } from '../api/client';
import { useAppState } from '../state/AppState';
import styles from './SitrepCard.module.css';

interface Sitrep {
  body_ko: string | null;
  generated_at: string | null;
  model: string | null;
  threat_sig: string;
  stale: boolean;
}

const POLL_MS = 60_000;

function formatTime(iso: string | null): string {
  if (!iso) return '--:--';
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export default function SitrepCard() {
  const { regionId, settings } = useAppState();
  const [sitrep, setSitrep] = useState<Sitrep | null>(null);
  const [loading, setLoading] = useState(true);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const dataset = activeDataset();
        const res = await fetch(
          `/api/sitrep?region=${encodeURIComponent(regionId)}${
            dataset ? `&dataset=${encodeURIComponent(dataset)}` : ''
          }`,
        );
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as Sitrep;
        if (!cancelled) setSitrep(data);
      } catch {
        if (!cancelled) setSitrep((prev) => (prev ? { ...prev, stale: true } : prev));
      } finally {
        inFlight.current = false;
        if (!cancelled) setLoading(false);
      }
    }
    setSitrep(null);
    setLoading(true);
    void load();
    if (!settings.autoRefresh) {
      return () => {
        cancelled = true;
      };
    }
    const timer = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [regionId, settings.autoRefresh, settings.dataset]);

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={`micro-label ${styles.label}`}>SITREP · 상황보고</span>
        {sitrep?.stale ? <span className={styles.staleBadge}>갱신 실패</span> : null}
        <span className={`mono ${styles.time}`}>{formatTime(sitrep?.generated_at ?? null)} 업데이트</span>
      </div>
      <div className={styles.body}>
        {loading && !sitrep ? (
          <span className={styles.pending}>상황보고 생성 중...</span>
        ) : sitrep?.body_ko ? (
          <p className={styles.text}>{sitrep.body_ko}</p>
        ) : (
          <span className={styles.pending}>보고 없음 — 데이터 수집 대기</span>
        )}
      </div>
    </div>
  );
}
