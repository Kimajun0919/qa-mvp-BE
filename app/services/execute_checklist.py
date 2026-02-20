from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


def _pick_url(screen: str) -> str:
    s = (screen or "").strip()
    if not s:
        return ""
    return s.split("|")[0].strip().split(" ")[0].strip()


def _scenario_kind(text: str, category: str = "") -> str:
    s = ((text or "") + " " + (category or "")).lower()
    if any(k in s for k in ["권한", "비로그인", "접근 차단", "redirect", "리다이렉트", "보안"]):
        return "AUTH"
    if any(k in s for k in ["유효성", "입력", "필수", "에러", "오류", "실패"]):
        return "VALIDATION"
    if any(k in s for k in ["반응형", "모바일", "해상도", "키보드"]):
        return "RESPONSIVE"
    if any(k in s for k in ["퍼블리싱", "정렬", "간격", "디자인", "깨짐"]):
        return "PUBLISHING"
    if any(k in s for k in ["버튼", "클릭", "이동", "동작", "링크"]):
        return "INTERACTION"
    return "SMOKE"


def _failure_code(status: str, reason: str) -> str:
    if status == "PASS":
        return "OK"
    r = (reason or "").lower()
    if status == "BLOCKED":
        if "timeout" in r:
            return "BLOCKED_TIMEOUT"
        return "BLOCKED_RUNTIME"
    if "유효한 url 없음" in r:
        return "CONFIG_INVALID_URL"
    if "http" in r:
        return "HTTP_ERROR"
    if "타이틀 없음" in reason:
        return "ASSERT_TITLE_MISSING"
    if "본문이 너무 짧" in reason:
        return "ASSERT_RENDER_WEAK"
    if "오류/예외" in reason:
        return "ASSERT_ERROR_SIGNAL"
    if "클릭 가능한 주요 요소 미발견" in reason:
        return "SELECTOR_NOT_FOUND"
    if "클릭 후 상태/이동 변화 미확인" in reason:
        return "ASSERT_NO_STATE_CHANGE"
    if "유효성/에러 신호 미확인" in reason:
        return "ASSERT_VALIDATION_MISSING"
    if "권한/로그인 차단 신호 미확인" in reason:
        return "ASSERT_AUTH_GUARD_MISSING"
    if "레이아웃 오버플로우" in reason:
        return "ASSERT_LAYOUT_OVERFLOW"
    return "ASSERT_UNKNOWN"


async def _login_if_possible(page: Any, auth: Dict[str, Any]) -> bool:
    login_url = str(auth.get("loginUrl") or "").strip()
    user_id = str(auth.get("userId") or "").strip()
    password = str(auth.get("password") or "").strip()
    if not (login_url and user_id and password):
        return False

    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        await page.locator("input[type='password']").first.fill(password, timeout=1500)
        uid = page.locator("input[type='email'], input[name*='id' i], input[name*='user' i], input[type='text']").first
        await uid.fill(user_id, timeout=1500)
        await page.locator("button[type='submit'], input[type='submit'], button:has-text('로그인'), button:has-text('Login')").first.click(timeout=1500)
        await page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


async def _collect_elements(page: Any) -> Dict[str, int]:
    try:
        data = await page.evaluate(
            """
            () => ({
              buttons: document.querySelectorAll('button,[role="button"],input[type="button"],input[type="submit"]').length,
              links: document.querySelectorAll('a[href]').length,
              inputs: document.querySelectorAll('input').length,
              selects: document.querySelectorAll('select').length,
              textareas: document.querySelectorAll('textarea').length,
              editors: document.querySelectorAll('[contenteditable="true"], .ql-editor, .toastui-editor-contents, .ck-editor__editable').length,
              forms: document.querySelectorAll('form').length,
            })
            """
        )
        return {k: int(v or 0) for k, v in (data or {}).items()}
    except Exception:
        return {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0, "forms": 0}


async def _run_one(page: Any, url: str, scenario: str, category: str = "") -> Tuple[str, str, Dict[str, Any], Dict[str, int]]:
    meta: Dict[str, Any] = {"scenarioKind": _scenario_kind(scenario, category), "action": ""}
    elems: Dict[str, int] = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0, "forms": 0}
    try:
        try:
            await page.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        before = page.url
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        code = int(resp.status) if resp else 0
        await page.wait_for_timeout(400)
        current = page.url
        title = (await page.title()) or ""
        html = (await page.content())[:40000]
        low = (title + "\n" + html + "\n" + scenario).lower()
        meta.update({"httpStatus": code, "title": title[:120], "urlAfter": current})

        elems = await _collect_elements(page)

        if code >= 400:
            return "FAIL", f"http {code}", meta, elems

        kind = str(meta["scenarioKind"])

        if kind == "AUTH":
            # login required signal or redirect to login-ish page
            if any(k in low for k in ["로그인", "sign in", "unauthorized", "permission", "권한"]):
                return "PASS", "", meta, elems
            if current != url and any(k in current.lower() for k in ["login", "signin", "auth"]):
                return "PASS", "", meta, elems
            return "FAIL", "권한/로그인 차단 신호 미확인", meta, elems

        if kind == "VALIDATION":
            meta["action"] = "submit-empty-form"
            had_form = False
            clicked_submit = False
            try:
                form = page.locator("form").first
                had_form = (await form.count()) > 0
                if had_form:
                    btn = form.locator("button[type='submit'],input[type='submit']").first
                    if await btn.count() > 0:
                        await btn.click(timeout=1500)
                        clicked_submit = True
                else:
                    btn2 = page.locator("button[type='submit'],input[type='submit']").first
                    if await btn2.count() > 0:
                        await btn2.click(timeout=1200)
                        clicked_submit = True
                await page.wait_for_timeout(500)
            except Exception:
                pass
            html2 = (await page.content())[:40000].lower()
            invalid_count = await page.locator(":invalid").count()
            meta.update({"hadForm": had_form, "clickedSubmit": clicked_submit, "invalidCount": int(invalid_count or 0)})
            if invalid_count > 0:
                return "PASS", "", meta, elems
            # require explicit validation phrasing only after submit attempt
            if clicked_submit and any(k in html2 for k in ["필수", "invalid", "유효", "입력해", "required"]):
                return "PASS", "", meta, elems
            return "FAIL", "유효성/에러 신호 미확인", meta, elems

        if kind == "INTERACTION":
            meta["action"] = "click-primary"
            clicked = False
            for sel in ["button", "a[href]", "[role='button']"]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=1200)
                        clicked = True
                        await page.wait_for_timeout(600)
                        break
                except Exception:
                    continue
            after = page.url
            if not clicked:
                return "FAIL", "클릭 가능한 주요 요소 미발견", meta, elems
            if after != current:
                return "PASS", "", meta, elems
            # same page acceptable only with explicit state signal
            html_after = (await page.content())[:30000].lower()
            if any(k in html_after for k in ["active", "selected", "open", "expanded", "완료", "성공", "적용"]):
                return "PASS", "", meta, elems
            return "FAIL", "클릭 후 상태/이동 변화 미확인", meta, elems

        if kind == "RESPONSIVE":
            meta["action"] = "mobile-viewport-check"
            try:
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.wait_for_timeout(300)
                scroll_w = await page.evaluate("() => document.documentElement.scrollWidth")
                inner_w = await page.evaluate("() => window.innerWidth")
                cta = await page.locator("button, a[href]").count()
                meta.update({"mobileScrollWidth": scroll_w, "mobileInnerWidth": inner_w, "mobileCtaCount": cta})
                if int(scroll_w or 0) > int(inner_w or 0) + 20:
                    return "FAIL", "모바일 가로 스크롤/레이아웃 깨짐 가능성", meta, elems
                return "PASS", "", meta, elems
            except Exception as e:
                return "BLOCKED", str(e)[:180], meta, elems

        if kind == "PUBLISHING":
            meta["action"] = "layout-sanity-check"
            try:
                overflow = await page.evaluate(
                    """
                    () => {
                      const de = document.documentElement;
                      const b = document.body;
                      return Math.max(de.scrollWidth, b ? b.scrollWidth : 0) - window.innerWidth;
                    }
                    """
                )
                hidden_text = await page.evaluate(
                    """
                    () => {
                      const els = Array.from(document.querySelectorAll('body *')).slice(0, 400);
                      let clipped = 0;
                      for (const el of els) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && (r.right < 0 || r.left > window.innerWidth)) clipped++;
                      }
                      return clipped;
                    }
                    """
                )
                meta.update({"overflowPx": overflow, "offscreenElements": hidden_text})
                if int(overflow or 0) > 30:
                    return "FAIL", "퍼블리싱 레이아웃 오버플로우 감지", meta, elems
                return "PASS", "", meta, elems
            except Exception as e:
                return "BLOCKED", str(e)[:180], meta, elems

        # SMOKE (strict)
        body_len = len((html or "").strip())
        meta["bodyLength"] = body_len
        if not title.strip():
            return "FAIL", "타이틀 없음", meta, elems
        if body_len < 400:
            return "FAIL", "본문이 너무 짧아 유효 렌더 근거 부족", meta, elems
        if any(k in low for k in ["404", "not found", "오류", "error", "exception"]):
            return "FAIL", "오류/예외 신호 감지", meta, elems
        if before == current:
            # still pass only if meaningful interactive surface exists
            if int(elems.get("buttons", 0)) + int(elems.get("links", 0)) < 2:
                return "FAIL", "인터랙션 표면 부족", meta, elems
        return "PASS", "", meta, elems

    except Exception as e:
        return "BLOCKED", str(e)[:180], meta, elems


def _url_priority(u: str) -> int:
    s = (u or "").lower()
    score = 0
    if any(k in s for k in ["login", "signin", "auth", "join", "register"]):
        score += 3
    if any(k in s for k in ["apply", "payment", "checkout", "order", "mypage", "admin", "cms"]):
        score += 2
    if any(k in s for k in ["form", "write", "edit", "new"]):
        score += 1
    return score


def _is_risky_label(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["삭제", "delete", "remove", "결제", "pay", "purchase", "발행", "publish", "withdraw"])


async def _exhaustive_probe(page: Any, url: str, max_clicks: int = 12, max_inputs: int = 12, max_depth: int = 1, time_budget_ms: int = 20000, allow_risky: bool = False) -> Dict[str, int]:
    out = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0}
    try:
        from urllib.parse import urlparse
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    except Exception:
        origin = ""

    visited_urls = set()
    queue = [(url, 0)]
    started = int(time.time() * 1000)

    while queue:
        if int(time.time() * 1000) - started > time_budget_ms:
            break
        # priority BFS: auth/payment/form related URLs first
        queue.sort(key=lambda x: (-_url_priority(x[0]), x[1]))
        current_url, depth = queue.pop(0)
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        try:
            await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(250)
        except Exception:
            continue

        # discover same-origin links for shallow recursion
        if depth < max_depth:
            try:
                hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href).filter(Boolean)")
                for h in hrefs[:80]:
                    hs = str(h)
                    if origin and hs.startswith(origin) and hs not in visited_urls and all(q[0] != hs for q in queue):
                        queue.append((hs, depth + 1))
            except Exception:
                pass

        # clickable sweep with de-dup (text+selector-index heuristic)
        clicked_keys = set()
        for sel, key in [
            ("button,[role='button'],input[type='button'],input[type='submit']", "buttons"),
            ("a[href]", "links"),
        ]:
            try:
                loc = page.locator(sel)
                cnt = min(await loc.count(), max_clicks)
                for i in range(cnt):
                    try:
                        text = (await loc.nth(i).inner_text(timeout=300)).strip()[:80]
                    except Exception:
                        text = ""
                    k = f"{sel}::{i}::{text}"
                    if k in clicked_keys:
                        continue
                    clicked_keys.add(k)
                    if (not allow_risky) and _is_risky_label(text):
                        continue
                    try:
                        await loc.nth(i).click(timeout=700, no_wait_after=True)
                        out[key] += 1
                        await page.wait_for_timeout(120)
                    except Exception:
                        continue
            except Exception:
                continue

        # input sweep with type-aware fuzz set
        typed_keys = set()
        try:
            loc = page.locator("input:not([type='hidden']):not([type='submit']):not([type='button'])")
            cnt = min(await loc.count(), max_inputs)
            for i in range(cnt):
                try:
                    el = loc.nth(i)
                    nm = (await el.get_attribute("name") or "")
                    iid = (await el.get_attribute("id") or "")
                    ph = (await el.get_attribute("placeholder") or "")
                    tp = (await el.get_attribute("type") or "text").lower()
                    k = f"{nm}|{iid}|{ph}|{tp}".strip("|") or f"input-{i}"
                    if k in typed_keys:
                        continue
                    typed_keys.add(k)

                    vals = ["qa-auto"]
                    hint = f"{nm} {iid} {ph}".lower()
                    if tp == "email" or "email" in hint or "메일" in hint:
                        vals = ["qa@example.com", "invalid-email"]
                    elif tp == "tel" or "phone" in hint or "휴대" in hint or "전화" in hint:
                        vals = ["01012345678", "010-12"]
                    elif tp == "number" or "수량" in hint or "금액" in hint:
                        vals = ["1", "0", "-1", "999999999"]
                    elif tp == "date":
                        vals = ["2026-01-01", "1900-01-01"]
                    elif tp == "password" or "비밀번호" in hint:
                        vals = ["Aa123456!", "1234"]
                    elif tp == "url":
                        vals = ["https://example.com", "not-a-url"]

                    for v in vals[:2]:
                        try:
                            await el.fill(v, timeout=700)
                            out["inputs"] += 1
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass

        # select sweep
        try:
            loc = page.locator("select")
            cnt = min(await loc.count(), max_inputs)
            for i in range(cnt):
                try:
                    await loc.nth(i).select_option(index=0, timeout=700)
                    out["selects"] += 1
                except Exception:
                    continue
        except Exception:
            pass

        # textarea sweep (short/long/special)
        try:
            loc = page.locator("textarea")
            cnt = min(await loc.count(), max_inputs)
            for i in range(cnt):
                for v in ["qa-auto", "한글 테스트", "<script>alert(1)</script>"][:2]:
                    try:
                        await loc.nth(i).fill(v, timeout=700)
                        out["textareas"] += 1
                    except Exception:
                        continue
        except Exception:
            pass

        # editor sweep
        try:
            loc = page.locator("[contenteditable='true'], .ql-editor, .toastui-editor-contents, .ck-editor__editable")
            cnt = min(await loc.count(), max_inputs)
            for i in range(cnt):
                for v in ["qa-auto", "굵게 **테스트**", "줄바꿈\n테스트"][:2]:
                    try:
                        await loc.nth(i).fill(v, timeout=700)
                        out["editors"] += 1
                    except Exception:
                        continue
        except Exception:
            pass

    return out


async def execute_checklist_rows(rows: List[Dict[str, Any]], max_rows: int = 20, auth: Dict[str, Any] | None = None, exhaustive: bool = False, exhaustive_clicks: int = 12, exhaustive_inputs: int = 12, exhaustive_depth: int = 1, exhaustive_budget_ms: int = 20000, allow_risky_actions: bool = False) -> Dict[str, Any]:
    if async_playwright is None:
        return {"ok": False, "error": "playwright not available"}

    auth = auth or {}
    out_dir = Path("out/report/execution")
    out_dir.mkdir(parents=True, exist_ok=True)

    executed: List[Dict[str, Any]] = []
    summary = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    coverage_totals = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0, "forms": 0}
    covered = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0, "forms": 0}

    async with async_playwright() as p:  # type: ignore[misc]
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        login_used = await _login_if_possible(page, auth)

        target_rows = (rows or [])[:max_rows]
        for i, r in enumerate(target_rows, start=1):
            module = str(r.get("module") or r.get("화면") or "")
            url = _pick_url(module)
            action = str(r.get("action") or "").strip()
            expected = str(r.get("expected") or "").strip()
            scenario = str(r.get("테스트시나리오") or "").strip() or (f"{action} - {expected}".strip(" -"))
            category = str(r.get("구분") or "")

            status = "BLOCKED"
            reason = "유효한 URL 없음"
            meta: Dict[str, Any] = {"scenarioKind": _scenario_kind(scenario, category)}

            elems = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0, "forms": 0}
            if url.startswith("http://") or url.startswith("https://"):
                status, reason, meta, elems = await _run_one(page, url, scenario, category)

            for k in coverage_totals.keys():
                coverage_totals[k] += int(elems.get(k, 0) or 0)

            kind = str(meta.get("scenarioKind") or "")
            if kind in {"INTERACTION", "SMOKE", "AUTH", "RESPONSIVE", "PUBLISHING"}:
                covered["buttons"] += min(1, int(elems.get("buttons", 0) or 0))
                covered["links"] += min(1, int(elems.get("links", 0) or 0))
            if kind in {"VALIDATION", "AUTH"}:
                covered["inputs"] += min(1, int(elems.get("inputs", 0) or 0))
                covered["forms"] += min(1, int(elems.get("forms", 0) or 0))
                covered["selects"] += min(1, int(elems.get("selects", 0) or 0))
                covered["textareas"] += min(1, int(elems.get("textareas", 0) or 0))
                covered["editors"] += min(1, int(elems.get("editors", 0) or 0))

            ts = int(time.time())
            shot = out_dir / f"exec_{int(time.time()*1000)}_{i}.png"
            evidence = ""
            try:
                await page.screenshot(path=str(shot), full_page=True)
                evidence = str(shot).replace("\\", "/")
            except Exception:
                evidence = ""

            fail_code = _failure_code(status, reason)
            evidence_meta = {
                "screenshotPath": evidence,
                "observedUrl": meta.get("urlAfter") or url,
                "title": meta.get("title") or "",
                "httpStatus": meta.get("httpStatus") or 0,
                "scenarioKind": meta.get("scenarioKind") or _scenario_kind(scenario, category),
                "timestamp": ts,
            }

            summary[status] = summary.get(status, 0) + 1
            nr = dict(r)
            nr["실행결과"] = status
            nr["증거"] = evidence
            nr["증거메타"] = evidence_meta
            nr["실패사유"] = reason
            nr["실패코드"] = fail_code
            nr["확인"] = status
            nr["actual"] = status if not reason else f"{status}: {reason}"
            if not nr.get("테스트시나리오"):
                nr["테스트시나리오"] = scenario
            if not nr.get("화면"):
                nr["화면"] = module
            if not nr.get("module"):
                nr["module"] = module
            if action and not nr.get("action"):
                nr["action"] = action
            if expected and not nr.get("expected"):
                nr["expected"] = expected
            nr["실행메타"] = meta
            nr["요소통계"] = elems
            nr["실행시각"] = ts
            executed.append(nr)

        probe_summary = {"buttons": 0, "links": 0, "inputs": 0, "selects": 0, "textareas": 0, "editors": 0}
        if exhaustive:
            seen_urls = []
            for r in target_rows:
                u = _pick_url(str(r.get("module") or r.get("화면") or ""))
                if u.startswith("http://") or u.startswith("https://"):
                    if u not in seen_urls:
                        seen_urls.append(u)
            for u in seen_urls[:10]:
                p = await _exhaustive_probe(page, u, max_clicks=exhaustive_clicks, max_inputs=exhaustive_inputs, max_depth=exhaustive_depth, time_budget_ms=exhaustive_budget_ms, allow_risky=allow_risky_actions)
                for k, v in p.items():
                    probe_summary[k] += int(v or 0)
            # bump covered signals with probe result
            covered["buttons"] += probe_summary.get("buttons", 0)
            covered["links"] += probe_summary.get("links", 0)
            covered["inputs"] += probe_summary.get("inputs", 0)
            covered["selects"] += probe_summary.get("selects", 0)
            covered["textareas"] += probe_summary.get("textareas", 0)
            covered["editors"] += probe_summary.get("editors", 0)

        await context.close()
        await browser.close()

    total_rows = max(1, len(executed))
    for k in coverage_totals.keys():
        covered[k] = min(int(covered.get(k, 0)), int(coverage_totals.get(k, 0)))
    untested = {k: max(0, int(coverage_totals.get(k, 0)) - int(covered.get(k, 0))) for k in coverage_totals.keys()}
    coverage = {
        "totalsObserved": coverage_totals,
        "coveredSignals": covered,
        "untestedEstimate": untested,
        "rowCoverage": round((summary.get("PASS", 0) + summary.get("FAIL", 0)) / total_rows, 3),
        "exhaustive": {"enabled": exhaustive, "probeSummary": probe_summary if 'probe_summary' in locals() else {}, "allowRiskyActions": allow_risky_actions, "fuzzProfile": "typed-input-v1"},
    }
    return {"ok": True, "rows": executed, "summary": summary, "coverage": coverage, "loginUsed": login_used}
