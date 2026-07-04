import os

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mda.paths import repo_root

load_dotenv(repo_root() / ".env")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5.4")

SYSTEM_PROMPT = """당신은 대한민국 해양영역인식(MDA) 지휘결심 지원 분석관입니다.
'SEASENTINEL' 시스템이 제공하는 실시간 상황 컨텍스트(위협 경보·선박·OSINT·현재 시각)를 근거로만 답하세요.

규칙:
- 반드시 한국어로, 지휘관이 즉시 활용할 수 있게 간결하고 구조적으로 답하세요.
- 제공된 컨텍스트에 근거해 답하고, 근거가 된 항목(선박명·경보·OSINT 출처)을 함께 인용하세요.
- 컨텍스트에 없는 사실은 지어내지 마세요. 불확실하면 불확실하다고 명시하세요.
- 필요 시 권고 조치를 제시하세요: 관심표적 지정 / ISR 재촬영 / 경비함 유도·차단 / 채증 패키지 / 지휘보고.
- 4~8문장 또는 짧은 불릿으로. 과장·미사여구 금지."""

JUNK_MODEL_IDS = {"high", "low", "medium", "gemini", "gpt", "chat_20706", "chat_23310"}

router = APIRouter()


class CopilotRequest(BaseModel):
    query: str
    context: str = ""
    model: str | None = None


@router.post("/copilot")
async def copilot(request: CopilotRequest) -> StreamingResponse:
    model = request.model or LLM_MODEL
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"[현재 상황 컨텍스트]\n{request.context}\n\n[지휘관 질의]\n{request.query}",
        },
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 800,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}

    async def relay():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{LLM_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


@router.get("/models")
async def models() -> dict:
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{LLM_BASE_URL}/models", headers=headers)
            response.raise_for_status()
            data = response.json()
        ids = sorted(
            {
                m["id"]
                for m in data.get("data", [])
                if "/" not in m["id"]
                and m["id"] not in JUNK_MODEL_IDS
                and any(c.isdigit() for c in m["id"])
            }
        )
    except Exception:
        ids = []
    return {"models": ids or [LLM_MODEL], "default": LLM_MODEL}
