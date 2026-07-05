import { useEffect, useState } from 'react';
import { Moon, Sun, Cpu, RefreshCw, FlaskConical, SlidersHorizontal } from 'lucide-react';
import { useAppState, useAppDispatch } from '../state/AppState';
import { api } from '../api/client';
import type { DatasetInfo, ScoringDetector } from '../api/types';
import styles from './SettingsPanel.module.css';

const TIER_KO: Record<string, string> = {
  identity: '신원',
  asset: '자산',
  behavior: '행동',
  context: '맥락',
  mitigating: '감점',
};

function ScoringSection() {
  const dispatch = useAppDispatch();
  const [detectors, setDetectors] = useState<ScoringDetector[]>([]);
  const [dirty, setDirty] = useState<Record<string, Partial<ScoringDetector>>>({});
  const [status, setStatus] = useState('');

  useEffect(() => {
    api.scoringConfig().then((res) => setDetectors(res.detectors), () => setStatus('설정 조회 실패'));
  }, []);

  function patch(name: string, fields: Partial<ScoringDetector>) {
    setDetectors((cur) => cur.map((d) => (d.name === name ? { ...d, ...fields } : d)));
    setDirty((cur) => ({ ...cur, [name]: { ...cur[name], ...fields } }));
  }

  function save() {
    const changes = Object.entries(dirty).map(([name, fields]) => ({ name, ...fields }));
    if (!changes.length) return;
    setStatus('저장 중...');
    api
      .updateScoring(changes)
      .then(() => api.rerunScoring())
      .then(() => {
        setDirty({});
        setStatus('저장됨 — 재분석 실행 중 (수 분 내 반영)');
        window.setTimeout(() => dispatch({ type: 'triggerThreatsRefresh' }), 60_000);
      })
      .catch(() => setStatus('저장 실패'));
  }

  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className="micro-label">위협 기준 SCORING</span>
      </div>
      <div className={styles.detList}>
        {detectors.map((d) => (
          <div key={d.name} className={styles.detRow} title={d.rationale_ko ?? ''}>
            <input
              type="checkbox"
              checked={d.enabled}
              onChange={(e) => patch(d.name, { enabled: e.target.checked })}
            />
            <span className={styles.detName}>
              {d.label_ko}
              {d.tier && <em className={styles.detTier}>{TIER_KO[d.tier] ?? d.tier}</em>}
            </span>
            <input
              className={`${styles.detNum} mono`}
              type="number"
              step="0.1"
              value={d.weight}
              title="가중치"
              onChange={(e) => patch(d.name, { weight: Number(e.target.value) })}
            />
            {d.points != null && (
              <input
                className={`${styles.detNum} mono`}
                type="number"
                step="1"
                value={d.points}
                title="기본 점수"
                onChange={(e) => patch(d.name, { points: Number(e.target.value) })}
              />
            )}
          </div>
        ))}
      </div>
      <button
        type="button"
        className={styles.toggle}
        disabled={!Object.keys(dirty).length}
        onClick={save}
      >
        <SlidersHorizontal size={14} />
        <span className="mono">저장 + 재분석</span>
      </button>
      <p className={styles.caption}>{status || '행에 마우스를 올리면 배점 근거(티어) 설명이 표시됩니다. 변경 이력은 위협 추이에 기준 변경 눈금으로 표시됩니다.'}</p>
    </section>
  );
}

export function SettingsPanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const { settings } = state;

  const [models, setModels] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.models().then((res) => {
      if (cancelled) return;
      setModels(res.models);
      setDefaultModel(res.default);
    });
    api.datasets().then((res) => {
      if (!cancelled) setDatasets(res.datasets);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedModel = settings.model || defaultModel;
  const selectedDataset = settings.dataset || 'live';
  const datasetInfo = datasets.find((d) => d.id === selectedDataset);

  function handleDatasetChange(id: string) {
    const info = datasets.find((d) => d.id === id);
    dispatch({
      type: 'settings',
      patch: {
        dataset: id === 'live' ? '' : id,
        datasetLabel: id === 'live' ? '' : (info?.name_ko ?? id),
      },
    });
  }

  return (
    <div className={styles.panel}>
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className="micro-label">데이터셋 DATASET</span>
        </div>
        <div className={styles.modelRow}>
          <FlaskConical size={14} className={styles.modelIcon} />
          <select
            className={styles.select}
            value={selectedDataset}
            onChange={(e) => handleDatasetChange(e.target.value)}
          >
            {datasets.length === 0 && <option value="live">실데이터 (LIVE)</option>}
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name_ko}
              </option>
            ))}
          </select>
        </div>
        <p className={styles.caption}>
          {datasetInfo?.description ?? '실데이터가 기본값 — 백테스트용 시나리오 데이터셋을 선택하면 전체 온톨로지가 교체됩니다'}
        </p>
      </section>

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

      <ScoringSection />

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
