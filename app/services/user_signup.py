from __future__ import annotations

import re
import time
from typing import Any, Dict, List
from urllib.parse import urljoin

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


_SIGNUP_KEYWORDS = [
    "signup",
    "sign up",
    "register",
    "create account",
    "join",
    "회원가입",
    "가입",
]


def _has_signup_text(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _SIGNUP_KEYWORDS)


def _dedup(seq: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in seq:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


async def attempt_user_signup(base_url: str, bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    signals: Dict[str, Any] = {
        "candidateUrls": [],
        "visitedUrls": [],
        "matchedKeywords": [],
        "detectedFields": [],
        "captchaDetected": False,
        "submitDetected": False,
        "submitted": False,
        "urlChangedAfterSubmit": False,
        "emailVerificationHint": False,
    }

    if async_playwright is None:
        return {"status": "SKIPPED", "reason": "playwright unavailable", "signals": signals}

    candidates: List[str] = [base_url]

    pages = (bundle or {}).get("pages") if isinstance((bundle or {}).get("pages"), list) else []
    for p in pages:
        path = str((p or {}).get("path") or "").strip()
        if path and _has_signup_text(path):
            candidates.append(urljoin(base_url, path))
            signals["matchedKeywords"].append(path)

    async with async_playwright() as p:  # type: ignore[misc]
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=15000)

            links = page.locator("a[href], button, [role='button']")
            n = min(await links.count(), 60)
            for i in range(n):
                try:
                    el = links.nth(i)
                    txt = (await el.inner_text(timeout=300)).strip().lower()
                    href = str(await el.get_attribute("href") or "").strip()
                    if _has_signup_text(txt) or _has_signup_text(href):
                        if href and href != "#":
                            candidates.append(urljoin(base_url, href))
                        else:
                            signals["matchedKeywords"].append(txt[:80])
                except Exception:
                    continue

            candidates = _dedup(candidates)[:5]
            signals["candidateUrls"] = candidates

            for target in candidates:
                try:
                    await page.goto(target, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    continue
                signals["visitedUrls"].append(page.url)

                title = (await page.title()).lower()
                body = (await page.locator("body").inner_text(timeout=1000)).lower()
                if _has_signup_text(page.url) or _has_signup_text(title) or _has_signup_text(body[:2000]):
                    signals["matchedKeywords"].append(page.url)

                inputs = page.locator("input")
                input_count = await inputs.count()
                has_password = await page.locator("input[type='password']").count() > 0
                has_email = await page.locator("input[type='email']").count() > 0
                has_submit = await page.locator("button[type='submit'], input[type='submit'], button:has-text('Sign up'), button:has-text('Register'), button:has-text('회원가입')").count() > 0
                signals["submitDetected"] = bool(has_submit)

                form_like = (input_count >= 2 and has_password) or (has_submit and _has_signup_text(page.url + " " + title + " " + body[:1000]))
                if not form_like:
                    continue

                # Fill safe synthetic values (reserved invalid domain)
                ts = int(time.time())
                synthetic = {
                    "email": f"qa.signup.{ts}@example.invalid",
                    "password": "Qatest!23456",
                    "name": "QA Test User",
                    "phone": "01000000000",
                }

                fill_selectors = [
                    ("input[type='email']", synthetic["email"]),
                    ("input[name*='email' i]", synthetic["email"]),
                    ("input[type='password']", synthetic["password"]),
                    ("input[name*='pass' i]", synthetic["password"]),
                    ("input[name*='name' i]", synthetic["name"]),
                    ("input[placeholder*='name' i]", synthetic["name"]),
                    ("input[type='tel']", synthetic["phone"]),
                    ("input[name*='phone' i]", synthetic["phone"]),
                ]

                detected_fields: List[str] = []
                for sel, value in fill_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            await loc.fill(value, timeout=1200)
                            detected_fields.append(sel)
                    except Exception:
                        continue

                signals["detectedFields"] = _dedup(signals.get("detectedFields", []) + detected_fields)

                # try terms checkbox safely
                try:
                    cb = page.locator("input[type='checkbox']").first
                    if await cb.count() > 0:
                        await cb.check(timeout=800)
                except Exception:
                    pass

                captcha = await page.locator("iframe[src*='captcha' i], .g-recaptcha, [id*='captcha' i], [class*='captcha' i]").count() > 0
                if captcha:
                    signals["captchaDetected"] = True
                    return {"status": "BLOCKED", "reason": "captcha detected", "signals": signals}

                before_url = page.url
                submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Sign up'), button:has-text('Register'), button:has-text('회원가입')").first
                if await submit_btn.count() == 0:
                    continue

                try:
                    await submit_btn.click(timeout=2000)
                    signals["submitted"] = True
                    await page.wait_for_timeout(1500)
                except Exception as e:
                    return {"status": "FAILED", "reason": f"submit click failed: {e}", "signals": signals}

                after_url = page.url
                signals["urlChangedAfterSubmit"] = after_url != before_url
                try:
                    latest_body = (await page.locator("body").inner_text(timeout=1000)).lower()
                    if re.search(r"verify|verification|이메일 인증|인증 메일", latest_body):
                        signals["emailVerificationHint"] = True
                except Exception:
                    pass

                reason = "submitted signup-like form"
                if signals["emailVerificationHint"]:
                    reason = "submitted; email verification hinted"
                return {"status": "ATTEMPTED", "reason": reason, "signals": signals}

        finally:
            await context.close()
            await browser.close()

    return {"status": "SKIPPED", "reason": "no signup-like form detected", "signals": signals}
