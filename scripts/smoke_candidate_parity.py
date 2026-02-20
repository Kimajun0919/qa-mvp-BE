#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analyze import analyze_site

TARGETS = [
    "https://httpbin.org/forms/post",
    "https://docs.openclaw.ai",
    "http://example.com",
]


async def _run_one(url: str) -> Dict[str, Any]:
    result = await analyze_site(url)
    candidates: List[Dict[str, Any]] = result.get("candidates", []) or []
    names = [str(c.get("name") or "") for c in candidates]
    parity_signals = ((result.get("metrics") or {}).get("paritySignals") or {}) if isinstance(result.get("metrics"), dict) else {}
    return {
        "url": url,
        "ok": bool(result.get("ok")),
        "pages": int(result.get("pages") or 0),
        "candidateCount": len(candidates),
        "candidateNames": names,
        "paritySignals": parity_signals,
    }


async def main() -> int:
    # Make smoke faster and deterministic-ish for CI/local runs.
    os.environ.setdefault("QA_ANALYZE_MAX_PAGES", "14")
    os.environ.setdefault("QA_ANALYZE_MAX_DEPTH", "2")
    os.environ.setdefault("QA_ANALYZE_DYNAMIC", "true")

    reports: List[Dict[str, Any]] = []
    for t in TARGETS:
        reports.append(await _run_one(t))

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))

    # Focused parity expectation (Cycle7 hotfix):
    # - sparse form target(httpbin) should not collapse into low candidate count
    # - docs target should expose docs-drift parity signals
    # - simple example target should stay backward-compatible
    raw_by_url = {x["url"]: x for x in reports}
    for r in reports:
        if not r["ok"]:
            print(f"FAIL: analyze not ok for {r['url']}", file=sys.stderr)
            return 1
        if r["candidateCount"] < 4:
            print(
                f"FAIL: candidateCount too low for {r['url']} (got {r['candidateCount']}, expected >=4)",
                file=sys.stderr,
            )
            return 1

    httpbin = raw_by_url.get("https://httpbin.org/forms/post", {})
    if "Form Submission Journey" not in (httpbin.get("candidateNames") or []):
        print("FAIL: httpbin form journey signal missing", file=sys.stderr)
        return 1

    docs = raw_by_url.get("https://docs.openclaw.ai", {})
    docs_risk = ((docs.get("paritySignals") or {}).get("docsDriftRisk") or "").upper()
    if docs_risk not in {"MEDIUM", "HIGH"}:
        print(f"FAIL: docs parity signal weak (docsDriftRisk={docs_risk})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
