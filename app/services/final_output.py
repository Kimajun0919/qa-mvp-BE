from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import xlsxwriter

DETAIL_COLUMNS = [
    "NO",
    "경로",
    "우선순위",
    "상세",
    "진행사항",
    "테스터",
    "수정 요청일",
    "수정 완료일",
    "수정 상태",
    "비고",
]


def _ensure() -> None:
    Path("out/report").mkdir(parents=True, exist_ok=True)


def _norm_status(v: str) -> str:
    s = (v or "").strip()
    if s in {"PASS", "테스트 완료", "완료"}:
        return "테스트 완료"
    if s in {"FAIL", "수정 필요"}:
        return "수정 필요"
    if s in {"BLOCKED", "재확인 요청"}:
        return "재확인 요청"
    if s in {"N/A", "테스트 불가"}:
        return "테스트 불가"
    if s in {"추후 수정"}:
        return "추후 수정"
    return "테스트 완료"


def _summary_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    keys = ["테스트 완료", "수정 필요", "재확인 요청", "테스트 불가", "추후 수정"]
    c = {k: 0 for k in keys}
    for r in rows:
        st = _norm_status(str(r.get("진행사항") or ""))
        c[st] = c.get(st, 0) + 1
    c["합계"] = len(rows)
    return c


def _row_decomposition_refs(item: Dict[str, Any]) -> Dict[str, str]:
    """Extract compact decomposition linkage refs from execution outputs.

    Backward-compatible: if decomposition data is absent, returns empty refs.
    """
    rows = item.get("decompositionRows")
    if not isinstance(rows, list):
        rows = []

    field_ref = ""
    action_ref = ""
    assertion_ref = ""
    error_ref = ""
    evidence_ref = ""
    actor_ref = str(item.get("Actor") or item.get("actor") or item.get("역할") or "").strip()
    handoff_ref = str(item.get("HandoffKey") or item.get("handoffKey") or item.get("연계키") or "").strip()
    chain_ref = str(item.get("ChainStatus") or item.get("chainStatus") or item.get("체인상태") or "").strip()

    for r in rows:
        if not isinstance(r, dict):
            continue
        kind = str(r.get("kind") or "").upper().strip()
        field = str(r.get("field") or "").strip()
        action = str(r.get("action") or "").strip()
        assertion = r.get("assertion") if isinstance(r.get("assertion"), dict) else {}
        evidence = r.get("evidence") if isinstance(r.get("evidence"), dict) else {}

        if not actor_ref:
            actor_ref = str(r.get("Actor") or r.get("actor") or "").strip()
        if not handoff_ref:
            handoff_ref = str(r.get("HandoffKey") or r.get("handoffKey") or "").strip()
        if not chain_ref:
            chain_ref = str(r.get("ChainStatus") or r.get("chainStatus") or "").strip()

        if (not field_ref) and field:
            field_ref = field
        if kind == "FIELD":
            if field and not field_ref:
                field_ref = field
        elif kind == "ACTION":
            if action and not action_ref:
                action_ref = action
        elif kind == "ASSERTION":
            exp = str(assertion.get("expected") or "").strip()
            obs = str(assertion.get("observed") or "").strip()
            fc = str(assertion.get("failureCode") or "").strip()
            if (exp or obs) and not assertion_ref:
                assertion_ref = f"exp={exp or '-'}|obs={obs or '-'}"
            if fc and fc != "OK" and not error_ref:
                error_ref = fc

        if not evidence_ref:
            shot = str(evidence.get("screenshotPath") or "").strip()
            url = str(evidence.get("observedUrl") or "").strip()
            status = str(evidence.get("httpStatus") or "").strip()
            kind = str(evidence.get("scenarioKind") or "").strip()
            ts = str(evidence.get("timestamp") or "").strip()
            if shot or url or status or kind or ts:
                bits = []
                if status:
                    bits.append(f"http={status}")
                if url:
                    bits.append(f"url={url}")
                if kind:
                    bits.append(f"kind={kind}")
                if ts:
                    bits.append(f"ts={ts}")
                if shot:
                    bits.append(f"shot={shot}")
                evidence_ref = "|".join(bits)

    # fallback to failureDecomposition (legacy shape)
    fd = item.get("failureDecomposition") if isinstance(item.get("failureDecomposition"), dict) else {}
    if not field_ref:
        field_ref = str(fd.get("field") or "").strip()
    if not action_ref:
        action_ref = str(fd.get("action") or "").strip()
    if not assertion_ref:
        a = fd.get("assertion") if isinstance(fd.get("assertion"), dict) else {}
        exp = str(a.get("expected") or "").strip()
        obs = str(a.get("observed") or "").strip()
        if exp or obs:
            assertion_ref = f"exp={exp or '-'}|obs={obs or '-'}"
    if not error_ref:
        error_ref = str(item.get("실패코드") or item.get("failureCode") or item.get("error") or (fd.get("assertion") or {}).get("failureCode") or "").strip()
    if not evidence_ref:
        em = item.get("증거메타") if isinstance(item.get("증거메타"), dict) else {}
        shot = str(em.get("screenshotPath") or item.get("증거") or "").strip()
        url = str(em.get("observedUrl") or "").strip()
        status = str(em.get("httpStatus") or "").strip()
        kind = str(em.get("scenarioKind") or "").strip()
        ts = str(em.get("timestamp") or "").strip()
        bits = []
        if status:
            bits.append(f"http={status}")
        if url:
            bits.append(f"url={url}")
        if kind:
            bits.append(f"kind={kind}")
        if ts:
            bits.append(f"ts={ts}")
        if shot:
            bits.append(f"shot={shot}")
        evidence_ref = "|".join(bits)
    if not evidence_ref:
        e = fd.get("evidence") if isinstance(fd.get("evidence"), dict) else {}
        shot = str(e.get("screenshotPath") or "").strip()
        url = str(e.get("observedUrl") or "").strip()
        status = str(e.get("httpStatus") or "").strip()
        kind = str(e.get("scenarioKind") or "").strip()
        ts = str(e.get("timestamp") or "").strip()
        bits = []
        if status:
            bits.append(f"http={status}")
        if url:
            bits.append(f"url={url}")
        if kind:
            bits.append(f"kind={kind}")
        if ts:
            bits.append(f"ts={ts}")
        if shot:
            bits.append(f"shot={shot}")
        evidence_ref = "|".join(bits)

    return {
        "field": field_ref,
        "action": action_ref,
        "assertion": assertion_ref,
        "error": error_ref,
        "evidence": evidence_ref,
        "actor": actor_ref,
        "handoff": handoff_ref,
        "chain": chain_ref,
    }


def _with_decomposition_density(item: Dict[str, Any], detail: str, note: str) -> tuple[str, str]:
    refs = _row_decomposition_refs(item)
    # Always preserve the five-slot decomposition shape for downstream parsers.
    normalized = {
        "field": refs.get("field") or "-",
        "action": refs.get("action") or "-",
        "assert": refs.get("assertion") or "-",
        "error": refs.get("error") or "-",
        "evidence": refs.get("evidence") or "-",
        "actor": refs.get("actor") or "-",
        "handoff": refs.get("handoff") or "-",
        "chain": refs.get("chain") or "-",
    }
    ref_tokens = [
        f"field:{normalized['field']}",
        f"action:{normalized['action']}",
        f"assert:{normalized['assert']}",
        f"error:{normalized['error']}",
        f"evidence:{normalized['evidence']}",
        f"actor:{normalized['actor']}",
        f"handoff:{normalized['handoff']}",
        f"chain:{normalized['chain']}",
    ]

    enriched_detail = detail
    if not enriched_detail:
        enriched_detail = f"field:{normalized['field']} / action:{normalized['action']}"
    elif "field:" not in enriched_detail:
        enriched_detail = f"{enriched_detail} | field:{normalized['field']}"

    links = "decompRefs=" + " ; ".join(ref_tokens)
    enriched_note = f"{note} | {links}" if note else links
    return enriched_detail, enriched_note


def _to_detail_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = datetime.now().strftime("%y.%m.%d")
    out: List[Dict[str, Any]] = []
    for i, it in enumerate(items, start=1):
        raw_status = str(it.get("진행사항") or it.get("ChainStatus") or it.get("실행결과") or it.get("status") or "")
        status = _norm_status(raw_status)
        detail = str(it.get("상세") or it.get("detail") or it.get("테스트시나리오") or "")
        note = str(it.get("비고") or it.get("note") or "")
        detail, note = _with_decomposition_density(it, detail, note)

        out.append(
            {
                "NO": i,
                "경로": str(it.get("경로") or it.get("path") or it.get("url") or ""),
                "우선순위": str(it.get("우선순위") or it.get("priority") or ""),
                "상세": detail,
                "진행사항": status,
                "테스터": str(it.get("테스터") or it.get("tester") or "AUTO"),
                "수정 요청일": str(it.get("수정 요청일") or it.get("requestedAt") or today),
                "수정 완료일": str(it.get("수정 완료일") or it.get("fixedAt") or ""),
                "수정 상태": str(it.get("수정 상태") or it.get("fixStatus") or ""),
                "비고": note,
            }
        )
    return out


def write_final_testsheet(run_id: str, project_name: str, items: List[Dict[str, Any]]) -> Dict[str, str]:
    _ensure()
    rows = _to_detail_rows(items)
    summary = _summary_counts(rows)

    csv_path = f"out/report/final_testsheet_{run_id}.csv"
    xlsx_path = f"out/report/final_testsheet_{run_id}.xlsx"

    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write(f",{project_name}\n")
        for k in ["테스트 완료", "수정 필요", "재확인 요청", "테스트 불가", "추후 수정", "합계"]:
            total = max(1, summary.get("합계", 0))
            pct = 100.0 * summary.get(k, 0) / total
            f.write(f",,,,,{k},{summary.get(k,0)},{pct:.2f}%\n")
        f.write("\n")
        f.write(",".join(DETAIL_COLUMNS) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(c, "")).replace(",", " ") for c in DETAIL_COLUMNS) + "\n")

    wb = xlsxwriter.Workbook(xlsx_path)
    ws = wb.add_worksheet("final")
    ws.write(0, 1, project_name)
    ri = 2
    for k in ["테스트 완료", "수정 필요", "재확인 요청", "테스트 불가", "추후 수정", "합계"]:
        total = max(1, summary.get("합계", 0))
        pct = 100.0 * summary.get(k, 0) / total
        ws.write(ri, 5, k)
        ws.write(ri, 6, summary.get(k, 0))
        ws.write(ri, 7, f"{pct:.2f}%")
        ri += 1

    ri += 1
    for ci, c in enumerate(DETAIL_COLUMNS):
        ws.write(ri, ci, c)
    for rix, r in enumerate(rows, start=ri + 1):
        for ci, c in enumerate(DETAIL_COLUMNS):
            ws.write(rix, ci, r.get(c, ""))
    wb.close()

    return {"csv": csv_path, "xlsx": xlsx_path}
