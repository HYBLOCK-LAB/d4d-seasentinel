import { useEffect, useRef, useState } from 'react';
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

interface DigestItem {
  category: string;
  summary_ko: string;
  time_hint: string;
  area_hint: string;
  severity: number;
  evidence_ids: string[];
}

interface DigestResponse {
  items: DigestItem[];
  note?: string;
  input_count: number;
  error?: string;
}

type OsintMode = 'raw' | 'llm';

function sentimentColor(sentiment: number): string {
  if (sentiment < -0.2) return 'var(--crit)';
  if (sentiment > 0.2) return 'var(--accent)';
  return 'var(--text-3)';
}

function categoryColor(category: string): string {
  if (category === 'infra_threat') return 'var(--crit)';
  if (category === 'militia_movement' || category === 'sanctions_evasion') return 'var(--warn)';
  return 'var(--accent)';
}

export function OsintPanel(): JSX.Element {
  const state = useAppState();
  const { regionId, window: timeWindow } = state;

  const [mode, setMode] = useState<OsintMode>('raw');

  const [items, setItems] = useState<OsintItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [digestLoading, setDigestLoading] = useState<boolean>(false);

  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

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

  useEffect(() => {
    if (mode !== 'llm') return undefined;
    let cancelled = false;

    async function run(): Promise<void> {
      setDigestLoading(true);
      try {
        const res = await fetch('/api/osint/digest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            region: regionId,
            start: timeWindow.start,
            end: timeWindow.end,
          }),
        });
        const data = (await res.json()) as DigestResponse;
        if (!cancelled) setDigest(data);
      } catch (err) {
        if (!cancelled) {
          setDigest({
            items: [],
            input_count: 0,
            error: err instanceof Error ? err.message : 'digest_failed',
          });
        }
      } finally {
        if (!cancelled) setDigestLoading(false);
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [mode, regionId, timeWindow.start, timeWindow.end]);

  useEffect(() => {
    if (!highlightId) return undefined;
    const el = rowRefs.current.get(highlightId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const timer = setTimeout(() => setHighlightId(null), 2600);
    return () => clearTimeout(timer);
  }, [highlightId]);

  function setRowRef(id: string) {
    return (el: HTMLDivElement | null): void => {
      if (el) rowRefs.current.set(id, el);
      else rowRefs.current.delete(id);
    };
  }

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

  function handleEvidenceClick(id: string): void {
    setMode('raw');
    setExpandedIds((prev) => new Set(prev).add(id));
    setHighlightId(id);
  }

  function renderRaw(): JSX.Element {
    if (loading) {
      return <div className={styles.empty}>로딩 중...</div>;
    }
    if (error) {
      return <div className={styles.empty}>{error}</div>;
    }
    if (items.length === 0) {
      return <div className={styles.empty}>해당 기간 OSINT 없음</div>;
    }
    return (
      <>
        {items.map((item) => {
          const isExpanded = expandedIds.has(item.id);
          const isHighlighted = highlightId === item.id;
          const hasMeta = item.sentiment !== null || item.weight !== null;
          return (
            <div
              key={item.id}
              ref={setRowRef(item.id)}
              className={
                isHighlighted ? `${styles.row} ${styles.rowHighlight}` : styles.row
              }
              onClick={() => toggleExpanded(item.id)}
            >
              <div className={styles.line1}>
                <span className={styles.chipKind}>{item.kind}</span>
                <span className={styles.chipLang}>{item.lang}</span>
                <span className={`${styles.ts} mono`}>{item.ts.slice(0, 16)}</span>
              </div>
              <div
                className={isExpanded ? `${styles.text} ${styles.textExpanded}` : styles.text}
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
        })}
      </>
    );
  }

  function renderLlm(): JSX.Element {
    if (digestLoading) {
      return <div className={styles.empty}>분석 중... (LLM)</div>;
    }
    if (!digest || digest.error || digest.items.length === 0) {
      return <div className={styles.empty}>분석 결과 없음</div>;
    }
    return (
      <>
        <div className={`${styles.noticeBar} mono`}>
          {`LLM 생성 분석 — 근거 원문 확인 필수 · 입력 ${digest.input_count}건`}
        </div>
        {digest.items.map((d, idx) => {
          const color = categoryColor(d.category);
          return (
            <div key={`${d.category}-${idx}`} className={styles.digestItem}>
              <div className={styles.line1}>
                <span className={styles.categoryChip} style={{ color, borderColor: color }}>
                  {d.category}
                </span>
                <div className={styles.severityBar}>
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span
                      key={i}
                      className={styles.severitySeg}
                      style={{ background: i < d.severity ? color : 'var(--bg-3)' }}
                    />
                  ))}
                </div>
              </div>
              <div className={styles.summary}>{d.summary_ko}</div>
              <div className={`${styles.metaMono} mono`}>{`${d.time_hint} · ${d.area_hint}`}</div>
              {d.evidence_ids.length > 0 && (
                <div className={styles.evidenceRow}>
                  {d.evidence_ids.map((eid) => (
                    <button
                      key={eid}
                      type="button"
                      className={`${styles.evidenceChip} mono`}
                      onClick={() => handleEvidenceClick(eid)}
                    >
                      {eid}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className="micro-label">{`OSINT 첩보 · ${items.length}건`}</span>
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={
              mode === 'raw' ? `${styles.modeBtn} ${styles.modeBtnActive}` : styles.modeBtn
            }
            onClick={() => setMode('raw')}
          >
            원문
          </button>
          <button
            type="button"
            className={
              mode === 'llm' ? `${styles.modeBtn} ${styles.modeBtnActive}` : styles.modeBtn
            }
            onClick={() => setMode('llm')}
          >
            LLM 분석
          </button>
        </div>
      </div>
      <div className={styles.list}>{mode === 'raw' ? renderRaw() : renderLlm()}</div>
    </div>
  );
}
