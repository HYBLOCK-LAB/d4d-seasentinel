// Vercel serverless — list available LLM models for the dashboard selector.
const JUNK = new Set(["high", "low", "medium", "gemini", "gpt", "chat_20706", "chat_23310"]);

export default async function handler(req, res) {
  const base = process.env.LLM_BASE_URL, key = process.env.LLM_API_KEY;
  const def = process.env.LLM_MODEL || "gpt-5.4";
  if (!base || !key) return res.status(200).json({ models: [def], default: def });
  try {
    const r = await fetch(base.replace(/\/$/, "") + "/models", { headers: { "Authorization": "Bearer " + key } });
    const d = await r.json();
    const ids = [...new Set((d.data || [])
      .map(m => m.id)
      .filter(id => !id.includes("/") && !JUNK.has(id) && /\d/.test(id)))].sort();
    return res.status(200).json({ models: ids.length ? ids : [def], default: def });
  } catch (e) {
    return res.status(200).json({ models: [def], default: def });
  }
}
