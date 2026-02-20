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


def _to_detail_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = datetime.now().strftime("%y.%m.%d")
    out: List[Dict[str, Any]] = []
    for i, it in enumerate(items, start=1):
        raw_status = str(it.get("진행사항") or it.get("실행결과") or it.get("status") or "")
        status = _norm_status(raw_status)
        out.append(
            {
                "NO": i,
                "경로": str(it.get("경로") or it.get("path") or it.get("url") or ""),
                "우선순위": str(it.get("우선순위") or it.get("priority") or ""),
                "상세": str(it.get("상세") or it.get("detail") or it.get("테스트시나리오") or ""),
                "진행사항": status,
                "테스터": str(it.get("테스터") or it.get("tester") or "AUTO"),
                "수정 요청일": str(it.get("수정 요청일") or it.get("requestedAt") or today),
                "수정 완료일": str(it.get("수정 완료일") or it.get("fixedAt") or ""),
                "수정 상태": str(it.get("수정 상태") or it.get("fixStatus") or ""),
                "비고": str(it.get("비고") or it.get("note") or ""),
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
