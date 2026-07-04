import { useCallback, useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { api } from '../api/client';
import { useAppDispatch, useAppState, useRegion } from '../state/AppState';
import { IconButton } from '../design/components';
import styles from './Timebar.module.css';

type Domain = { start: string; end: string };
type PresetKey = '72H' | '30D' | '1Y' | 'ALL';
type TimelineBucket = Awaited<ReturnType<typeof api.timeline>>['buckets'][number];
type DragState = { startX: number; currentX: number; moved: boolean };

const PRESET_KEYS: PresetKey[] = ['72H', '30D', '1Y', 'ALL'];
const HOUR_MS = 3600000;
const DAY_MS = 86400000;
const PRESET_MS: Record<Exclude<PresetKey, 'ALL'>, number> = {
  '72H': 72 * HOUR_MS,
  '30D': 30 * DAY_MS,
  '1Y': 365 * DAY_MS,
};
const DAY_BUCKET_THRESHOLD_MS = 14 * DAY_MS;
const PLAY_INTERVAL_MS = 800;
const DRAG_THRESHOLD_PX = 3;

const COLOR_ACCENT = '#35e0c2';
const COLOR_ACCENT_80 = 'rgba(53,224,194,0.8)';
const COLOR_ACCENT_20 = 'rgba(53,224,194,0.2)';
const COLOR_ACCENT_10 = 'rgba(53,224,194,0.1)';
const COLOR_CRIT = '#ff5a4d';
const COLOR_OSINT = '#94b2d1';
const COLOR_DIM = 'rgba(10,18,32,0.45)';
const COLOR_HAIRLINE = 'rgba(148,178,209,0.14)';

function formatEdgeLabel(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatSpan(ms: number): string {
  const hours = ms / HOUR_MS;
  if (hours < 48) return `${Math.max(1, Math.round(hours))}h`;
  const days = hours / 24;
  if (days < 60) return `${Math.round(days)}d`;
  return `${(days / 365).toFixed(1)}y`;
}

const SPEEDS = [0.5, 1, 2, 4];

export function Timebar() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const region = useRegion();

  const [domain, setDomain] = useState<Domain>(() => ({ ...state.fullRange }));
  const [activePreset, setActivePreset] = useState<PresetKey>('ALL');
  const [buckets, setBuckets] = useState<TimelineBucket[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    if (activePreset === 'ALL') setDomain({ ...state.fullRange });
  }, [activePreset, state.fullRange]);

  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<DragState | null>(null);

  const domainSpanMs = Math.max(new Date(domain.end).getTime() - new Date(domain.start).getTime(), 1);
  const bucketUnit: 'hour' | 'day' = domainSpanMs > DAY_BUCKET_THRESHOLD_MS ? 'day' : 'hour';

  useEffect(() => {
    let cancelled = false;
    api
      .timeline({ region: region.id, start: domain.start, end: domain.end }, bucketUnit)
      .then((res) => {
        if (!cancelled) setBuckets(res.buckets);
      })
      .catch(() => {
        if (!cancelled) setBuckets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [region.id, domain.start, domain.end, bucketUnit]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.width / dpr;
    const height = canvas.height / dpr;

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    if (buckets.length === 0) {
      ctx.strokeStyle = COLOR_HAIRLINE;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, Math.round(height / 2) + 0.5);
      ctx.lineTo(width, Math.round(height / 2) + 0.5);
      ctx.stroke();
      ctx.restore();
      return;
    }

    const domainStartMs = new Date(domain.start).getTime();
    const timeToX = (t: number) => ((t - domainStartMs) / domainSpanMs) * width;
    const bucketSpanMs = bucketUnit === 'day' ? DAY_MS : HOUR_MS;
    const barWidth = Math.max((bucketSpanMs / domainSpanMs) * width, 1);

    const maxAis = Math.max(1, ...buckets.map((b) => b.ais));
    const maxOsint = Math.max(1, ...buckets.map((b) => b.osint));
    const barAreaTop = 10;
    const barAreaHeight = Math.max(height - barAreaTop - 4, 1);

    for (const bucket of buckets) {
      const x = timeToX(new Date(bucket.t).getTime());
      const osintH = barAreaHeight * (Math.log(1 + bucket.osint) / Math.log(1 + maxOsint));
      const osintWidth = Math.max(barWidth * 0.4, 1);
      ctx.fillStyle = COLOR_OSINT;
      ctx.fillRect(x + (barWidth - osintWidth) / 2, barAreaTop + barAreaHeight - osintH, osintWidth, osintH);

      const aisH = barAreaHeight * (Math.log(1 + bucket.ais) / Math.log(1 + maxAis));
      ctx.fillStyle = COLOR_ACCENT_80;
      ctx.fillRect(x, barAreaTop + barAreaHeight - aisH, barWidth, aisH);
    }

    ctx.fillStyle = COLOR_CRIT;
    for (const bucket of buckets) {
      if (bucket.alerts <= 0) continue;
      const x = timeToX(new Date(bucket.t).getTime()) + barWidth / 2;
      ctx.beginPath();
      ctx.arc(x, 6, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }

    const winStartMs = new Date(state.window.start).getTime();
    const winEndMs = new Date(state.window.end).getTime();
    const winX0 = Math.max(0, Math.min(width, timeToX(winStartMs)));
    const winX1 = Math.max(0, Math.min(width, timeToX(winEndMs)));

    if (winX0 > 0) {
      ctx.fillStyle = COLOR_DIM;
      ctx.fillRect(0, 0, winX0, height);
    }
    if (winX1 < width) {
      ctx.fillStyle = COLOR_DIM;
      ctx.fillRect(winX1, 0, width - winX1, height);
    }

    ctx.fillStyle = COLOR_ACCENT_10;
    ctx.fillRect(winX0, 0, Math.max(winX1 - winX0, 0), height);
    ctx.strokeStyle = COLOR_ACCENT;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.round(winX0) + 0.5, 0);
    ctx.lineTo(Math.round(winX0) + 0.5, height);
    ctx.moveTo(Math.round(winX1) - 0.5, 0);
    ctx.lineTo(Math.round(winX1) - 0.5, height);
    ctx.stroke();

    const drag = dragRef.current;
    if (drag) {
      const dragX0 = Math.min(drag.startX, drag.currentX);
      const dragX1 = Math.max(drag.startX, drag.currentX);
      ctx.fillStyle = COLOR_ACCENT_20;
      ctx.fillRect(dragX0, 0, dragX1 - dragX0, height);
    }

    ctx.restore();
  }, [domain, domainSpanMs, buckets, bucketUnit, state.window]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      draw();
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [draw]);

  useEffect(() => {
    if (!state.playing) return;
    const id = window.setInterval(() => {
      const startMs = new Date(state.window.start).getTime();
      const endMs = new Date(state.window.end).getTime();
      const spanMs = Math.max(endMs - startMs, 1);
      const step = spanMs / 3;
      const domainEndMs = new Date(domain.end).getTime();
      let nextStart = startMs + step;
      let nextEnd = endMs + step;
      if (nextEnd >= domainEndMs) {
        nextEnd = domainEndMs;
        nextStart = nextEnd - spanMs;
        dispatch({
          type: 'window',
          window: { start: new Date(nextStart).toISOString(), end: new Date(nextEnd).toISOString() },
        });
        dispatch({ type: 'playing', on: false });
        return;
      }
      dispatch({
        type: 'window',
        window: { start: new Date(nextStart).toISOString(), end: new Date(nextEnd).toISOString() },
      });
    }, PLAY_INTERVAL_MS / speed);
    return () => window.clearInterval(id);
  }, [state.playing, state.window, domain.end, dispatch, speed]);

  const applyPreset = useCallback(
    (key: PresetKey) => {
      setActivePreset(key);
      if (key === 'ALL') {
        setDomain({ start: state.fullRange.start, end: state.fullRange.end });
        return;
      }
      const windowEndMs = new Date(state.window.end).getTime();
      const fullStartMs = new Date(state.fullRange.start).getTime();
      const startMs = Math.max(fullStartMs, windowEndMs - PRESET_MS[key]);
      setDomain({ start: new Date(startMs).toISOString(), end: new Date(windowEndMs).toISOString() });
    },
    [state.window.end, state.fullRange.start, state.fullRange.end]
  );

  const handleCanvasMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    dragRef.current = { startX: x, currentX: x, moved: false };
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const drag = dragRef.current;
      if (!drag) return;
      drag.currentX = x;
      if (!drag.moved && Math.abs(x - drag.startX) > DRAG_THRESHOLD_PX) drag.moved = true;
      draw();
    };

    const handleUp = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const width = Math.max(rect.width, 1);
      const domainStartMs = new Date(domain.start).getTime();
      const domainEndMs = new Date(domain.end).getTime();
      const span = Math.max(domainEndMs - domainStartMs, 1);
      const xToTime = (px: number) => domainStartMs + (px / width) * span;
      const drag = dragRef.current;

      if (drag && drag.moved) {
        const t0 = xToTime(Math.min(drag.startX, x));
        const t1 = xToTime(Math.max(drag.startX, x));
        const minSpan = bucketUnit === 'day' ? DAY_MS : HOUR_MS;
        const clampedStart = Math.max(domainStartMs, t0);
        let clampedEnd = Math.min(domainEndMs, t1);
        if (clampedEnd - clampedStart < minSpan) clampedEnd = Math.min(domainEndMs, clampedStart + minSpan);
        dispatch({
          type: 'window',
          window: { start: new Date(clampedStart).toISOString(), end: new Date(clampedEnd).toISOString() },
        });
      } else {
        const clickTime = xToTime(x);
        const currentSpan = Math.max(
          new Date(state.window.end).getTime() - new Date(state.window.start).getTime(),
          1
        );
        let newStart = clickTime - currentSpan / 2;
        let newEnd = clickTime + currentSpan / 2;
        if (newStart < domainStartMs) {
          newStart = domainStartMs;
          newEnd = newStart + currentSpan;
        }
        if (newEnd > domainEndMs) {
          newEnd = domainEndMs;
          newStart = newEnd - currentSpan;
        }
        dispatch({
          type: 'window',
          window: { start: new Date(newStart).toISOString(), end: new Date(newEnd).toISOString() },
        });
      }

      dragRef.current = null;
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isDragging, domain, bucketUnit, state.window, dispatch, draw]);

  const windowSpanMs = Math.max(
    new Date(state.window.end).getTime() - new Date(state.window.start).getTime(),
    0
  );

  return (
    <div className={styles.root}>
      <div className={styles.controls}>
        <IconButton
          active={state.playing}
          title={state.playing ? '일시정지' : '재생'}
          onClick={() => dispatch({ type: 'playing', on: !state.playing })}
        >
          {state.playing ? <Pause size={14} /> : <Play size={14} />}
        </IconButton>
        <button
          type="button"
          className={`${styles.presetBtn} mono`}
          title="재생 속도"
          onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] as number)}
        >
          {speed}×
        </button>
        <div className={styles.presets}>
          {PRESET_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className={
                activePreset === key ? `${styles.presetBtn} ${styles.presetBtnActive}` : styles.presetBtn
              }
              onClick={() => applyPreset(key)}
            >
              {key}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.main}>
        <div className={styles.histWrap} ref={containerRef}>
          <canvas ref={canvasRef} className={styles.canvas} onMouseDown={handleCanvasMouseDown} />
          {buckets.length === 0 && <div className={styles.emptyLabel}>데이터 없음</div>}
        </div>
        <div className={styles.labels}>
          <span className={`${styles.edgeLabel} mono micro-label`}>{formatEdgeLabel(domain.start)}</span>
          <span className={`${styles.centerLabel} mono`}>
            {formatEdgeLabel(state.window.start)} ~ {formatEdgeLabel(state.window.end)} ({formatSpan(windowSpanMs)})
          </span>
          <span className={`${styles.edgeLabel} mono micro-label`}>{formatEdgeLabel(domain.end)}</span>
        </div>
      </div>
    </div>
  );
}
