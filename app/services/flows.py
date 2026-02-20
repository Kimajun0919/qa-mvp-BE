from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List
from urllib.parse import urljoin

import httpx

from .llm import chat_json, parse_json_text
from .reporting import write_fix_sheet, write_html_summary

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


def finalize_flows(store: Dict[str, Dict[str, Any]], analysis_id: str, flows: List[Dict[str, Any]]) -> Dict[str, Any]:
    item = store.get(analysis_id)
    if not item:
        return {"ok": False, "error": "analysis not found", "status": 404}
    item["flows"] = flows
    return {"ok": True, "saved": len(flows), "storage": "fastapi-memory"}


def _retry_count() -> int:
    try:
        return max(1, int(os.getenv("QA_FLOW_RETRY_COUNT", "2")))
    except Exception:
        return 2


def _step_timeout_ms() -> int:
    try:
        return max(1000, int(os.getenv("QA_FLOW_STEP_TIMEOUT_MS", "10000")))
    except Exception:
        return 10000


def _selector_candidates(step: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    s = str(step.get("selector") or "").strip()
    if s:
        candidates.append(s)

    fb = step.get("fallbackSelectors")
    if isinstance(fb, list):
        for x in fb:
            t = str(x or "").strip()
            if t:
                candidates.append(t)

    tid = str(step.get("testId") or "").strip()
    if tid:
        candidates.append(f"[data-testid='{tid}']")

    # de-dup preserve order
    out: List[str] = []
    seen = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def _run_with_retry(fn: Callable[[], Awaitable[None]], retries: int, delay_ms: int = 250) -> None:
    last: Exception | None = None
    for i in range(retries):
        try:
            await fn()
            return
        except Exception as e:  # noqa: PERF203
            last = e
            if i < retries - 1:
                await asyncio.sleep(delay_ms / 1000)
    if last:
        raise last


async def _run_flows_light(base_url: str, flows: List[Dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_issues: List[Dict[str, Any]] = []
    flow_summary: List[Dict[str, Any]] = []

    for flow in flows:
        f_start = int(time.time() * 1000)
        flow_name = str(flow.get("name") or "Unnamed flow")
        steps = flow.get("steps") or []
        status = "PASS"
        issue_count = 0
        current_url = base_url

        for step in steps:
            action = str(step.get("action") or "").upper()
            try:
                if action == "NAVIGATE":
                    to = step.get("targetUrl") or "/"
                    current_url = urljoin(base_url, str(to))
                    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, verify=False) as client:
                        r = await client.get(current_url)
                    if r.status_code >= 400:
                        status = "FAIL"
                        issue_count += 1
                        all_issues.append({"status": "FAIL", "actual": f"HTTP {r.status_code} {current_url}"})
                elif action == "ASSERT_URL":
                    target = str(step.get("targetUrl") or "/")
                    if target not in (current_url or ""):
                        status = "FAIL"
                        issue_count += 1
                        all_issues.append({"status": "FAIL", "actual": f"expected url includes {target}, got {current_url}"})
                elif action == "WAIT":
                    ms = int(step.get("value") or 300)
                    await asyncio.sleep(max(ms, 0) / 1000)
                else:
                    all_issues.append({"status": "WARNING", "actual": f"unsupported action in light runner: {action}"})
                    if status == "PASS":
                        status = "PASS_WITH_WARNINGS"
            except Exception as e:
                status = "FAIL"
                issue_count += 1
                all_issues.append({"status": "ERROR", "actual": str(e)})

        flow_summary.append(
            {
                "flowName": flow_name,
                "durationMs": int(time.time() * 1000) - f_start,
                "status": status,
                "issueCount": issue_count,
            }
        )

    return all_issues, flow_summary


async def _run_flows_playwright(base_url: str, flows: List[Dict[str, Any]], run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_issues: List[Dict[str, Any]] = []
    flow_summary: List[Dict[str, Any]] = []

    screenshot_dir = Path("artifacts") / run_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    retries = _retry_count()
    step_timeout = _step_timeout_ms()

    async with async_playwright() as p:  # type: ignore[misc]
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for flow in flows:
            f_start = int(time.time() * 1000)
            flow_name = str(flow.get("name") or "Unnamed flow")
            steps = flow.get("steps") or []
            status = "PASS"
            issue_count = 0

            for i, step in enumerate(steps):
                action = str(step.get("action") or "").upper()
                try:
                    if action == "NAVIGATE":
                        to = str(step.get("targetUrl") or "/")

                        async def _go() -> None:
                            await page.goto(urljoin(base_url, to), wait_until="domcontentloaded", timeout=step_timeout)

                        await _run_with_retry(_go, retries)
                    elif action == "ASSERT_URL":
                        target = str(step.get("targetUrl") or "/")
                        if target not in page.url:
                            status = "FAIL"
                            issue_count += 1
                            shot = screenshot_dir / f"{flow_name}_{i}_assert_url.png"
                            await page.screenshot(path=str(shot), full_page=True)
                            all_issues.append({"status": "FAIL", "actual": f"expected url includes {target}, got {page.url}", "screenshotPath": str(shot)})
                    elif action == "CLICK":
                        selectors = _selector_candidates(step)
                        if not selectors:
                            raise RuntimeError("CLICK selector missing")
                        last_err: Exception | None = None
                        clicked = False
                        for sel in selectors:
                            try:
                                async def _click() -> None:
                                    await page.locator(sel).first.click(timeout=step_timeout)
                                await _run_with_retry(_click, retries)
                                clicked = True
                                break
                            except Exception as e:
                                last_err = e
                        if not clicked:
                            raise RuntimeError(f"CLICK failed for selectors={selectors}: {last_err}")
                    elif action == "TYPE":
                        selectors = _selector_candidates(step)
                        value = str(step.get("value") or "")
                        if not selectors:
                            raise RuntimeError("TYPE selector missing")
                        last_err: Exception | None = None
                        typed = False
                        for sel in selectors:
                            try:
                                async def _type() -> None:
                                    await page.locator(sel).first.fill(value, timeout=step_timeout)
                                await _run_with_retry(_type, retries)
                                typed = True
                                break
                            except Exception as e:
                                last_err = e
                        if not typed:
                            raise RuntimeError(f"TYPE failed for selectors={selectors}: {last_err}")
                    elif action == "ASSERT_VISIBLE":
                        selectors = _selector_candidates(step)
                        if not selectors:
                            raise RuntimeError("ASSERT_VISIBLE selector missing")
                        visible = False
                        for sel in selectors:
                            try:
                                visible = await page.locator(sel).first.is_visible(timeout=step_timeout)
                                if visible:
                                    break
                            except Exception:
                                continue
                        if not visible:
                            status = "FAIL"
                            issue_count += 1
                            shot = screenshot_dir / f"{flow_name}_{i}_assert_visible.png"
                            await page.screenshot(path=str(shot), full_page=True)
                            all_issues.append({"status": "FAIL", "actual": f"selector not visible: {selectors}", "screenshotPath": str(shot)})
                    elif action == "WAIT":
                        ms = int(step.get("value") or 300)
                        await page.wait_for_timeout(max(ms, 0))
                    else:
                        all_issues.append({"status": "WARNING", "actual": f"unsupported action in playwright runner: {action}"})
                        if status == "PASS":
                            status = "PASS_WITH_WARNINGS"
                except Exception as e:
                    status = "FAIL"
                    issue_count += 1
                    shot = screenshot_dir / f"{flow_name}_{i}_error.png"
                    try:
                        await page.screenshot(path=str(shot), full_page=True)
                        shot_path = str(shot)
                    except Exception:
                        shot_path = ""
                    all_issues.append({"status": "ERROR", "actual": str(e), "screenshotPath": shot_path})

            flow_summary.append(
                {
                    "flowName": flow_name,
                    "durationMs": int(time.time() * 1000) - f_start,
                    "status": status,
                    "issueCount": issue_count,
                }
            )

        await context.close()
        await browser.close()

    return all_issues, flow_summary


async def run_flows(
    store: Dict[str, Dict[str, Any]],
    analysis_id: str,
    provider: str | None = None,
    model: str | None = None,
    llm_auth: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    item = store.get(analysis_id)
    if not item:
        return {"ok": False, "error": "analysis not found", "status": 404}

    base_url = (item.get("analysis") or {}).get("baseUrl")
    flows = item.get("flows") or []
    if not flows:
        return {"ok": False, "error": "no finalized flows", "status": 400}

    run_id = f"py_run_{int(time.time() * 1000)}"
    started_ms = int(time.time() * 1000)

    use_playwright = os.getenv("QA_FASTAPI_USE_PLAYWRIGHT", "true").lower() in {"1", "true", "yes", "on"}
    if use_playwright and async_playwright is not None:
        try:
            all_issues, flow_summary = await _run_flows_playwright(base_url, flows, run_id)
        except Exception:
            all_issues, flow_summary = await _run_flows_light(base_url, flows)
    else:
        all_issues, flow_summary = await _run_flows_light(base_url, flows)

    summary = {
        "PASS": len([x for x in flow_summary if x["status"] == "PASS"]),
        "WARNING": len([x for x in flow_summary if x["status"] == "PASS_WITH_WARNINGS"]),
        "FAIL": len([x for x in flow_summary if x["status"] == "FAIL"]),
        "BLOCKED": 0,
        "ERROR": len([x for x in all_issues if x.get("status") == "ERROR"]),
        "FINAL": "PASS",
    }
    if summary["FAIL"] > 0 or summary["ERROR"] > 0:
        summary["FINAL"] = "FAIL"
    elif summary["WARNING"] > 0:
        summary["FINAL"] = "PASS_WITH_WARNINGS"

    judge = {"mode": "heuristic", "topCause": "Unknown", "priority": "P2", "summary3Lines": ["...", "...", "..."]}
    try:
        ok, content, _, _ = await chat_json(
            "Return JSON only: {\"topCause\":string,\"priority\":\"P1\"|\"P2\"|\"P3\",\"summary3Lines\":string[]}",
            f"summary={summary}\nissues={all_issues[:5]}",
            provider=provider,
            model=model,
            llm_auth=llm_auth,
        )
        if ok:
            d = parse_json_text(content)
            if isinstance(d, dict):
                judge = {
                    "mode": "llm",
                    "topCause": str(d.get("topCause") or "Unknown"),
                    "priority": str(d.get("priority") or "P2"),
                    "summary3Lines": d.get("summary3Lines") or ["...", "...", "..."],
                }
    except Exception:
        pass

    native_payload = {
        "failed": all_issues,
        "execution": {
            "targetUrl": base_url,
            "startedAt": started_ms,
            "finishedAt": int(time.time() * 1000),
            "durationMs": int(time.time() * 1000) - started_ms,
            "finalStatus": summary["FINAL"],
        },
    }

    report_dir = Path("out/report")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / f"run_{run_id}.json"
    fix_sheet = write_fix_sheet(run_id, all_issues)
    report_html = write_html_summary(run_id, summary, flow_summary, judge)

    payload = {
        "runId": run_id,
        "summary": summary,
        "flowSummary": flow_summary,
        "judge": judge,
        "native": native_payload,
        "fixSheet": fix_sheet,
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "runId": run_id,
        "finalStatus": summary["FINAL"],
        "summary": summary,
        "flowSummary": flow_summary,
        "judge": judge,
        "reportPath": report_html,
        "reportJson": str(report_json).replace('\\', '/'),
        "fixSheet": fix_sheet,
        "_native": native_payload,
    }
