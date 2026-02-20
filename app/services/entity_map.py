from __future__ import annotations

from typing import Any, Dict, List

ENTITY_RULES = [
    {
        "entity": "CONTENT",
        "adminKeywords": ["post", "article", "content", "notice", "blog", "게시", "콘텐츠"],
        "userKeywords": ["blog", "news", "notice", "article", "게시", "공지"],
    },
    {
        "entity": "PRODUCT",
        "adminKeywords": ["product", "item", "catalog", "상품"],
        "userKeywords": ["product", "shop", "store", "item", "상품"],
    },
    {
        "entity": "BANNER",
        "adminKeywords": ["banner", "hero", "popup", "배너"],
        "userKeywords": ["home", "main", "landing", "배너"],
    },
    {
        "entity": "CATEGORY",
        "adminKeywords": ["category", "menu", "taxonomy", "카테고리"],
        "userKeywords": ["category", "menu", "browse", "카테고리"],
    },
    {
        "entity": "USER_ROLE",
        "adminKeywords": ["user", "member", "role", "permission", "권한", "사용자"],
        "userKeywords": ["mypage", "profile", "account", "회원", "프로필"],
    },
]


def _contains_any(text: str, words: List[str]) -> bool:
    t = (text or "").lower()
    return any(w.lower() in t for w in words)


def infer_entity_for_path(path: str, rules: List[Dict[str, Any]] | None = None) -> str:
    p = (path or "").lower()
    for r in (rules or ENTITY_RULES):
        if _contains_any(p, r["adminKeywords"]) or _contains_any(p, r["userKeywords"]):
            return r["entity"]
    return "GENERIC"


def match_admin_user_links(admin_pages: List[Dict[str, Any]], user_pages: List[Dict[str, Any]], rules: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []
    active_rules = rules or ENTITY_RULES

    for a in admin_pages:
        ap = str(a.get("path") or "")
        at = str(a.get("title") or "")
        atext = f"{ap} {at}"

        matched = False
        for r in active_rules:
            if not _contains_any(atext, r["adminKeywords"]):
                continue

            for u in user_pages:
                up = str(u.get("path") or "")
                ut = str(u.get("title") or "")
                utext = f"{up} {ut}"
                if _contains_any(utext, r["userKeywords"]):
                    links.append(
                        {
                            "entity": r["entity"],
                            "adminPath": ap,
                            "userPath": up,
                            "evidence": f"rule:{r['entity']} keywords",
                        }
                    )
                    matched = True

        if not matched:
            links.append(
                {
                    "entity": infer_entity_for_path(ap, active_rules),
                    "adminPath": ap,
                    "userPath": "/",
                    "evidence": "fallback: no explicit entity match",
                }
            )

    # de-dup
    uniq = []
    seen = set()
    for l in links:
        k = (l["entity"], l["adminPath"], l["userPath"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(l)

    return uniq[:80]
