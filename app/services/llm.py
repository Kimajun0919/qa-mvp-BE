import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def _provider_candidates(provider: Optional[str]) -> List[str]:
    raw = (provider or _env("QA_LLM_PROVIDER", "ollama")).strip().lower()
    if not raw:
        return ["ollama"]
    parts = [x.strip() for x in raw.replace("|", ",").split(",") if x.strip()]
    return parts or ["ollama"]


async def chat_json(system: str, user: str, *, provider: Optional[str] = None, model: Optional[str] = None, timeout_sec: float = 60.0, llm_auth: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, str, str]:
    llm_auth = llm_auth or {}
    providers = _provider_candidates(provider)
    last_err = "no provider tried"

    for p in providers:
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
                    last_err = f"ollama http {r.status_code}"
                    continue
                data = r.json()
                content = (data.get("message") or {}).get("content") or ""
                if not content:
                    last_err = "ollama empty content"
                    continue
                return True, content, p, m
            except Exception as e:
                last_err = str(e)
                continue

        if p == "openai":
            auth_openai = llm_auth.get("openai") if isinstance(llm_auth.get("openai"), dict) else {}
            api_key = str(auth_openai.get("apiKey") or auth_openai.get("oauthToken") or _env("OPENAI_API_KEY")).strip()
            m = model or _env("QA_OPENAI_MODEL", "gpt-4o-mini")
            if not api_key:
                last_err = "OPENAI_API_KEY/oauthToken not set"
                continue

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
                    last_err = f"openai http {r.status_code}"
                    continue
                data = r.json()
                content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                if not content:
                    last_err = "openai empty content"
                    continue
                return True, content, p, m
            except Exception as e:
                last_err = str(e)
                continue

        last_err = f"unsupported provider: {p}"

    return False, last_err, providers[0] if providers else "ollama", (model or "")


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
