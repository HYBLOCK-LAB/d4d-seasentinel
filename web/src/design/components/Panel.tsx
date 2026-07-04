import type { PropsWithChildren, ReactNode } from 'react';
import styles from './Panel.module.css';

interface PanelProps extends PropsWithChildren {
  header?: ReactNode;
  noPad?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function Panel({ header, noPad, className, style, children }: PanelProps) {
  return (
    <section className={[styles.panel, className].filter(Boolean).join(' ')} style={style}>
      {header}
      <div className={[styles.body, noPad ? styles.noPad : ''].filter(Boolean).join(' ')}>
        {children}
      </div>
    </section>
  );
}
