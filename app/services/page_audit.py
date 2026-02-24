from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from .checklist import COLUMNS, generate_checklist

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


def _tsv(rows: List[Dict[str, Any]]) -> str:
    head = "\t".join(COLUMNS)
    body = ["\t".join(str(r.get(c, "")) for c in COLUMNS) for r in rows]
    return "\n".join([head, *body])


async def _login_if_possible(page: Any, auth: Dict[str, Any]) -> bool:
    user_id = str(auth.get("userId") or "").strip()
    password = str(auth.get("password") or "").strip()
    if not user_id or not password:
        return False

    try:
        await page.locator("input[type='password']").first.fill(password, timeout=1200)
        # id/email/user 추정 필드
        uid_loc = page.locator("input[type='email'], input[name*='id' i], input[name*='user' i], input[type='text']").first
        await uid_loc.fill(user_id, timeout=1200)
        await page.locator("button[type='submit'], input[type='submit'], button:has-text('로그인'), button:has-text('Login')").first.click(timeout=1500)
        await page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


async def _capture_page(url: str, out_dir: Path, auth: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if async_playwright is None:
        return {"ok": False, "error": "playwright not available"}

    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"snap_{int(time.time()*1000)}.png"
    shot = out_dir / fname

    try:
        async with async_playwright() as p:  # type: ignore[misc]
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 900})

            auth = auth or {}
            login_url = str(auth.get("loginUrl") or "").strip()
            login_used = False
            if login_url:
                try:
                    await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                    login_used = await _login_if_possible(page, auth)
                except Exception:
                    login_used = False

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(shot), full_page=True)

            title = await page.title()
            stats = await page.evaluate(
                """
                () => ({
                  h1: document.querySelectorAll('h1').length,
                  forms: document.querySelectorAll('form').length,
                  buttons: document.querySelectorAll('button, [role="button"]').length,
                  links: document.querySelectorAll('a[href]').length,
                  inputs: document.querySelectorAll('input,select,textarea').length,
                })
                """
            )
            await browser.close()
            return {
                "ok": True,
                "title": title,
                "screenshotPath": str(shot).replace("\\", "/"),
                "stats": stats or {},
                "loginUsed": login_used,
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def auto_checklist_from_sitemap(
    bundle: Dict[str, Any],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    include_auth: bool = True,
    max_pages: Optional[int] = None,
    source: str = "sitemap",
    auth: Dict[str, Any] | None = None,
    checklist_expand: bool = False,
    checklist_expand_mode: str = "none",
    checklist_expand_limit: int = 20,
) -> Dict[str, Any]:
    analysis = bundle.get("analysis") or {}
    base_url = str(analysis.get("baseUrl") or "").rstrip("/")
    pages = bundle.get("pages") or []

    selected_pages = pages
    src = (source or "sitemap").lower()
    if src == "menu":
        menu_rows: List[Dict[str, Any]] = []
        reports = bundle.get("reports") or {}
        menu_path = str(reports.get("menuPath") or "").strip()
        if menu_path:
            mp = Path(menu_path)
            if mp.exists():
                try:
                    menu_payload = json.loads(mp.read_text(encoding="utf-8"))
                    menu_rows = menu_payload.get("rows") or []
                except Exception:
                    menu_rows = []

        seen = set()
        menu_pages: List[Dict[str, Any]] = []
        for m in menu_rows:
            href = str(m.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            menu_pages.append({"path": href, "title": str(m.get("name") or href)})

        if menu_pages:
            selected_pages = menu_pages

    auth = auth or {}
    out_dir = Path("out/report/screenshots")
    page_results: List[Dict[str, Any]] = []
    merged_rows: List[Dict[str, Any]] = []
    screenshot_ok = 0

    auto_cap = int(os.getenv("QA_AUTO_MAX_PAGES", "30"))
    target_count = max_pages if (isinstance(max_pages, int) and max_pages > 0) else len(selected_pages)
    target_count = max(1, min(target_count, auto_cap))

    for p in selected_pages[:target_count]:
        path = str(p.get("path") or "/")
        title = str(p.get("title") or "").strip()
        full_url = urljoin(base_url + "/", path.lstrip("/")) if path != "/" else base_url + "/"

        snap = await _capture_page(full_url, out_dir, auth=auth)
        if snap.get("ok"):
            screenshot_ok += 1
        visual = snap.get("stats") or {}
        visual_ctx = f"path={path}, title={title}, visual={visual}, screenshot={snap.get('screenshotPath','')}"

        chk = await generate_checklist(
            screen=full_url,
            context=visual_ctx,
            include_auth=include_auth,
            provider=provider,
            model=model,
            expand=checklist_expand,
            expand_mode=checklist_expand_mode,
            max_rows=max(6, min(checklist_expand_limit, 300)),
        )
        rows = chk.get("rows") or []

        # normalize screen/module to absolute URL + section + attach evidence path
        for r in rows:
            module = str(r.get("module") or r.get("화면") or full_url).strip() or full_url
            if module.startswith("http://") or module.startswith("https://"):
                normalized_module = module
            else:
                normalized_module = f"{full_url}::{module.split('::')[-1]}" if "::" in module else full_url
            r["module"] = normalized_module
            r["화면"] = normalized_module
            if "비고" not in r:
                r["비고"] = ""
            note = f"evidence:{snap.get('screenshotPath','')}"
            r["비고"] = (str(r.get("비고") or "") + " " + note).strip()
            merged_rows.append(r)

        page_results.append(
            {
                "path": path,
                "url": full_url,
                "title": title,
                "screenshot": snap,
                "checklistMode": chk.get("mode"),
                "rows": rows,
            }
        )

    # merge into single checklist (site-level) while preserving section-level density
    merged_map: Dict[str, Dict[str, Any]] = {}
    for r in merged_rows:
        module = str(r.get("module") or r.get("화면") or "").strip()
        element = str(r.get("element") or "").strip()
        action = str(r.get("action") or r.get("테스트시나리오") or "").strip()
        expected = str(r.get("expected") or r.get("확인") or "").strip()
        category = str(r.get("구분") or "").strip()
        if not action:
            continue
        key = f"{module}::{element}::{category}::{action}::{expected}"
        if key in merged_map:
            continue
        merged_map[key] = {
            "화면": module,
            "module": module,
            "element": element,
            "구분": category,
            "action": action,
            "expected": expected,
            "actual": str(r.get("actual") or ""),
            "테스트시나리오": str(r.get("테스트시나리오") or action),
            "확인": str(r.get("확인") or expected),
            "비고": str(r.get("비고") or ""),
        }

    dedup: List[Dict[str, Any]] = [v for _, v in sorted(merged_map.items(), key=lambda kv: kv[0])]

    return {
        "ok": True,
        "analysisId": analysis.get("analysisId"),
        "baseUrl": base_url,
        "pagesAudited": len(page_results),
        "screenshotOk": screenshot_ok,
        "screenshotFailed": max(0, len(page_results) - screenshot_ok),
        "columns": COLUMNS,
        "rows": dedup[:120],
        "tsv": _tsv(dedup[:120]),
        "pageResults": page_results,
        "source": src,
        "authProvided": bool(str(auth.get("userId") or "").strip() and str(auth.get("password") or "").strip()),
        "note": f"{src} -> screenshot -> visual context checklist pipeline",
    }
