from __future__ import annotations

import json
import os

import httpx
from dotenv import load_dotenv

from mda.paths import repo_root

load_dotenv(repo_root() / ".env")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5.4")

THREAT_SUMMARY_SYSTEM = (
    "당신은 대한민국 해양영역인식(MDA) 위협 분석관입니다. "
    "반드시 제공된 경보와 근거 목록만 사용해 한국어로 2-3문장 설명을 작성하세요. "
    "없는 사실, 확률, 출처, 권고를 만들지 마세요."
)


def chat_completion(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 500,
) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("LLM_BASE_URL/LLM_API_KEY not configured")
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    with httpx.Client(timeout=90.0) as client:
        response = client.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def threat_summary_prompt(alert: dict, evidence: list[dict]) -> list[dict]:
    if not evidence:
        raise ValueError("cannot generate threat summary without evidence")
    evidence_payload = [
        {
            "term": item.get("term") or item.get("term_name"),
            "points": item.get("points"),
            "detail": item.get("detail"),
        }
        for item in evidence
    ]
    user_content = json.dumps(
        {
            "alert": {
                "id": alert.get("id") or alert.get("alert_id"),
                "title_ko": alert.get("title_ko"),
                "title_en": alert.get("title_en"),
                "level": alert.get("level"),
                "score": alert.get("score"),
                "why": alert.get("why"),
            },
            "evidence": evidence_payload,
            "instruction": "이 경보가 왜 위험한지 2-3문장으로 설명하고, 근거 목록에 있는 항목만 인용하세요.",
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": THREAT_SUMMARY_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def generate_threat_summary_ko(alert: dict, evidence: list[dict]) -> str:
    return chat_completion(threat_summary_prompt(alert, evidence))
