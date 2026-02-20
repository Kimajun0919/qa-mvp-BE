from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import xlsxwriter

FIX_COLUMNS = ["경로", "우선순위", "문제상세내용", "진행사항", "테스터", "수정 요청일"]


def _ensure_dirs() -> None:
    Path("out/report").mkdir(parents=True, exist_ok=True)


def write_html_summary(run_id: str, summary: Dict[str, Any], flow_summary: List[Dict[str, Any]], judge: Dict[str, Any]) -> str:
    _ensure_dirs()
    p = Path("out/report/index.html")
    rows = "".join(
        f"<tr><td>{r.get('flowName','')}</td><td>{r.get('status','')}</td><td>{r.get('issueCount',0)}</td><td>{r.get('durationMs',0)}</td></tr>"
        for r in flow_summary
    )
    html = f"""<!doctype html>
<html lang='ko'><head><meta charset='utf-8'><title>QA Run Report</title>
<style>body{{font-family:sans-serif;padding:20px}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px}}</style>
</head><body>
<h2>QA Run Report</h2>
<p>runId: <b>{run_id}</b></p>
<p>final: <b>{summary.get('FINAL','-')}</b></p>
<h3>Summary</h3>
<pre>{summary}</pre>
<h3>Judge</h3>
<pre>{judge}</pre>
<h3>Flow Summary</h3>
<table><thead><tr><th>Flow</th><th>Status</th><th>Issues</th><th>Duration(ms)</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
    p.write_text(html, encoding="utf-8")
    return str(p).replace('\\', '/')


def build_fix_rows(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = datetime.now().strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for i in issues:
        out.append(
            {
                "경로": str(i.get("path") or i.get("url") or ""),
                "우선순위": str(i.get("severity") or "P2"),
                "문제상세내용": str(i.get("actual") or i.get("detail") or ""),
                "진행사항": "수정 필요",
                "테스터": "AUTO",
                "수정 요청일": str(i.get("executedAt") or today)[:10],
            }
        )
    return out


def write_fix_sheet(run_id: str, issues: List[Dict[str, Any]]) -> Dict[str, str]:
    _ensure_dirs()
    rows = build_fix_rows(issues)
    base = Path("out/report") / f"fix_requests_{run_id}"

    # CSV
    csv_path = str(base.with_suffix('.csv')).replace('\\', '/')
    with open(csv_path, "w", encoding="utf-8") as f:
      f.write(",".join(FIX_COLUMNS) + "\n")
      for r in rows:
        f.write(",".join(str(r.get(c, "")).replace(",", " ") for c in FIX_COLUMNS) + "\n")

    # XLSX
    xlsx_path = str(base.with_suffix('.xlsx')).replace('\\', '/')
    wb = xlsxwriter.Workbook(xlsx_path)
    ws = wb.add_worksheet("fix_requests")
    for ci, c in enumerate(FIX_COLUMNS):
        ws.write(0, ci, c)
    for ri, r in enumerate(rows, start=1):
        for ci, c in enumerate(FIX_COLUMNS):
            ws.write(ri, ci, r.get(c, ""))
    wb.close()

    return {"csv": csv_path, "xlsx": xlsx_path}
