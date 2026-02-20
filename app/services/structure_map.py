from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def _path_segments(path: str) -> List[str]:
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    if p == "/":
        return ["/"]
    return [s for s in p.split("/") if s]


def _insert(tree: Dict[str, Any], path: str, role: str) -> None:
    segs = _path_segments(path)
    node = tree
    if segs == ["/"]:
        node.setdefault("/", {"_meta": {"roles": set(), "count": 0}, "children": {}})
        node["/"]["_meta"]["roles"].add(role)
        node["/"]["_meta"]["count"] += 1
        return

    cur = node.setdefault("/", {"_meta": {"roles": set(), "count": 0}, "children": {}})
    cur["_meta"]["count"] += 1
    cur["_meta"]["roles"].add(role)
    for s in segs:
        ch = cur["children"].setdefault(s, {"_meta": {"roles": set(), "count": 0}, "children": {}})
        ch["_meta"]["count"] += 1
        ch["_meta"]["roles"].add(role)
        cur = ch


def _serialize(node: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in node.items():
        out[k] = {
            "meta": {
                "roles": sorted(list(v.get("_meta", {}).get("roles", set()))),
                "count": int(v.get("_meta", {}).get("count", 0)),
            },
            "children": _serialize(v.get("children", {})),
        }
    return out


def build_structure_map(bundle: Dict[str, Any], flow_map: Dict[str, Any]) -> Dict[str, Any]:
    pages = bundle.get("pages", []) or []
    analysis = bundle.get("analysis", {}) or {}

    tree: Dict[str, Any] = {}
    role_graph = defaultdict(lambda: {"to": set(), "paths": 0})

    for p in pages:
        path = str(p.get("path") or "/")
        role = str(p.get("role") or "LANDING")
        _insert(tree, path, role)
        role_graph[role]["paths"] += 1

    for link in (flow_map.get("links") or []):
        admin_action = str(link.get("adminAction") or "")
        user_impact = str(link.get("userImpact") or "")
        src_role = "DASHBOARD" if "admin" in admin_action.lower() or "관리" in admin_action else "UNKNOWN"
        dst_role = "LANDING"
        if any(k in user_impact.lower() for k in ["login", "로그인"]):
            dst_role = "LOGIN"
        elif any(k in user_impact.lower() for k in ["checkout", "결제", "order"]):
            dst_role = "CHECKOUT"
        role_graph[src_role]["to"].add(dst_role)

    graph = [
        {"role": r, "paths": v["paths"], "to": sorted(list(v["to"]))}
        for r, v in role_graph.items()
    ]

    return {
        "ok": True,
        "analysisId": analysis.get("analysisId", ""),
        "pathTree": _serialize(tree),
        "roleGraph": graph,
        "entityLinks": flow_map.get("links", []),
        "stats": {
            "pageCount": len(pages),
            "roleCount": len(graph),
            "entityLinkCount": len(flow_map.get("links", [])),
        },
    }
