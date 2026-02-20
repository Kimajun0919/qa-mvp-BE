from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

PROFILES_CANDIDATES = [Path("profiles"), Path("../profiles"), Path("../../profiles")]


def _host_matches(host: str, patterns: List[str]) -> bool:
    h = (host or "").lower()
    for p in patterns or []:
        pp = (p or "").lower()
        if pp == "*":
            return True
        if pp.startswith("*.") and h.endswith(pp[1:]):
            return True
        if h == pp:
            return True
    return False


def _load_all_profiles() -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    seen = set()
    for d in PROFILES_CANDIDATES:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                key = str(f.resolve())
            except Exception:
                key = str(f)
            if key in seen:
                continue
            seen.add(key)
            try:
                profiles.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    return profiles


def get_profile_for_url(url: str) -> Dict[str, Any]:
    host = (urlparse(url).hostname or "").lower()
    all_profiles = _load_all_profiles()

    # 1) exact / wildcard-specific matches (exclude catch-all '*')
    for p in all_profiles:
        patterns = p.get("matchHosts") or []
        non_catch_all = [x for x in patterns if str(x).strip() != "*"]
        if non_catch_all and _host_matches(host, non_catch_all):
            return p

    # 2) catch-all profiles
    for p in all_profiles:
        if _host_matches(host, p.get("matchHosts") or []):
            return p

    # fallback default
    return {
        "siteKey": "default",
        "matchHosts": ["*"],
        "roles": ["guest", "user", "editor", "admin"],
        "entities": [],
    }
