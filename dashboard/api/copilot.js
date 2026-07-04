// Vercel serverless — LLM copilot proxy (streaming SSE relay).
// Env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL. Key stays server-side.
const SYSTEM_PROMPT = `당신은 대한민국 해양영역인식(MDA) 지휘결심 지원 분석관입니다.
'SEASENTINEL' 시스템이 제공하는 실시간 상황 컨텍스트(위협 경보·선박·OSINT·현재 시각)를 근거로만 답하세요.

규칙:
- 반드시 한국어로, 지휘관이 즉시 활용할 수 있게 간결하고 구조적으로 답하세요.
- 제공된 컨텍스트에 근거해 답하고, 근거가 된 항목(선박명·경보·OSINT 출처)을 함께 인용하세요.
- 컨텍스트에 없는 사실은 지어내지 마세요. 불확실하면 불확실하다고 명시하세요.
- 필요 시 권고 조치를 제시하세요: 관심표적 지정 / ISR 재촬영 / 경비함 유도·차단 / 채증 패키지 / 지휘보고.
- 4~8문장 또는 짧은 불릿으로. 과장·미사여구 금지.`;

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "method" });
  const { query, context, model } = req.body || {};
  if (!query) return res.status(400).json({ error: "empty query" });
  const base = process.env.LLM_BASE_URL, key = process.env.LLM_API_KEY;
  const mdl = model || process.env.LLM_MODEL || "gpt-5.4";
  if (!base || !key) return res.status(502).json({ error: "no llm config (set LLM_BASE_URL / LLM_API_KEY)" });
  const user = `[현재 상황 컨텍스트]\n${context || ""}\n\n[지휘관 질의]\n${query}`;
  let upstream;
  try {
    upstream = await fetch(base.replace(/\/$/, "") + "/chat/completions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ model: mdl, stream: true, temperature: 0.3, max_tokens: 800, messages: [{ role: "system", content: SYSTEM_PROMPT }, { role: "user", content: user }] }),
    });
  } catch (e) { return res.status(502).json({ error: "upstream", detail: String(e).slice(0, 200) }); }
  if (!upstream.ok || !upstream.body) return res.status(502).json({ error: "upstream", status: upstream.status });
  res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache");
  const reader = upstream.body.getReader(); const dec = new TextDecoder();
  try {
    while (true) { const { done, value } = await reader.read(); if (done) break; res.write(dec.decode(value, { stream: true })); }
  } catch (e) { /* client disconnect */ }
  res.end();
}
