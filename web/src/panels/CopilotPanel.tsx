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
  {
    type: 'function',
    function: {
      name: 'get_threats',
      description: '현재 해역·시간창의 위협 목록을 조회한다 (score 내림차순 상위 20건 반환)',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_threat_evidence',
      description: '특정 위협의 근거 항목(term·points·원천 테이블·provenance)을 조회한다',
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
      name: 'get_osint',
      description: '현재 해역·시간창의 OSINT 수집 항목(텔레그램·다크웹 등)을 조회한다 (최근 30건)',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_timeline',
      description: '현재 해역·시간창의 시간대별 활동 히스토그램(AIS·OSINT·경보 수)을 조회한다',
      parameters: {
        type: 'object',
        properties: { bucket: { type: 'string', enum: ['hour', 'day'] } },
        required: ['bucket'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'assess_threat',
      description:
        '분석관 확인 결과를 위협도 조정 인자(evidence)로 기록한다. dismiss=위협 아님 확인(-40점), lower=위험 낮음(-20점), raise=위험 상향(+15점). 선박/존 경보에만 적용 가능하며 reason에 확인 내용을 기록한다',
      parameters: {
        type: 'object',
        properties: {
          threat_id: { type: 'string' },
          action: { type: 'string', enum: ['dismiss', 'lower', 'raise'] },
          reason: { type: 'string' },
        },
        required: ['threat_id', 'action', 'reason'],
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

  function windowQs(): string {
    return `region=${encodeURIComponent(state.regionId)}&start=${encodeURIComponent(
      state.window.start,
    )}&end=${encodeURIComponent(state.window.end)}`;
  }

  async function fetchJson(path: string): Promise<unknown> {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${path} ${res.status}`);
    return res.json();
  }

  async function executeTool(name: string, args: Record<string, unknown>): Promise<string> {
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
      case 'get_threats': {
        const data = (await fetchJson(`/api/threats?${windowQs()}`)) as {
          threats: Array<Record<string, unknown>>;
        };
        const top = [...data.threats]
          .sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0))
          .slice(0, 20)
          .map((t) => ({
            id: t.id,
            kind: t.kind,
            type: t.type,
            level: t.level,
            score: t.score,
            title_ko: t.title_ko,
            vessel_id: t.vessel_id,
            aoi_id: t.aoi_id,
            generated_at: t.generated_at,
          }));
        return JSON.stringify({ total: data.threats.length, top });
      }
      case 'get_threat_evidence':
        return JSON.stringify(
          await fetchJson(`/api/threats/${encodeURIComponent(String(args.threat_id))}/evidence`),
        );
      case 'get_osint': {
        const data = (await fetchJson(`/api/osint?${windowQs()}`)) as {
          items: Array<Record<string, unknown>>;
        };
        const items = data.items.slice(0, 30).map((it) => ({
          id: it.id,
          ts: it.ts,
          kind: it.kind,
          source: it.source,
          text: String(it.text ?? '').slice(0, 200),
        }));
        return JSON.stringify({ total: data.items.length, items });
      }
      case 'get_timeline':
        return JSON.stringify(
          await fetchJson(`/api/timeline?${windowQs()}&bucket=${args.bucket === 'day' ? 'day' : 'hour'}`),
        );
      case 'assess_threat': {
        const res = await fetch(`/api/threats/${encodeURIComponent(String(args.threat_id))}/assess`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: args.action, reason: args.reason }),
        });
        if (!res.ok) {
          return `조정 실패 (${res.status}): ${await res.text()}`;
        }
        const data = (await res.json()) as Record<string, unknown>;
        dispatch({ type: 'triggerThreatsRefresh' });
        return JSON.stringify(data);
      }
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
    const context = `now=${new Date().toISOString()} region=${state.regionId} window=${state.window.start}..${state.window.end}${
      state.selectedThreatId ? ` selected_threat=${state.selectedThreatId}` : ''
    }`;
    convoRef.current.push({
      role: 'user',
      content: `[현재 상황 컨텍스트]\n${context}\n\n[지휘관 질의]\n${query}`,
    });
    const chips: string[] = [];
    try {
      for (let round = 0; round < 6; round += 1) {
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
          let result: string;
          try {
            result = await executeTool(call.function.name, args);
          } catch (err) {
            result = `도구 실행 실패: ${err instanceof Error ? err.message : String(err)}`;
          }
          chips.push(`${call.function.name} 실행`);
          convoRef.current.push({ role: 'tool', tool_call_id: call.id, content: result });
        }
        if (round === 5) {
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
