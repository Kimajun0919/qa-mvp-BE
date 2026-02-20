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
        )
        rows = chk.get("rows") or []

        # normalize screen column to absolute URL + attach evidence path
        for r in rows:
            r["화면"] = full_url
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

    # merge into single checklist (site-level): same 구분+시나리오 rows are unified
    merged_map: Dict[str, Dict[str, Any]] = {}
    for r in merged_rows:
        scenario = str(r.get("테스트시나리오") or "").strip()
        category = str(r.get("구분") or "").strip()
        if not scenario:
            continue
        key = f"{category}::{scenario}"
        current = merged_map.get(key)
        src_url = str(r.get("화면") or "").strip()
        if current is None:
            merged_map[key] = {
                "화면": src_url,
                "구분": category,
                "테스트시나리오": scenario,
                "확인": str(r.get("확인") or ""),
                "_urls": [src_url] if src_url else [],
            }
        else:
            if src_url and src_url not in current["_urls"]:
                current["_urls"].append(src_url)

    dedup: List[Dict[str, Any]] = []
    for _, row in sorted(merged_map.items(), key=lambda kv: kv[0]):
        urls = row.pop("_urls", [])
        if isinstance(urls, list) and urls:
            preview = urls[:3]
            suffix = f" (+{len(urls)-3})" if len(urls) > 3 else ""
            row["화면"] = " | ".join(preview) + suffix
        dedup.append(row)

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
