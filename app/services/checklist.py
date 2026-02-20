from typing import Any, Dict, List, Optional

from .llm import chat_json, parse_json_text

COLUMNS = ["화면", "구분", "테스트시나리오", "확인"]


def _heuristic_rows(screen: str, context: str = "", include_auth: bool = False) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = [
        {"화면": screen, "구분": "퍼블리싱", "테스트시나리오": context or "UI 요소 렌더링 및 정렬 확인", "확인": ""},
        {"화면": screen, "구분": "기능", "테스트시나리오": "주요 버튼/링크 동작 확인", "확인": ""},
        {"화면": screen, "구분": "예외", "테스트시나리오": "필수값 누락/잘못된 입력 처리 확인", "확인": ""},
    ]
    if include_auth:
        rows.append({"화면": screen, "구분": "권한", "테스트시나리오": "비로그인/권한없는 사용자 접근 차단 확인", "확인": ""})
    return rows


def _rows_to_tsv(rows: List[Dict[str, str]]) -> str:
    head = "\t".join(COLUMNS)
    body = ["\t".join(str(r.get(c, "")) for c in COLUMNS) for r in rows]
    return "\n".join([head, *body])


async def generate_checklist(
    screen: str,
    context: str = "",
    include_auth: bool = False,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    llm_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    system = (
        "당신은 QA 테스트 설계자다. 반드시 JSON만 반환한다. "
        "마크다운/설명 금지. 오직 JSON. "
        "스키마: {\"rows\":[{\"화면\":string,\"구분\":string,\"테스트시나리오\":string,\"확인\":string}]}"
    )
    role_hint = "admin" if any(k in (screen + ' ' + context).lower() for k in ["admin", "cms", "관리", "권한"]) else "user"
    user = (
        f"화면: {screen}\n"
        f"컨텍스트: {context}\n"
        f"권한체크 포함: {include_auth}\n"
        f"roleHint: {role_hint}\n"
        "실무용 체크리스트 10~14개를 생성해라. 정상/예외/경계/권한/회귀를 포함하고 중복 금지."
        " roleHint=admin 이면 발행/권한승격/감사로그 항목을 반드시 포함."
    )

    ok, content_or_err, used_provider, used_model = await chat_json(system, user, provider=provider, model=model, llm_auth=llm_auth)
    if not ok:
        rows = _heuristic_rows(screen, context, include_auth)
        return {
            "ok": True,
            "mode": "heuristic",
            "reason": content_or_err,
            "columns": COLUMNS,
            "rows": rows,
            "tsv": _rows_to_tsv(rows),
            "provider": used_provider,
            "model": used_model,
        }

    data = parse_json_text(content_or_err)
    raw_rows = None
    if isinstance(data, dict):
        raw_rows = data.get("rows") or data.get("items") or data.get("checklist")
    rows: List[Dict[str, str]] = []
    if isinstance(raw_rows, list):
        for r in raw_rows[:20]:
            if not isinstance(r, dict):
                continue
            # key alias normalization for small models
            row = {
                "화면": str(r.get("화면") or r.get("screen") or r.get("page") or "").strip(),
                "구분": str(r.get("구분") or r.get("type") or r.get("category") or "").strip(),
                "테스트시나리오": str(r.get("테스트시나리오") or r.get("scenario") or r.get("test") or r.get("description") or "").strip(),
                "확인": str(r.get("확인") or r.get("check") or r.get("result") or "").strip(),
            }
            if not row["화면"]:
                row["화면"] = screen
            if row["구분"] and row["테스트시나리오"]:
                rows.append(row)

    if len(rows) < 6:
        rows = _heuristic_rows(screen, context, include_auth)
        if "admin" in (screen + ' ' + context).lower() or "cms" in (screen + ' ' + context).lower() or "관리" in (screen + ' ' + context):
            rows.extend([
                {"화면": screen, "구분": "권한", "테스트시나리오": "권한 없는 계정의 발행 버튼 접근 차단 확인", "확인": ""},
                {"화면": screen, "구분": "기능", "테스트시나리오": "게시물 발행/비공개 전환 후 사용자 화면 반영 확인", "확인": ""},
                {"화면": screen, "구분": "운영", "테스트시나리오": "감사로그(변경 이력) 기록 확인", "확인": ""},
            ])
        return {
            "ok": True,
            "mode": "heuristic",
            "reason": "llm sparse fallback",
            "columns": COLUMNS,
            "rows": rows,
            "tsv": _rows_to_tsv(rows),
            "provider": used_provider,
            "model": used_model,
        }

    return {
        "ok": True,
        "mode": "llm",
        "reason": "",
        "columns": COLUMNS,
        "rows": rows,
        "tsv": _rows_to_tsv(rows),
        "provider": used_provider,
        "model": used_model,
    }
