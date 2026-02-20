from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .llm import chat_json, parse_json_text

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


@dataclass
class PageInfo:
    path: str
    title: str
    depth: int = 0
    role: str = "LANDING"
    priority_score: int = 60
    priority_tier: str = "MEDIUM"
    http_status: int = 200


def _guess_service_type(url: str, title: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    t = (title or "").lower()
    if any(k in host for k in ["shop", "store", "mall"]) or any(k in t for k in ["shop", "store", "cart", "checkout"]):
        return "ECOMMERCE"
    if any(k in t for k in ["dashboard", "admin", "관리자"]):
        return "DASHBOARD"
    return "LANDING"


def _is_auth_likely(text: str) -> bool:
    h = text.lower()
    keys = ["login", "sign in", "로그인", "password", "비밀번호", "auth", "2fa", "otp", "회원가입", "signin"]
    return any(k in h for k in keys)


def _classify_form_type(form_html: str) -> str:
    s = form_html.lower()
    if any(k in s for k in ["password", "로그인", "signin", "login"]):
      return "AUTH"
    if any(k in s for k in ["search", "검색"]):
      return "SEARCH"
    if any(k in s for k in ["checkout", "payment", "결제", "card"]):
      return "CHECKOUT"
    if any(k in s for k in ["contact", "문의", "email", "message"]):
      return "CONTACT"
    return "UNKNOWN"


def _normalize_path(url: str) -> str:
    u = urlparse(url)
    p = u.path or "/"
    if p != "/" and p.endswith("/"):
        p = p[:-1]
    return p


def _extract_paths_from_source(html: str) -> List[str]:
    # static source hints: router.push('/x'), "/path" strings, api/sitemap references
    candidates = set()
    for m in re.findall(r"(?:router\.push|navigate|href|to)\(\s*['\"](/[^'\"#?\s]{1,120})['\"]\s*\)", html):
        candidates.add(m)
    for m in re.findall(r"['\"](/(?:[a-zA-Z0-9_\-]+/){0,4}[a-zA-Z0-9_\-]+)['\"]", html):
        if len(m) > 1:
            candidates.add(m)
    return sorted(candidates)[:120]


async def _extract_paths_dynamic(url: str, origin: str) -> List[str]:
    if async_playwright is None:
        return []

    discovered: set[str] = set()
    try:
        async with async_playwright() as p:  # type: ignore[misc]
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)

            network_urls: set[str] = set()

            def _on_response(resp: Any) -> None:
                try:
                    u = str(resp.url)
                    if u.startswith(origin):
                        network_urls.add(u)
                except Exception:
                    pass

            page.on("response", _on_response)

            async def collect_links() -> None:
                hrefs = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
                )
                for h in hrefs or []:
                    absu = urljoin(url, str(h))
                    if absu.startswith(origin):
                        discovered.add(_normalize_path(absu))

            await collect_links()

            # try expand likely nav controls (hamburger/menu/toggle)
            selectors = [
                "button[aria-label*='menu' i]",
                "button[aria-label*='nav' i]",
                "button[class*='menu' i]",
                "button[class*='hamburger' i]",
                "[role='button'][aria-expanded='false']",
            ]
            for sel in selectors:
                try:
                    handles = page.locator(sel)
                    cnt = min(await handles.count(), 3)
                    for i in range(cnt):
                        try:
                            await handles.nth(i).click(timeout=1500)
                            await page.wait_for_timeout(400)
                            await collect_links()
                        except Exception:
                            continue
                except Exception:
                    continue

            # include in-page route hints after hydration
            html = await page.content()
            for sp in _extract_paths_from_source(html):
                discovered.add(sp)

            # network-derived same-origin paths (api/docs routes)
            for nu in network_urls:
                discovered.add(_normalize_path(nu))

            await context.close()
            await browser.close()
    except Exception:
        return []

    return sorted([p for p in discovered if p and p.startswith("/")])[:150]


def _priority_tier(score: int) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def _classify_role(path: str, title: str) -> str:
    s = f"{path} {title}".lower()
    if any(k in s for k in ["login", "signin", "로그인"]):
        return "LOGIN"
    if any(k in s for k in ["admin", "dashboard", "관리"]):
        return "DASHBOARD"
    if any(k in s for k in ["checkout", "cart", "결제", "주문"]):
        return "CHECKOUT"
    return "LANDING"


def _priority_score(path: str, role: str) -> int:
    score = 55
    if path == "/":
        score += 20
    if role in {"LOGIN", "CHECKOUT", "DASHBOARD"}:
        score += 20
    if any(k in path for k in ["/login", "/checkout", "/order", "/admin"]):
        score += 10
    return min(score, 100)


def _normalize_parity_signals(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}

    docs_risk = str(src.get("docsDriftRisk") or "LOW").upper()
    if docs_risk not in {"LOW", "MEDIUM", "HIGH"}:
        docs_risk = "LOW"

    def _to_nonneg_int(v: Any) -> int:
        try:
            return max(0, int(v or 0))
        except Exception:
            return 0

    return {
        "docsDriftRisk": docs_risk,
        "docsSignalCount": _to_nonneg_int(src.get("docsSignalCount")),
        "formSignalCount": _to_nonneg_int(src.get("formSignalCount")),
        "strongFormSignal": bool(src.get("strongFormSignal", False)),
        "singlePageFormTendency": bool(src.get("singlePageFormTendency", False)),
        "authLikely": bool(src.get("authLikely", False)),
    }


def _collect_parity_signals(pages: List[PageInfo], menu_rows: List[Dict[str, Any]], form_type_counts: Dict[str, int], auth_likely: bool) -> Dict[str, Any]:
    tokens: List[str] = []
    for p in pages:
        tokens.append((p.path or "").lower())
        tokens.append((p.title or "").lower())
    for m in menu_rows:
        tokens.append(str(m.get("href") or "").lower())
        tokens.append(str(m.get("name") or "").lower())

    docs_hits = sum(1 for t in tokens if any(k in t for k in ["/docs", "reference", "guide", "tutorial", "api", "changelog", "release", "sdk"]))
    form_total = int(sum(int(v or 0) for v in (form_type_counts or {}).values()))
    strong_form = form_total > 0 and int(form_type_counts.get("UNKNOWN", 0) or 0) <= max(1, form_total // 2)
    has_single_page_form_tendency = len({p.path for p in pages}) <= 2 and form_total > 0

    return _normalize_parity_signals(
        {
            "docsDriftRisk": "HIGH" if docs_hits >= 4 else ("MEDIUM" if docs_hits >= 2 else "LOW"),
            "docsSignalCount": docs_hits,
            "formSignalCount": form_total,
            "strongFormSignal": strong_form,
            "singlePageFormTendency": has_single_page_form_tendency,
            "authLikely": bool(auth_likely),
        }
    )


def _infer_candidate_flows(
    pages: List[PageInfo],
    menu_rows: List[Dict[str, Any]],
    service_type: str,
    auth_likely: bool,
    form_type_counts: Dict[str, int],
    parity_signals: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    path_tokens: set[str] = set()
    for p in pages:
        lp = (p.path or "").lower()
        if lp:
            path_tokens.add(lp)
    for m in menu_rows:
        href = str(m.get("href") or "").lower()
        if href:
            path_tokens.add(href)

    def _has_any(*keys: str) -> bool:
        return any(any(k in token for k in keys) for token in path_tokens)

    inferred: List[Dict[str, Any]] = [
        {
            "name": "Landing Navigation",
            "platformType": "LANDING",
            "confidence": 0.72,
            "status": "PROPOSED",
        },
        {
            "name": "Core CTA Journey",
            "platformType": service_type,
            "confidence": 0.74,
            "status": "PROPOSED",
        },
    ]

    parity_signals = _normalize_parity_signals(parity_signals)
    docs_signal_count = int(parity_signals.get("docsSignalCount") or 0)

    if _has_any("/docs", "/doc", "/guide", "/tutorial", "/reference", "/api") or docs_signal_count >= 2:
        inferred.append(
            {
                "name": "Documentation Discovery",
                "platformType": "LANDING",
                "confidence": 0.78,
                "status": "PROPOSED",
            }
        )

    if docs_signal_count >= 3:
        inferred.append(
            {
                "name": "Docs Reference Integrity",
                "platformType": "LANDING",
                "confidence": 0.73,
                "status": "PROPOSED",
            }
        )

    if form_type_counts.get("SEARCH", 0) > 0 or _has_any("/search"):
        inferred.append(
            {
                "name": "Search & Result Navigation",
                "platformType": "LANDING",
                "confidence": 0.76,
                "status": "PROPOSED",
            }
        )

    if _has_any("/download", "/releases", "/install"):
        inferred.append(
            {
                "name": "Download/Install Journey",
                "platformType": "LANDING",
                "confidence": 0.75,
                "status": "PROPOSED",
            }
        )

    if _has_any("/community", "/support", "/help", "/about", "/discuss"):
        inferred.append(
            {
                "name": "Community/Support Discovery",
                "platformType": "LANDING",
                "confidence": 0.71,
                "status": "PROPOSED",
            }
        )

    if form_type_counts.get("CONTACT", 0) > 0:
        inferred.append(
            {
                "name": "Form Submission Journey",
                "platformType": "LANDING",
                "confidence": 0.77,
                "status": "PROPOSED",
            }
        )

    if parity_signals.get("singlePageFormTendency"):
        inferred.append(
            {
                "name": "Single-Page Form Probe",
                "platformType": "LANDING",
                "confidence": 0.7,
                "status": "PROPOSED",
            }
        )

    if auth_likely:
        inferred.append(
            {
                "name": "Auth/Guard Access",
                "platformType": "LOGIN",
                "confidence": 0.68,
                "status": "PROPOSED",
            }
        )

    if form_type_counts.get("CHECKOUT", 0) > 0 or _has_any("/checkout", "/cart", "/order"):
        inferred.append(
            {
                "name": "Checkout/Order Flow",
                "platformType": "CHECKOUT",
                "confidence": 0.72,
                "status": "PROPOSED",
            }
        )

    # stable de-dup and hard cap to keep API payload compact
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for c in inferred:
        k = (str(c.get("name") or "").strip().lower(), str(c.get("platformType") or "").strip().upper())
        if not k[0]:
            continue
        if k in seen:
            continue
        seen.add(k)
        deduped.append(c)

    # Keep backward-compatible schema, but avoid low-candidate tendency on sparse targets.
    floor_candidates = [
        {"name": "Primary Path Smoke", "platformType": "LANDING", "confidence": 0.66, "status": "PROPOSED"},
        {"name": "Navigation Stability", "platformType": "LANDING", "confidence": 0.64, "status": "PROPOSED"},
    ]
    for c in floor_candidates:
        if len(deduped) >= 4:
            break
        k = (str(c.get("name") or "").strip().lower(), str(c.get("platformType") or "").strip().upper())
        if k in seen:
            continue
        seen.add(k)
        deduped.append(c)

    return deduped[:6]


def _write_analysis_reports(analysis_id: str, pages: List[PageInfo], menu_rows: List[Dict[str, Any]], metrics: Dict[str, Any]) -> Dict[str, str]:
    out_dir = Path("out/report")
    out_dir.mkdir(parents=True, exist_ok=True)

    sitemap_path = out_dir / f"analysis_{analysis_id}_sitemap.json"
    menu_path = out_dir / f"analysis_{analysis_id}_menu.json"
    quality_path = out_dir / f"analysis_{analysis_id}_quality.json"

    sitemap_payload = {
        "analysisId": analysis_id,
        "rows": [
            {
                "depth": p.depth,
                "role": p.role,
                "path": p.path,
                "priorityScore": p.priority_score,
                "priorityTier": p.priority_tier,
                "httpStatus": p.http_status,
                "title": p.title,
            }
            for p in pages
        ],
    }
    menu_payload = {"analysisId": analysis_id, "rows": menu_rows}
    form_types = metrics.get("formTypeCounts", {}) or {}
    form_total = max(1, int(metrics.get("formCount", 0) or 0))
    unknown_ratio = round(float(form_types.get("UNKNOWN", 0)) / form_total, 2) if form_total > 0 else 0
    precision = round(max(0.4, 1 - unknown_ratio * 0.7), 2)
    confidence = round(min(0.95, 0.55 + (metrics.get("coverageScore", 0) * 0.25) + (precision * 0.2)), 2)

    risks: List[str] = []
    if metrics.get("crawled", 0) < 3:
        risks.append("analysis depth limited")
    if unknown_ratio > 0.3:
        risks.append("form classification uncertainty")
    if metrics.get("authGatePages", 0) > 0:
        risks.append("auth-gate pages detected")

    quality_payload = {
        "analysisId": analysis_id,
        "metrics": metrics,
        "confidence": confidence,
        "formPrecision": {
            "precisionScore": precision,
            "unknownRatio": unknown_ratio,
            "notes": "fastapi tuned analyzer",
        },
        "risks": risks,
    }

    sitemap_path.write_text(json.dumps(sitemap_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    menu_path.write_text(json.dumps(menu_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_path.write_text(json.dumps(quality_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "sitemapPath": str(sitemap_path).replace("\\", "/"),
        "menuPath": str(menu_path).replace("\\", "/"),
        "qualityPath": str(quality_path).replace("\\", "/"),
    }


async def analyze_site(base_url: str, provider: Optional[str] = None, model: Optional[str] = None, llm_auth: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    target = base_url.strip()
    verify_tls = os.getenv("QA_HTTP_VERIFY_TLS", "false").lower() in {"1", "true", "yes", "on"}
    max_pages = int(os.getenv("QA_ANALYZE_MAX_PAGES", "20"))
    max_depth = int(os.getenv("QA_ANALYZE_MAX_DEPTH", "3"))
    if not target:
        raise ValueError("baseUrl required")

    if not target.startswith("http://") and not target.startswith("https://"):
        target = "https://" + target

    parsed_root = urlparse(target)
    origin = f"{parsed_root.scheme}://{parsed_root.netloc}"

    # pre-check robots/sitemap hints
    robots_block_all = False
    robots_requires_review = False
    robots_txt = ""

    visited: set[str] = set()
    queue: List[tuple[str, int]] = [(target, 0)]
    pages: List[PageInfo] = []
    menu_counter: Dict[tuple[str, str, str, str], int] = {}
    cta_count = 0
    form_count = 0
    form_type_counts: Dict[str, int] = {"AUTH": 0, "SEARCH": 0, "CHECKOUT": 0, "CONTACT": 0, "UNKNOWN": 0}
    auth_pages = 0
    auth_paths: List[str] = []

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=verify_tls) as client:
        try:
            rr = await client.get(urljoin(origin + "/", "/robots.txt"))
            if rr.status_code < 400:
                robots_txt = rr.text or ""
                low = robots_txt.lower()
                if "user-agent: *" in low and "disallow: /" in low:
                    robots_block_all = True
                if "disallow:" in low:
                    robots_requires_review = True
        except Exception:
            pass

        while queue and len(pages) < max_pages:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                r = await client.get(url)
            except Exception:
                continue

            html = r.text
            soup = BeautifulSoup(html, "html.parser")
            title = (soup.title.text.strip() if soup.title and soup.title.text else "")
            path = _normalize_path(str(r.url))
            role = _classify_role(path, title)
            score = _priority_score(path, role)
            tier = _priority_tier(score)
            page = PageInfo(path=path, title=title, depth=depth, role=role, priority_score=score, priority_tier=tier, http_status=r.status_code)
            pages.append(page)

            text_blob = f"{title}\n{html[:5000]}"
            if _is_auth_likely(text_blob):
                auth_pages += 1
                if path not in auth_paths:
                    auth_paths.append(path)

            forms = soup.select("form")
            form_count += len(forms)
            for f in forms:
                t = _classify_form_type(str(f))
                form_type_counts[t] = form_type_counts.get(t, 0) + 1

            anchors = soup.select("a[href]")
            for a in anchors:
                href = str(a.get("href") or "").strip()
                name = (a.get_text() or "").strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                absolute = urljoin(str(r.url), href)
                if not absolute.startswith(origin):
                    continue
                cta_count += 1

                scope = "GLOBAL" if depth == 0 else "LOCAL"
                zone = "header" if depth == 0 else "content"
                href_path = _normalize_path(absolute)
                key = (scope, zone, name[:120], href_path)
                menu_counter[key] = menu_counter.get(key, 0) + 1

                if depth < max_depth and absolute not in visited and all(q[0] != absolute for q in queue):
                    queue.append((absolute, depth + 1))

            # source-code level discovery for SPA/dynamic routes
            source_paths = _extract_paths_from_source(html)
            for sp in source_paths:
                absolute = urljoin(origin + "/", sp)
                if not absolute.startswith(origin):
                    continue
                if depth < max_depth and absolute not in visited and all(q[0] != absolute for q in queue):
                    queue.append((absolute, depth + 1))

            # absolute URL hints in source (same-origin only)
            for absu in re.findall(r"https?://[^\"'\s)]+", html):
                if not absu.startswith(origin):
                    continue
                if depth < max_depth and absu not in visited and all(q[0] != absu for q in queue):
                    queue.append((absu, depth + 1))

            # dynamic rendered routes (only on shallow depth for cost control)
            if depth == 0 and os.getenv("QA_ANALYZE_DYNAMIC", "true").lower() in {"1", "true", "yes", "on"}:
                dyn_paths = await _extract_paths_dynamic(str(r.url), origin)
                for dp in dyn_paths:
                    absolute = urljoin(origin + "/", dp)
                    if depth < max_depth and absolute not in visited and all(q[0] != absolute for q in queue):
                        queue.append((absolute, depth + 1))

    menu_rows: List[Dict[str, Any]] = [
        {"scope": k[0], "zone": k[1], "name": k[2], "href": k[3], "count": v}
        for k, v in sorted(menu_counter.items(), key=lambda x: x[1], reverse=True)[:100]
    ]

    if not pages:
        raise RuntimeError("no pages crawled")

    service_type = _guess_service_type(target, pages[0].title)
    auth_likely = auth_pages > 0

    parity_signals = _collect_parity_signals(pages, menu_rows, form_type_counts, auth_likely)

    metrics = {
        "queued": len(visited) + len(queue),
        "crawled": len(pages),
        "uniquePathCount": len({p.path for p in pages}),
        "ctaCount": cta_count,
        "menuCount": len(menu_rows),
        "formCount": form_count,
        "formTypeCounts": form_type_counts,
        "coverageScore": min(1, round(len(pages) / max(1, max_pages), 2)),
        "criticalPages": len([p for p in pages if p.priority_tier == "HIGH"]),
        "avgPriorityScore": int(sum(p.priority_score for p in pages) / len(pages)),
        "authGatePages": auth_pages,
        "paritySignals": parity_signals,
    }

    # LLM-assisted candidate generation (fallback heuristic)
    sys = "You are QA planner. Return JSON only: {\"candidates\":[{\"name\":string,\"platformType\":string,\"confidence\":number,\"status\":\"PROPOSED\"}]}"
    usr = f"url={target}\nserviceType={service_type}\nauthLikely={auth_likely}\npaths={','.join(p.path for p in pages[:10])}\nGenerate 3 QA flow candidates."

    ok, content_or_err, used_provider, used_model = await chat_json(sys, usr, provider=provider, model=model, llm_auth=llm_auth)
    planner_mode = "llm" if ok else "heuristic"
    planner_reason = "" if ok else content_or_err

    inferred_candidates = _infer_candidate_flows(pages, menu_rows, service_type, auth_likely, form_type_counts, parity_signals=parity_signals)

    candidates: List[Dict[str, Any]] = []
    if ok:
        data = parse_json_text(content_or_err)
        raw = data.get("candidates") if isinstance(data, dict) else None
        if isinstance(raw, list):
            for i, c in enumerate(raw[:6]):
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or f"Flow {i+1}").strip()
                ptype = str(c.get("platformType") or service_type).strip().upper()
                conf = float(c.get("confidence") or 0.7)
                candidates.append(
                    {
                        "name": name,
                        "platformType": ptype,
                        "confidence": max(0.0, min(conf, 1.0)),
                        "status": "PROPOSED",
                    }
                )

    # Node-path parity: keep LLM candidates, then top-up with extracted route/signal candidates.
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in (candidates, inferred_candidates):
        for c in source:
            key = (
                str(c.get("name") or "").strip().lower(),
                str(c.get("platformType") or service_type).strip().upper(),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "name": str(c.get("name") or "Flow").strip(),
                    "platformType": str(c.get("platformType") or service_type).strip().upper(),
                    "confidence": max(0.0, min(float(c.get("confidence") or 0.7), 1.0)),
                    "status": "PROPOSED",
                }
            )

    if not merged:
        merged = inferred_candidates
        planner_mode = "heuristic"
        planner_reason = planner_reason or "llm parse fallback"

    candidates = [
        {
            "id": f"cand_py_{int(time.time())}_{i}",
            **c,
        }
        for i, c in enumerate(merged[:6])
    ]

    analysis_id = f"py_analysis_{int(time.time() * 1000)}"
    reports = _write_analysis_reports(analysis_id, pages, menu_rows, metrics)

    advisories: List[Dict[str, Any]] = []
    if robots_block_all:
        advisories.append(
            {
                "type": "ROBOTS_BLOCK",
                "severity": "WARN",
                "message": "robots.txt 에서 광범위 차단(Disallow: /) 신호가 감지되었습니다. 크롤 결과가 제한될 수 있습니다.",
                "action": "robots 정책 확인 후 허용 범위에서 점검하거나 인증 기반 점검을 진행하세요.",
            }
        )
    elif robots_requires_review:
        advisories.append(
            {
                "type": "ROBOTS_RULE",
                "severity": "INFO",
                "message": "robots.txt 제한 규칙이 감지되었습니다.",
                "action": "차단 경로를 확인하고 허용 경로 중심으로 점검하세요.",
            }
        )

    if auth_likely or metrics.get("crawled", 0) <= 1:
        advisories.append(
            {
                "type": "AUTH_OR_LIMITED_CRAWL",
                "severity": "INFO",
                "message": "인증이 필요하거나 동적 라우팅으로 수집이 제한될 수 있습니다.",
                "action": "로그인 필요 페이지 점검을 위해 테스트 계정(ID/PW) 제공이 필요합니다.",
                "needsCredentials": True,
            }
        )

    return {
        "ok": True,
        "analysisId": analysis_id,
        "pages": len(pages),
        "elements": 0,
        "serviceType": service_type,
        "authLikely": auth_likely,
        "limits": {
            "maxPages": max_pages,
            "maxDepth": max_depth,
            "hrefOnly": True,
            "sameOriginOnly": True,
            "ignoreRobots": True,
        },
        "plannerMode": planner_mode,
        "plannerReason": planner_reason,
        "metrics": metrics,
        "authPaths": auth_paths,
        "reports": reports,
        "advisories": advisories,
        "robots": {
            "blockAll": robots_block_all,
            "hasRules": robots_requires_review,
        },
        "candidates": candidates,
        "provider": used_provider,
        "model": used_model,
        "_native": {
            "resolvedUrl": target,
            "pages": [p.__dict__ for p in pages],
        },
    }
