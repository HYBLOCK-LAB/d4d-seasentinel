import { useEffect, useState } from 'react';
import { useAppState } from '../state/AppState';
import styles from './OsintPanel.module.css';

interface OsintItem {
  id: string;
  ts: string;
  kind: string;
  lang: string;
  text: string;
  source: string;
  sentiment: number | null;
  weight: number | null;
}

interface OsintResponse {
  items: OsintItem[];
}

function sentimentColor(sentiment: number): string {
  if (sentiment < -0.2) return 'var(--crit)';
  if (sentiment > 0.2) return 'var(--accent)';
  return 'var(--text-3)';
}

export function OsintPanel(): JSX.Element {
  const state = useAppState();
  const { regionId, window: timeWindow } = state;

  const [items, setItems] = useState<OsintItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    async function run(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          region: regionId,
          start: timeWindow.start,
          end: timeWindow.end,
        });
        const res = await fetch(`/api/osint?${params.toString()}`);
        if (!res.ok) throw new Error(`OSINT 조회 실패 (${res.status})`);
        const data = (await res.json()) as OsintResponse;
        if (!cancelled) setItems(data.items);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'OSINT 조회 실패');
          setItems([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [regionId, timeWindow.start, timeWindow.end]);

  function toggleExpanded(id: string): void {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className="micro-label">{`OSINT 첩보 · ${items.length}건`}</span>
      </div>
      <div className={styles.list}>
        {loading ? (
          <div className={styles.empty}>로딩 중...</div>
        ) : error ? (
          <div className={styles.empty}>{error}</div>
        ) : items.length === 0 ? (
          <div className={styles.empty}>해당 기간 OSINT 없음</div>
        ) : (
          items.map((item) => {
            const isExpanded = expandedIds.has(item.id);
            const hasMeta = item.sentiment !== null || item.weight !== null;
            return (
              <div
                key={item.id}
                className={styles.row}
                onClick={() => toggleExpanded(item.id)}
              >
                <div className={styles.line1}>
                  <span className={styles.chipKind}>{item.kind}</span>
                  <span className={styles.chipLang}>{item.lang}</span>
                  <span className={`${styles.ts} mono`}>{item.ts.slice(0, 16)}</span>
                </div>
                <div
                  className={
                    isExpanded ? `${styles.text} ${styles.textExpanded}` : styles.text
                  }
                >
                  {item.text}
                </div>
                {hasMeta && (
                  <div className={styles.line3}>
                    <span className="mono">
                      {item.sentiment !== null && (
                        <span style={{ color: sentimentColor(item.sentiment) }}>
                          {`sent ${item.sentiment.toFixed(2)}`}
                        </span>
                      )}
                      {item.sentiment !== null && item.weight !== null ? ' · ' : ''}
                      {item.weight !== null && <span>{`w ${item.weight.toFixed(2)}`}</span>}
                    </span>
                    <span className={styles.source}>{item.source}</span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
