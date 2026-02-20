from __future__ import annotations

from typing import Any, Dict, List

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


async def run_transition_check(steps: List[Dict[str, Any]], auth: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if async_playwright is None:
        return {"ok": False, "error": "playwright not available"}

    auth = auth or {}
    out: List[Dict[str, Any]] = []
    summary = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}

    async with async_playwright() as p:  # type: ignore[misc]
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # optional login bootstrap
        login_url = str(auth.get("loginUrl") or "").strip()
        user_id = str(auth.get("userId") or "").strip()
        password = str(auth.get("password") or "").strip()
        if login_url and user_id and password:
            try:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                await page.locator("input[type='password']").first.fill(password, timeout=1500)
                await page.locator("input[type='email'], input[name*='id' i], input[name*='user' i], input[type='text']").first.fill(user_id, timeout=1500)
                await page.locator("button[type='submit'], input[type='submit'], button:has-text('로그인'), button:has-text('Login')").first.click(timeout=1500)
                await page.wait_for_timeout(1200)
            except Exception:
                pass

        for i, s in enumerate(steps or [], start=1):
            name = str(s.get("name") or f"step-{i}")
            url = str(s.get("url") or "").strip()
            expect_text = str(s.get("expectText") or "").strip()
            expect_url_contains = str(s.get("expectUrlContains") or "").strip()

            status = "BLOCKED"
            reason = "url missing"
            observed = {"url": "", "title": ""}

            if url:
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    code = int(resp.status) if resp else 0
                    current = page.url
                    title = (await page.title()) or ""
                    html = (await page.content())[:30000]
                    observed = {"url": current, "title": title, "httpStatus": code}

                    if code >= 400:
                        status = "FAIL"
                        reason = f"http {code}"
                    elif expect_url_contains and expect_url_contains not in current:
                        status = "FAIL"
                        reason = f"url expectation failed: {expect_url_contains}"
                    elif expect_text and expect_text not in html and expect_text not in title:
                        status = "FAIL"
                        reason = f"text expectation failed: {expect_text}"
                    else:
                        status = "PASS"
                        reason = ""
                except Exception as e:
                    status = "BLOCKED"
                    reason = str(e)[:180]

            summary[status] = summary.get(status, 0) + 1
            out.append({"name": name, "status": status, "reason": reason, "observed": observed})

        await context.close()
        await browser.close()

    return {"ok": True, "summary": summary, "steps": out}
