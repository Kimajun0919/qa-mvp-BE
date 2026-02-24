from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import xlsxwriter

FIX_COLUMNS = [
    "경로",
    "우선순위",
    "문제상세내용",
    "진행사항",
    "테스터",
    "수정 요청일",
    "Actor",
    "HandoffKey",
    "ChainStatus",
    "ErrorCode",
    "Evidence",
    "Completeness",
]


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


def _pick_path(issue: Dict[str, Any]) -> str:
    evidence_meta = issue.get("증거메타") if isinstance(issue.get("증거메타"), dict) else {}
    return str(
        issue.get("path")
        or issue.get("url")
        or issue.get("module")
        or evidence_meta.get("observedUrl")
        or ""
    )


def _pick_actor(issue: Dict[str, Any]) -> str:
    actor = str(issue.get("Actor") or issue.get("actor") or issue.get("역할") or "").strip().upper()
    return actor if actor in {"USER", "ADMIN"} else "USER"


def _pick_handoff_key(issue: Dict[str, Any]) -> str:
    return str(issue.get("HandoffKey") or issue.get("handoffKey") or issue.get("연계키") or "").strip()


def _pick_chain_status(issue: Dict[str, Any]) -> str:
    status = str(issue.get("ChainStatus") or issue.get("chainStatus") or issue.get("실행결과") or issue.get("status") or "").strip().upper()
    return status or "FAIL"


def _pick_error_code(issue: Dict[str, Any]) -> str:
    return str(issue.get("실패코드") or issue.get("failureCode") or issue.get("errorCode") or "ASSERT_UNKNOWN").strip()


def _pick_evidence(issue: Dict[str, Any]) -> str:
    evidence_meta = issue.get("증거메타") if isinstance(issue.get("증거메타"), dict) else {}
    raw = str(issue.get("증거") or issue.get("screenshotPath") or evidence_meta.get("screenshotPath") or "").strip()
    if raw:
        return raw
    observed_url = str(evidence_meta.get("observedUrl") or "").strip()
    return observed_url


def _completeness(actor: str, handoff_key: str, chain_status: str, error_code: str, evidence: str) -> str:
    missing: List[str] = []
    if not actor:
        missing.append("Actor")
    if not handoff_key:
        missing.append("HandoffKey")
    if not chain_status:
        missing.append("ChainStatus")
    if not error_code:
        missing.append("ErrorCode")
    if not evidence:
        missing.append("Evidence")
    return "OK" if not missing else f"MISSING:{'|'.join(missing)}"


def build_fix_rows(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = datetime.now().strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for i in issues:
        actor = _pick_actor(i)
        handoff_key = _pick_handoff_key(i)
        chain_status = _pick_chain_status(i)
        error_code = _pick_error_code(i)
        evidence = _pick_evidence(i)
        out.append(
            {
                "경로": _pick_path(i),
                "우선순위": str(i.get("severity") or i.get("우선순위") or "P2"),
                "문제상세내용": str(i.get("actual") or i.get("detail") or i.get("테스트시나리오") or ""),
                "진행사항": "수정 필요",
                "테스터": str(i.get("tester") or i.get("테스터") or "AUTO"),
                "수정 요청일": str(i.get("executedAt") or i.get("수정 요청일") or today)[:10],
                "Actor": actor,
                "HandoffKey": handoff_key,
                "ChainStatus": chain_status,
                "ErrorCode": error_code,
                "Evidence": evidence,
                "Completeness": _completeness(actor, handoff_key, chain_status, error_code, evidence),
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
