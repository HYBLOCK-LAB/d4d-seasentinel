// Vercel serverless — LLM structured generator (OSINT hypotheses / knowledge-graph expansion).
// Returns JSON. Env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
const PROMPTS = {
  osint: `당신은 해양 OSINT 분석관입니다. 주어진 상황 컨텍스트를 근거로, 추가 조사가 필요한 공개출처정보(OSINT) 첩보 가설 4개를 생성하세요. 각 항목은 확인된 사실이 아닌 '추론된 첩보 가설'이며 검증이 필요합니다. 반드시 JSON 배열만 출력하고 다른 텍스트는 쓰지 마세요. schema: [{"kind":"port_logistics|social|sat_change|registry|news","text":"한국어 첩보 문장","source":"추정 출처","weight":0.0~1.0,"sentiment":-1.0~1.0}]`,
  graph: `당신은 해양 정보분석관입니다. 주어진 표적 선박의 잠재적 연계 관계를 지식그래프로 확장하세요. 확인된 사실이 아닌 '조사 가설'로서의 관계입니다. 반드시 JSON 객체만 출력하세요. schema: {"nodes":[{"id":"고유id","label":"한국어 라벨","type":"vessel|org|flag|port|person|shipment"}],"edges":[{"source":"id","target":"id","rel":"관계(한국어 동사구)"}]}. 4~7개 노드, 표적과 연결.`,
};

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "method" });
  const { task, context, model } = req.body || {};
  const sysp = PROMPTS[task];
  if (!sysp) return res.status(400).json({ error: "unknown task" });
  const base = process.env.LLM_BASE_URL, key = process.env.LLM_API_KEY;
  const mdl = model || process.env.LLM_MODEL || "gpt-5.4";
  if (!base || !key) return res.status(502).json({ error: "no llm config" });
  let text;
  try {
    const r = await fetch(base.replace(/\/$/, "") + "/chat/completions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json" },
      body: JSON.stringify({ model: mdl, stream: false, temperature: 0.4, max_tokens: 900, messages: [{ role: "system", content: sysp }, { role: "user", content: context || "" }] }),
    });
    const d = await r.json();
    text = d.choices?.[0]?.message?.content;
  } catch (e) { return res.status(502).json({ error: "upstream", detail: String(e).slice(0, 200) }); }
  if (!text) return res.status(502).json({ error: "upstream" });
  let t = text.trim();
  if (t.includes("```")) { t = t.split("```")[1] || t; if (t.startsWith("json")) t = t.slice(4); }
  try {
    let data;
    if (task === "osint") { const a = t.indexOf("["), b = t.lastIndexOf("]"); data = JSON.parse(t.slice(a, b + 1)); }
    else { const a = t.indexOf("{"), b = t.lastIndexOf("}"); data = JSON.parse(t.slice(a, b + 1)); }
    return res.status(200).json({ ok: true, data, model: mdl });
  } catch (e) { return res.status(502).json({ error: "parse", raw: String(text).slice(0, 300) }); }
}
