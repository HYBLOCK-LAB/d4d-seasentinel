import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { SendHorizonal } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppDispatch, useAppState } from '../state/AppState';
import { api } from '../api/client';
import styles from './CopilotPanel.module.css';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  toolChips?: string[];
}

const PRESETS = [
  '지난 24시간 해저케이블 인근 다크선박 있나?',
  '부산 입항 예정 선박 중 최고위험 표적은?',
  '제재회피 STS 환적 정황을 요약해줘',
  '이 해역에서 지금 가장 위험한 표적 3개는?',
];

const TOOLS = [
  {
    type: 'function',
    function: {
      name: 'set_region',
      description: '지도 표시 해역을 변경한다',
      parameters: {
        type: 'object',
        properties: {
          region_id: { type: 'string', enum: ['west_sea', 'south_china_sea', 'baltic'] },
        },
        required: ['region_id'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_time_window',
      description: '조회 시간창을 변경한다 (ISO8601)',
      parameters: {
        type: 'object',
        properties: { start: { type: 'string' }, end: { type: 'string' } },
        required: ['start', 'end'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'toggle_layer',
      description: '지도 레이어를 켜거나 끈다',
      parameters: {
        type: 'object',
        properties: {
          layer_id: {
            type: 'string',
            enum: ['ais_points', 'tracks', 'alerts_geo', 'events', 'zones', 'cables', 'ports'],
          },
          on: { type: 'boolean' },
        },
        required: ['layer_id', 'on'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'focus_map',
      description: '지도를 특정 좌표로 이동한다',
      parameters: {
        type: 'object',
        properties: { lon: { type: 'number' }, lat: { type: 'number' } },
        required: ['lon', 'lat'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'select_threat',
      description: '위협 목록에서 특정 위협을 선택해 근거를 펼친다',
      parameters: {
        type: 'object',
        properties: { threat_id: { type: 'string' } },
        required: ['threat_id'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'open_panel',
      description: '우측 패널을 연다',
      parameters: {
        type: 'object',
        properties: { panel: { type: 'string', enum: ['ontology', 'osint', 'copilot', 'settings'] } },
        required: ['panel'],
      },
    },
  },
];

type OpenAiMessage = Record<string, unknown>;

export function CopilotPanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const [defaultModel, setDefaultModel] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const convoRef = useRef<OpenAiMessage[]>([]);

  const settingsModel = (state as unknown as { settings?: { model?: string } }).settings?.model ?? '';
  const model = settingsModel || defaultModel;

  useEffect(() => {
    api.models().then((res) => setDefaultModel(res.default));
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  function executeTool(name: string, args: Record<string, unknown>): string {
    switch (name) {
      case 'set_region':
        dispatch({ type: 'region', regionId: String(args.region_id) });
        return `해역을 ${args.region_id}(으)로 변경했습니다`;
      case 'set_time_window':
        dispatch({ type: 'window', window: { start: String(args.start), end: String(args.end) } });
        return `시간창을 ${args.start} ~ ${args.end}(으)로 설정했습니다`;
      case 'toggle_layer':
        dispatch({ type: 'layer', id: String(args.layer_id), on: Boolean(args.on) });
        return `레이어 ${args.layer_id}=${args.on ? 'on' : 'off'}`;
      case 'focus_map':
        dispatch({ type: 'focus', target: { lon: Number(args.lon), lat: Number(args.lat) } });
        return `지도를 (${args.lon}, ${args.lat})로 이동했습니다`;
      case 'select_threat':
        dispatch({ type: 'selectThreat', id: String(args.threat_id) });
        return `위협 ${args.threat_id}을(를) 선택했습니다`;
      case 'open_panel':
        dispatch({ type: 'rightPanel', panel: args.panel as 'ontology' | 'osint' | 'copilot' });
        return `${args.panel} 패널을 열었습니다`;
      default:
        return `알 수 없는 도구: ${name}`;
    }
  }

  async function agentCall(convo: OpenAiMessage[]): Promise<OpenAiMessage> {
    const res = await fetch('/api/copilot/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: convo, model: model || undefined, tools: TOOLS }),
    });
    if (!res.ok) throw new Error(`agent ${res.status}`);
    const data = (await res.json()) as { message: OpenAiMessage };
    return data.message;
  }

  async function handleSend(override?: string) {
    const query = (override ?? input).trim();
    if (!query || streaming) {
      return;
    }
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: query }]);
    setStreaming(true);
    const context = `region=${state.regionId} window=${state.window.start}..${state.window.end}${
      state.selectedThreatId ? ` selected_threat=${state.selectedThreatId}` : ''
    }`;
    convoRef.current.push({
      role: 'user',
      content: `[현재 상황 컨텍스트]\n${context}\n\n[지휘관 질의]\n${query}`,
    });
    const chips: string[] = [];
    try {
      for (let round = 0; round < 4; round += 1) {
        const message = await agentCall(convoRef.current);
        const toolCalls = (message.tool_calls ?? []) as Array<{
          id: string;
          function: { name: string; arguments: string };
        }>;
        convoRef.current.push(message);
        if (!toolCalls.length) {
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', text: String(message.content ?? ''), toolChips: [...chips] },
          ]);
          break;
        }
        for (const call of toolCalls) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(call.function.arguments || '{}') as Record<string, unknown>;
          } catch {
            args = {};
          }
          const result = executeTool(call.function.name, args);
          chips.push(`${call.function.name} 실행`);
          convoRef.current.push({ role: 'tool', tool_call_id: call.id, content: result });
        }
        if (round === 3) {
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', text: '(도구 실행 완료)', toolChips: [...chips] },
          ]);
        }
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', text: '[게이트웨이 오류]' }]);
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
            {message.toolChips?.length ? (
              <div>
                {message.toolChips.map((chip, i) => (
                  <span key={i} className={styles.toolChip}>
                    {chip}
                  </span>
                ))}
              </div>
            ) : null}
            <div className={styles.text}>{message.text}</div>
          </div>
        ))}
        {streaming ? <div className={`${styles.label} micro-label`}>분석 중...</div> : null}
      </div>
      <div className={styles.inputRow}>
        <textarea
          className={`${styles.textarea} mono`}
          rows={2}
          value={input}
          placeholder="질의 또는 화면 조작 지시 (예: 남중국해로 이동해줘)"
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
