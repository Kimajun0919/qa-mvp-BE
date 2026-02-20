import json
import os
from typing import Any, Dict, Optional, Tuple

import httpx


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


async def chat_json(system: str, user: str, *, provider: Optional[str] = None, model: Optional[str] = None, timeout_sec: float = 60.0) -> Tuple[bool, str, str, str]:
    p = (provider or _env("QA_LLM_PROVIDER", "ollama")).lower()

    if p == "ollama":
        base = _env("QA_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        m = model or _env("QA_OLLAMA_MODEL", "qwen2.5:0.5b")
        payload: Dict[str, Any] = {
            "model": m,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.2},
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                r = await client.post(f"{base}/api/chat", json=payload)
            if r.status_code >= 400:
                return False, f"ollama http {r.status_code}", p, m
            data = r.json()
            content = (data.get("message") or {}).get("content") or ""
            if not content:
                return False, "ollama empty content", p, m
            return True, content, p, m
        except Exception as e:
            return False, str(e), p, m

    # openai
    api_key = _env("OPENAI_API_KEY")
    m = model or _env("QA_OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return False, "OPENAI_API_KEY not set", "openai", m

    payload = {
        "model": m,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        if r.status_code >= 400:
            return False, f"openai http {r.status_code}", "openai", m
        data = r.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        if not content:
            return False, "openai empty content", "openai", m
        return True, content, "openai", m
    except Exception as e:
        return False, str(e), "openai", m


def parse_json_text(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass

    # try fenced / prefixed text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start:end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return {}
    return {}
