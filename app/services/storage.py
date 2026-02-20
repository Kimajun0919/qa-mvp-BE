from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("QA_FASTAPI_DB_PATH", "out/qa_fastapi.sqlite")

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def migrate() -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_bundle (
                  analysis_id TEXT PRIMARY KEY,
                  base_url TEXT NOT NULL,
                  pages_json TEXT NOT NULL,
                  elements_json TEXT NOT NULL,
                  candidates_json TEXT NOT NULL,
                  flows_json TEXT,
                  created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def save_analysis(analysis_id: str, base_url: str, pages: List[Dict[str, Any]], elements: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """
                INSERT INTO analysis_bundle(analysis_id, base_url, pages_json, elements_json, candidates_json, flows_json, created_at)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT flows_json FROM analysis_bundle WHERE analysis_id = ?), NULL), ?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                  base_url=excluded.base_url,
                  pages_json=excluded.pages_json,
                  elements_json=excluded.elements_json,
                  candidates_json=excluded.candidates_json
                """,
                (
                    analysis_id,
                    base_url,
                    json.dumps(pages, ensure_ascii=False),
                    json.dumps(elements, ensure_ascii=False),
                    json.dumps(candidates, ensure_ascii=False),
                    analysis_id,
                    int(time.time()),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def save_flows(analysis_id: str, flows: List[Dict[str, Any]]) -> bool:
    with _lock:
        conn = _conn()
        try:
            cur = conn.execute("UPDATE analysis_bundle SET flows_json=? WHERE analysis_id=?", (json.dumps(flows, ensure_ascii=False), analysis_id))
            conn.commit()
            return (cur.rowcount or 0) > 0
        finally:
            conn.close()


def get_bundle(analysis_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM analysis_bundle WHERE analysis_id=?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    return {
        "analysis": {"analysisId": row["analysis_id"], "baseUrl": row["base_url"]},
        "pages": json.loads(row["pages_json"] or "[]"),
        "elements": json.loads(row["elements_json"] or "[]"),
        "candidates": json.loads(row["candidates_json"] or "[]"),
        "flows": json.loads(row["flows_json"] or "[]"),
        "createdAt": row["created_at"],
    }
