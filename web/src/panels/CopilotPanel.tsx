import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { SendHorizonal } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppState } from '../state/AppState';
import { api, copilotStream } from '../api/client';
import styles from './CopilotPanel.module.css';

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

const PRESETS = [
  '지난 24시간 해저케이블 인근 다크선박 있나?',
  '부산 입항 예정 선박 중 최고위험 표적은?',
  '제재회피 STS 환적 정황을 요약해줘',
  '이 해역에서 지금 가장 위험한 표적 3개는?',
];

export function CopilotPanel() {
  const state = useAppState();
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.models().then((res) => {
      setModels(res.models);
      setModel(res.default);
    });
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  async function handleSend(override?: string) {
    const query = (override ?? input).trim();
    if (!query || streaming) {
      return;
    }
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: query }, { role: 'assistant', text: '' }]);
    setStreaming(true);
    const context = `region=${state.regionId} window=${state.window.start}..${state.window.end}${
      state.selectedThreatId ? ` selected_threat=${state.selectedThreatId}` : ''
    }`;
    try {
      await copilotStream({ query, context, model }, (delta) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (!last) return prev;
          next[next.length - 1] = { role: last.role, text: last.text + delta };
          return next;
        });
      });
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: 'assistant', text: '[게이트웨이 오류]' };
        return next;
      });
    } finally {
      setStreaming(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  const showPresets = !streaming && messages.length === 0;

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <select className={`${styles.select} mono`} value={model} onChange={(e) => setModel(e.target.value)}>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      {showPresets ? (
        <div className={styles.presets}>
          {PRESETS.map((preset) => (
            <button key={preset} className={`${styles.presetChip} mono`} onClick={() => void handleSend(preset)}>
              {preset}
            </button>
          ))}
        </div>
      ) : null}
      <div className={styles.list} ref={listRef}>
        {messages.map((message, index) => (
          <div key={index} className={message.role === 'user' ? styles.userMsg : styles.assistantMsg}>
            {message.role === 'assistant' ? <span className={`${styles.label} micro-label`}>ANALYST</span> : null}
            <div className={styles.text}>{message.text}</div>
          </div>
        ))}
      </div>
      <div className={styles.inputRow}>
        <textarea
          className={`${styles.textarea} mono`}
          rows={2}
          value={input}
          placeholder="질의를 입력하세요"
          disabled={streaming}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <IconButton title="전송" onClick={() => void handleSend()}>
          <SendHorizonal size={14} />
        </IconButton>
      </div>
    </div>
  );
}
