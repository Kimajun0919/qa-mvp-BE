from __future__ import annotations

from typing import Any, Dict, List

from .entity_map import match_admin_user_links
from .site_profile import get_profile_for_url


def _priority_from_role(role: str) -> str:
    r = (role or "").upper()
    if r in {"CHECKOUT", "LOGIN"}:
        return "P1"
    if r in {"DASHBOARD"}:
        return "P1"
    return "P2"


def _link_score(entity: str, priority: str, evidence: str, verification_path: List[str]) -> float:
    score = 0.5
    if entity in {"CONTENT", "PRODUCT", "USER_ROLE"}:
        score += 0.2
    if priority == "P1":
        score += 0.2
    if "rule:" in (evidence or ""):
        score += 0.1
    if len([p for p in verification_path if p]) >= 2:
        score += 0.05
    return round(min(score, 0.99), 2)


def _risk_level(priority: str, score: float) -> str:
    if priority == "P1" and score >= 0.8:
        return "HIGH"
    if score >= 0.65:
        return "MEDIUM"
    return "LOW"


def build_flow_map(bundle: Dict[str, Any], screen: str = "", context: str = "") -> Dict[str, Any]:
    pages: List[Dict[str, Any]] = bundle.get("pages", []) or []
    candidates: List[Dict[str, Any]] = bundle.get("candidates", []) or []
    base_url = str((bundle.get("analysis") or {}).get("baseUrl") or "")
    profile = get_profile_for_url(base_url)
    profile_rules = profile.get("entities") or []

    admin_pages = [p for p in pages if str(p.get("role", "")).upper() in {"DASHBOARD"} or "admin" in str(p.get("path", "")).lower()]
    user_pages = [p for p in pages if p not in admin_pages]

    links: List[Dict[str, Any]] = []

    matched = match_admin_user_links(admin_pages[:20], user_pages[:40], rules=profile_rules)
    for m in matched:
        u_role = "LANDING"
        for u in user_pages:
            if str(u.get("path") or "") == m.get("userPath"):
                u_role = str(u.get("role") or "LANDING")
                break
        verification_path = [m.get("adminPath"), m.get("userPath")]
        priority = _priority_from_role(u_role)
        evidence = str(m.get("evidence") or "")
        score = _link_score(str(m.get("entity") or "GENERIC"), priority, evidence, verification_path)
        links.append(
            {
                "entity": m.get("entity"),
                "adminAction": f"{m.get('adminPath')}에서 {m.get('entity')} 변경",
                "userImpact": f"{m.get('userPath')} 노출/동작 변화",
                "verificationPath": verification_path,
                "priority": priority,
                "reason": "관리자 변경사항이 사용자 화면 반영에 영향",
                "evidencePath": evidence,
                "score": score,
                "riskLevel": _risk_level(priority, score),
            }
        )

    if not links:
        # fallback when no explicit admin route is discovered
        for c in candidates[:5]:
            name = str(c.get("name") or "Flow")
            ptype = str(c.get("platformType") or "LANDING")
            priority = "P1" if ptype in {"LOGIN", "CHECKOUT", "DASHBOARD"} else "P2"
            verification_path = ["/admin", "/"]
            evidence = "candidate inference"
            score = _link_score("CANDIDATE", priority, evidence, verification_path)
            links.append(
                {
                    "entity": "CANDIDATE",
                    "adminAction": "관리자에서 관련 데이터 변경",
                    "userImpact": f"사용자 플로우({name}) 결과 변화",
                    "verificationPath": verification_path,
                    "priority": priority,
                    "reason": f"candidate flow 기반 연결 추정 ({ptype})",
                    "evidencePath": evidence,
                    "score": score,
                    "riskLevel": _risk_level(priority, score),
                }
            )

    if screen or context:
        verification_path = ["/admin", "/"]
        priority = "P1"
        evidence = "request context"
        score = _link_score("CONTEXT", priority, evidence, verification_path)
        links.insert(
            0,
            {
                "entity": "CONTEXT",
                "adminAction": f"'{screen or '대상 화면'}' 관련 관리자 설정 변경",
                "userImpact": f"'{screen or '대상 화면'}' 사용자 경험/결과 확인",
                "verificationPath": verification_path,
                "priority": priority,
                "reason": (context or "요청 컨텍스트 기반 우선 검증"),
                "evidencePath": evidence,
                "score": score,
                "riskLevel": _risk_level(priority, score),
            },
        )

    ranked = sorted(links, key=lambda x: (x.get("priority") == "P1", x.get("score", 0)), reverse=True)
    return {
        "ok": True,
        "analysisId": (bundle.get("analysis") or {}).get("analysisId", ""),
        "siteProfile": profile.get("siteKey", "default"),
        "totalLinks": len(ranked),
        "avgScore": round(sum(float(x.get("score", 0)) for x in ranked) / max(1, len(ranked)), 2),
        "links": ranked[:30],
    }
