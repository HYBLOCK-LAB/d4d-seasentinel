import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'
import styles from './SectionHeader.module.css'

interface SectionHeaderProps {
  title: string
  actions?: ReactNode
  collapsed?: boolean
  onToggle?: () => void
}

export function SectionHeader({ title, actions, collapsed, onToggle }: SectionHeaderProps) {
  return (
    <div className={styles.header}>
      <div className={styles.titleGroup}>
        {onToggle && (
          <button
            className={[styles.collapseBtn, collapsed ? styles.collapsed : ''].join(' ')}
            onClick={onToggle}
            aria-label={collapsed ? 'expand' : 'collapse'}
          >
            <ChevronDown size={12} />
          </button>
        )}
        <span className={styles.title}>{title}</span>
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  )
}
