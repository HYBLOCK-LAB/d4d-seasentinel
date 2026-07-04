#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEASENTINEL demo server — static files + LLM copilot proxy.

- Serves the static app (index.html, app.js, data/…).
- Holds the LLM API key SERVER-SIDE (.secrets/llm.json) so it never reaches the client.
- POST /api/copilot streams a grounded answer from the OpenAI-compatible gateway (SSE relay).
- Denies static access to secrets / server source.

Run:  python3 server.py   (PORT env optional, default 3010)
"""
import json, os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "3010"))
try:
    CFG = json.load(open(os.path.join(ROOT, ".secrets", "llm.json")))
except Exception as e:
    CFG = {}
    print("WARN: .secrets/llm.json not loaded —", e, "→ copilot will 502, frontend falls back to rules")

SYSTEM_PROMPT = """당신은 대한민국 해양영역인식(MDA) 지휘결심 지원 분석관입니다.
'SEASENTINEL' 시스템이 제공하는 실시간 상황 컨텍스트(위협 경보·선박·OSINT·현재 시각)를 근거로만 답하세요.

규칙:
- 반드시 한국어로, 지휘관이 즉시 활용할 수 있게 간결하고 구조적으로 답하세요.
- 제공된 컨텍스트에 근거해 답하고, 근거가 된 항목(선박명·경보·OSINT 출처)을 함께 인용하세요.
- 컨텍스트에 없는 사실은 지어내지 마세요. 불확실하면 불확실하다고 명시하세요.
- 필요 시 권고 조치를 제시하세요: 관심표적 지정 / ISR 재촬영 / 경비함 유도·차단 / 채증 패키지 / 지휘보고.
- 4~8문장 또는 짧은 불릿으로. 과장·미사여구 금지."""

DENY = {".secrets", ".git", ".env", "server.py", ".gitignore", "scripts"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def _denied(self, path):
        for seg in path.split("?")[0].strip("/").split("/"):
            if seg.startswith(".") or seg in DENY:
                return True
        return False

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        if self.path.startswith("/api/health"):
            return self._json(200, {"ok": bool(CFG), "model": CFG.get("model")})
        if self._denied(self.path):
            return self._json(403, {"error": "forbidden"})
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/copilot"):
            return self._copilot()
        if self.path.startswith("/api/generate"):
            return self._generate()
        return self._json(404, {"error": "not found"})

    def _llm_text(self, messages, max_tokens=900):
        """Non-streaming completion → full text (or None on error)."""
        payload = {"model": CFG.get("model"), "stream": False, "temperature": 0.4, "max_tokens": max_tokens, "messages": messages}
        up = urllib.request.Request(
            CFG["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + CFG["api_key"], "Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(up, timeout=90)
            d = json.loads(resp.read())
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            print("generate upstream err:", str(e)[:200]); return None

    def _generate(self):
        if not CFG:
            return self._json(502, {"error": "no llm config"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})
        task = req.get("task"); context = req.get("context") or ""
        if task == "osint":
            sysp = ("당신은 해양 OSINT 분석관입니다. 주어진 상황 컨텍스트를 근거로, 추가 조사가 필요한 "
                    "공개출처정보(OSINT) 첩보 가설 4개를 생성하세요. 각 항목은 실제 확인된 사실이 아닌 "
                    "'추론된 첩보 가설'이며 검증이 필요합니다. 반드시 JSON 배열만 출력하고 다른 텍스트는 쓰지 마세요. "
                    'schema: [{"kind":"port_logistics|social|sat_change|registry|news","text":"한국어 첩보 문장",'
                    '"source":"추정 출처","weight":0.0~1.0,"sentiment":-1.0~1.0}]')
        elif task == "graph":
            sysp = ("당신은 해양 정보분석관입니다. 주어진 표적 선박의 잠재적 연계 관계를 지식그래프로 확장하세요. "
                    "확인된 사실이 아닌 '조사 가설'로서의 관계입니다. 반드시 JSON 객체만 출력하세요. "
                    'schema: {"nodes":[{"id":"고유id","label":"한국어 라벨","type":"vessel|org|flag|port|person|shipment"}],'
                    '"edges":[{"source":"id","target":"id","rel":"관계(한국어 동사구)"}]}. 4~7개 노드, 표적과 연결.')
        else:
            return self._json(400, {"error": "unknown task"})
        text = self._llm_text([{"role": "system", "content": sysp}, {"role": "user", "content": context}], 900)
        if not text:
            return self._json(502, {"error": "upstream"})
        # extract JSON (strip fences / surrounding prose)
        t = text.strip()
        if "```" in t:
            t = t.split("```")[1]
            if t.startswith("json"): t = t[4:]
        a, b = t.find("["), t.rfind("]")
        c, d = t.find("{"), t.rfind("}")
        try:
            if task == "osint" and a >= 0: data = json.loads(t[a:b + 1])
            else: data = json.loads(t[c:d + 1])
        except Exception as e:
            return self._json(502, {"error": "parse", "raw": text[:300]})
        return self._json(200, {"ok": True, "data": data, "model": CFG.get("model")})

    def _copilot(self):
        if not CFG:
            return self._json(502, {"error": "no llm config"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})
        query = (req.get("query") or "").strip()
        context = req.get("context") or ""
        model = req.get("model") or CFG.get("model")
        if not query:
            return self._json(400, {"error": "empty query"})
        user = f"[현재 상황 컨텍스트]\n{context}\n\n[지휘관 질의]\n{query}"
        payload = {
            "model": model, "stream": True, "temperature": 0.3, "max_tokens": 800,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
        up = urllib.request.Request(
            CFG["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + CFG["api_key"],
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(up, timeout=90)
        except Exception as e:
            return self._json(502, {"error": "upstream", "detail": str(e)[:200]})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for line in resp:               # http.client streams lines as they arrive
                self.wfile.write(line)
                self.wfile.flush()
        except Exception:
            pass

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"SEASENTINEL server → http://localhost:{PORT}  (root={ROOT}, model={CFG.get('model')}, llm={'on' if CFG else 'OFF'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
