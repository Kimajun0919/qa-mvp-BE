import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build

logger = logging.getLogger("qa-mvp-fastapi")

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SUPPORTED_SHEETS = ["checklist", "execution", "fix_sheet"]


@dataclass
class SheetsConfig:
    spreadsheet_id: str
    auth_mode: Literal["service_account", "oauth"]
    service_account_json: str | None = None
    oauth_access_token: str | None = None

    @classmethod
    def from_env(cls) -> "SheetsConfig":
        spreadsheet_id = os.getenv("QA_SHEETS_SPREADSHEET_ID", "").strip()
        auth_mode = os.getenv("QA_SHEETS_AUTH_MODE", "service_account").strip().lower()
        service_account_json = os.getenv("QA_SHEETS_SERVICE_ACCOUNT_JSON", "").strip() or None
        oauth_access_token = os.getenv("QA_SHEETS_OAUTH_ACCESS_TOKEN", "").strip() or None

        if auth_mode not in {"service_account", "oauth"}:
            raise ValueError("QA_SHEETS_AUTH_MODE must be one of: service_account, oauth")
        if not spreadsheet_id:
            raise ValueError("QA_SHEETS_SPREADSHEET_ID is required")

        if auth_mode == "service_account" and not service_account_json:
            raise ValueError("QA_SHEETS_SERVICE_ACCOUNT_JSON is required for service_account mode")
        if auth_mode == "oauth" and not oauth_access_token:
            raise ValueError("QA_SHEETS_OAUTH_ACCESS_TOKEN is required for oauth mode (placeholder)")

        return cls(
            spreadsheet_id=spreadsheet_id,
            auth_mode=auth_mode,
            service_account_json=service_account_json,
            oauth_access_token=oauth_access_token,
        )


class AuthProvider:
    def get_credentials(self):
        raise NotImplementedError


class ServiceAccountAuthProvider(AuthProvider):
    def __init__(self, service_account_json_path: str):
        self.service_account_json_path = Path(service_account_json_path)

    def get_credentials(self):
        if not self.service_account_json_path.exists():
            raise ValueError(f"service account json not found: {self.service_account_json_path}")
        return service_account.Credentials.from_service_account_file(
            str(self.service_account_json_path), scopes=SHEETS_SCOPES
        )


class OAuthPlaceholderAuthProvider(AuthProvider):
    def __init__(self, access_token: str):
        self.access_token = access_token

    def get_credentials(self):
        # Placeholder mode only for phase-1. Token refresh flow is intentionally not implemented.
        if not self.access_token:
            raise ValueError("oauth access token missing")
        return OAuthCredentials(token=self.access_token, scopes=SHEETS_SCOPES)


class GoogleSheetsClient:
    def __init__(self, config: SheetsConfig):
        self.config = config
        auth_provider: AuthProvider
        if config.auth_mode == "service_account":
            auth_provider = ServiceAccountAuthProvider(config.service_account_json or "")
        else:
            auth_provider = OAuthPlaceholderAuthProvider(config.oauth_access_token or "")
        creds = auth_provider.get_credentials()
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def pull_sheet(self, sheet_name: str) -> List[Dict[str, Any]]:
        read_range = f"{sheet_name}!A1:ZZZ"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.config.spreadsheet_id, range=read_range)
            .execute()
        )
        values = result.get("values", [])
        if not values:
            return []

        header = [str(x).strip() for x in values[0]]
        rows = []
        for idx, row in enumerate(values[1:], start=2):
            row_dict = {header[i]: row[i] if i < len(row) else "" for i in range(len(header))}
            row_dict["_row_number"] = idx
            rows.append(row_dict)
        return rows


def _is_iso8601(v: str) -> bool:
    if not v:
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def _is_yyyy_mm_dd(v: str) -> bool:
    if not v:
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_int_ge1(v: Any) -> bool:
    try:
        return int(v) >= 1
    except Exception:
        return False


def _is_number(v: Any) -> bool:
    if v in (None, ""):
        return True
    try:
        float(v)
        return True
    except Exception:
        return False


def validate_sheet_rows(sheet_name: str, rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    required_common = ["id", "title", "status", "priority", "owner", "updated_at", "updated_by", "version"]
    priority_enum = {"low", "medium", "high", "critical"}

    status_enum: Dict[str, set[str]] = {
        "checklist": {"todo", "in_progress", "done", "blocked"},
        "execution": {"queued", "running", "success", "failed", "cancelled"},
        "fix_sheet": {"open", "investigating", "fixing", "qa_done", "closed"},
    }

    valid: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_ids = set()

    for row in rows:
        row_errors: List[str] = []
        row_id = str(row.get("id", "")).strip()

        for col in required_common:
            if str(row.get(col, "")).strip() == "":
                row_errors.append(f"missing required field: {col}")

        if row_id:
            if row_id in seen_ids:
                row_errors.append("duplicate id in sheet")
            seen_ids.add(row_id)

        priority = str(row.get("priority", "")).strip().lower()
        if priority and priority not in priority_enum:
            row_errors.append(f"invalid priority: {priority}")

        status = str(row.get("status", "")).strip().lower()
        if status and status not in status_enum.get(sheet_name, set()):
            row_errors.append(f"invalid status: {status}")

        if str(row.get("updated_at", "")).strip() and not _is_iso8601(str(row.get("updated_at"))):
            row_errors.append("invalid updated_at (expected ISO8601)")

        if str(row.get("version", "")).strip() and not _is_int_ge1(row.get("version")):
            row_errors.append("invalid version (expected integer >= 1)")

        if sheet_name == "checklist":
            due_date = str(row.get("due_date", "")).strip()
            if due_date and not _is_yyyy_mm_dd(due_date):
                row_errors.append("invalid due_date (expected YYYY-MM-DD)")

        elif sheet_name == "execution":
            started_at = str(row.get("started_at", "")).strip()
            ended_at = str(row.get("ended_at", "")).strip()
            if started_at and not _is_iso8601(started_at):
                row_errors.append("invalid started_at (expected ISO8601)")
            if ended_at and not _is_iso8601(ended_at):
                row_errors.append("invalid ended_at (expected ISO8601)")
            if not _is_number(row.get("duration_sec")):
                row_errors.append("invalid duration_sec (expected number)")

        elif sheet_name == "fix_sheet":
            severity = str(row.get("severity", "")).strip()
            if severity and severity not in {"S1", "S2", "S3", "S4"}:
                row_errors.append("invalid severity (expected S1/S2/S3/S4)")

        if row_errors:
            errors.append(
                {
                    "sheet": sheet_name,
                    "row": row.get("_row_number"),
                    "id": row_id,
                    "errors": row_errors,
                }
            )
        else:
            valid.append(row)

    return valid, errors


def audit_log(event: str, detail: Dict[str, Any]) -> None:
    path = Path("out/google_sheets_audit.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event": event,
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def pull_and_validate(sheets: List[str] | None = None) -> Dict[str, Any]:
    cfg = SheetsConfig.from_env()
    selected = sheets or SUPPORTED_SHEETS
    invalid_names = [s for s in selected if s not in SUPPORTED_SHEETS]
    if invalid_names:
        raise ValueError(f"unsupported sheet(s): {', '.join(invalid_names)}")

    client = GoogleSheetsClient(cfg)
    data: Dict[str, Any] = {}
    all_errors: List[Dict[str, Any]] = []
    for sheet in selected:
        rows = client.pull_sheet(sheet)
        valid_rows, errors = validate_sheet_rows(sheet, rows)
        data[sheet] = {
            "rows": valid_rows,
            "rawRowCount": len(rows),
            "validRowCount": len(valid_rows),
            "errorCount": len(errors),
        }
        all_errors.extend(errors)

    summary = {
        "sheetCount": len(selected),
        "totalErrors": len(all_errors),
        "totalValidRows": sum(int(data[s]["validRowCount"]) for s in data),
        "totalRawRows": sum(int(data[s]["rawRowCount"]) for s in data),
    }

    audit_log(
        "google_sheets_pull",
        {
            "sheets": selected,
            "authMode": cfg.auth_mode,
            "spreadsheetId": cfg.spreadsheet_id,
            "summary": summary,
        },
    )

    return {
        "ok": True,
        "mode": "pull-only",
        "spreadsheetId": cfg.spreadsheet_id,
        "authMode": cfg.auth_mode,
        "data": data,
        "errors": all_errors,
        "summary": summary,
    }
