import { useEffect, useState } from 'react';
import { Moon, Sun, Cpu, RefreshCw } from 'lucide-react';
import { useAppState, useAppDispatch } from '../state/AppState';
import { api } from '../api/client';
import styles from './SettingsPanel.module.css';

export function SettingsPanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const { settings } = state;

  const [models, setModels] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState('');

  useEffect(() => {
    let cancelled = false;
    api.models().then((res) => {
      if (cancelled) return;
      setModels(res.models);
      setDefaultModel(res.default);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedModel = settings.model || defaultModel;

  return (
    <div className={styles.panel}>
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className="micro-label">표시 THEME</span>
        </div>
        <div className={styles.themeRow}>
          <button
            type="button"
            className={`${styles.themeButton} ${settings.theme === 'dark' ? styles.themeButtonActive : ''}`}
            onClick={() => dispatch({ type: 'settings', patch: { theme: 'dark' } })}
          >
            <Moon size={14} />
            다크
          </button>
          <button
            type="button"
            className={`${styles.themeButton} ${settings.theme === 'light' ? styles.themeButtonActive : ''}`}
            onClick={() => dispatch({ type: 'settings', patch: { theme: 'light' } })}
          >
            <Sun size={14} />
            라이트
          </button>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className="micro-label">LLM 모델</span>
        </div>
        <div className={styles.modelRow}>
          <Cpu size={14} className={styles.modelIcon} />
          <select
            className={`${styles.select} mono`}
            value={selectedModel}
            onChange={(e) => dispatch({ type: 'settings', patch: { model: e.target.value } })}
          >
            {models.length === 0 && <option value="">로딩 중...</option>}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <p className={styles.caption}>코파일럿·OSINT 분석에 사용</p>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className="micro-label">자동 갱신 AUTO REFRESH</span>
        </div>
        <button
          type="button"
          className={`${styles.toggle} ${settings.autoRefresh ? styles.toggleOn : styles.toggleOff}`}
          onClick={() => dispatch({ type: 'settings', patch: { autoRefresh: !settings.autoRefresh } })}
        >
          <RefreshCw size={14} />
          <span className="mono">{settings.autoRefresh ? 'ON' : 'OFF'}</span>
        </button>
        <p className={styles.caption}>실시간 창 추적 시 60초 주기 재조회</p>
      </section>
    </div>
  );
}
