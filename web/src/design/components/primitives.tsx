import type { ButtonHTMLAttributes, ReactNode } from 'react'
import styles from './primitives.module.css'

const LEVEL_CLASS: Record<string, string | undefined> = {
  CRITICAL: styles.crit,
  ALERT: styles.crit,
  HIGH: styles.warn,
  WATCH: styles.warn,
  MED: styles.med,
  LOW: styles.neutral,
}

export function Badge({ level, children }: { level?: string; children: ReactNode }) {
  const cls = (level && LEVEL_CLASS[level]) || styles.neutral
  return <span className={[styles.badge, cls].join(' ')}>{children}</span>
}

export function ScoreBar({ score }: { score: number }) {
  const v = Math.max(0, Math.min(100, score))
  const cls = v >= 90 ? styles.crit : v >= 75 ? styles.warn : styles.accent
  return (
    <span className={styles.scoreBar} title={`${v.toFixed(0)}/100`}>
      <span className={[styles.scoreFill, cls].join(' ')} style={{ width: `${v}%` }} />
    </span>
  )
}

export function Toggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      className={[styles.toggle, on ? styles.toggleOn : ''].join(' ')}
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
    >
      <span className={styles.knob} />
    </button>
  )
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean
}

export function IconButton({ active, className, children, ...rest }: IconButtonProps) {
  return (
    <button
      className={[styles.iconBtn, active ? styles.iconBtnActive : '', className]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Kpi({ value, label, tone }: { value: ReactNode; label: string; tone?: 'accent' | 'warn' | 'crit' }) {
  return (
    <div className={styles.kpi}>
      <div className={[styles.kpiValue, tone ? styles[tone] : ''].filter(Boolean).join(' ')}>{value}</div>
      <div className={styles.kpiLabel}>{label}</div>
    </div>
  )
}
