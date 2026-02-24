from itertools import product
from typing import Any, Dict, List, Optional, Set

from .llm import chat_json, parse_json_text

BASE_COLUMNS = ["화면", "구분", "테스트시나리오", "확인"]
GRANULAR_COLUMNS = ["module", "element", "action", "expected", "actual", "Actor", "HandoffKey", "ChainStatus"]
COLUMNS = BASE_COLUMNS + GRANULAR_COLUMNS
EXPANSION_KEYS = {"field", "action", "assertion"}


def _normalize_row(row: Dict[str, Any], *, default_screen: str = "") -> Dict[str, str]:
    module = str(
        row.get("module")
        or row.get("모듈")
        or row.get("화면")
        or row.get("screen")
        or row.get("page")
        or default_screen
        or ""
    ).strip()
    category = str(row.get("구분") or row.get("type") or row.get("category") or "").strip()
    action = str(
        row.get("action")
        or row.get("동작")
        or row.get("테스트시나리오")
        or row.get("scenario")
        or row.get("test")
        or row.get("description")
        or ""
    ).strip()
    expected = str(row.get("expected") or row.get("기대결과") or row.get("확인") or row.get("check") or row.get("result") or "").strip()
    actual = str(row.get("actual") or row.get("실제결과") or "").strip()
    element = str(row.get("element") or row.get("요소") or row.get("target") or "").strip()

    scenario = action
    if expected and expected not in scenario:
        scenario = f"{scenario} - {expected}" if scenario else expected

    actor = str(row.get("Actor") or row.get("actor") or row.get("역할") or "USER").strip().upper()
    if actor not in {"USER", "ADMIN"}:
        actor = "USER"
    handoff_key = str(row.get("HandoffKey") or row.get("handoffKey") or row.get("연계키") or "").strip()
    chain_status = str(row.get("ChainStatus") or row.get("chainStatus") or row.get("체인상태") or "").strip()

    return {
        # backward-compatible fields
        "화면": module,
        "구분": category,
        "테스트시나리오": scenario,
        "확인": actual or expected,
        # granular fields
        "module": module,
        "element": element,
        "action": action,
        "expected": expected,
        "actual": actual,
        # interaction-linking metadata (additive, backward-compatible)
        "Actor": actor,
        "HandoffKey": handoff_key,
        "ChainStatus": chain_status,
    }


def _split_parts(text: str, delimiters: List[str], max_parts: int = 4) -> List[str]:
    out = [str(text or "").strip()]
    for d in delimiters:
        next_out: List[str] = []
        for item in out:
            if d in item:
                next_out.extend([p.strip() for p in item.split(d)])
            else:
                next_out.append(item)
        out = next_out
    dedup: List[str] = []
    seen = set()
    for item in out:
        if not item or item in seen:
            continue
        seen.add(item)
        dedup.append(item)
        if len(dedup) >= max_parts:
            break
    return dedup or [str(text or "").strip()]


def _resolve_expansion(expand: bool = False, mode: str = "none") -> Set[str]:
    m = (mode or "none").strip().lower()
    # backward-compat guardrail: legacy callers may send checklistExpand=true without mode
    if m in ("none", "off", "false", "0", ""):
        return set(EXPANSION_KEYS) if expand else set()
    if m == "all":
        return set(EXPANSION_KEYS)
    keys = {x.strip() for x in m.split(",") if x.strip()}
    keys = {"field" if k == "element" else k for k in keys}
    keys = keys.intersection(EXPANSION_KEYS)
    if keys:
        return keys
    return set(EXPANSION_KEYS) if expand else set()


def _expand_rows(rows: List[Dict[str, str]], expansion: Set[str], max_rows: int) -> List[Dict[str, str]]:
    if not expansion:
        return rows[:max_rows]

    expanded: List[Dict[str, str]] = []
    seen = set()

    for row in rows:
        elements = [row.get("element", "")]
        actions = [row.get("action", "")]
        assertions = [row.get("expected", "")]

        if "field" in expansion:
            elements = _split_parts(elements[0], [",", "/", "|", " 및 ", " 와 ", " + "])
        if "action" in expansion:
            actions = _split_parts(actions[0], [";", "->", " 후 ", " 그리고 ", " 및 "])
        if "assertion" in expansion:
            assertions = _split_parts(assertions[0], [";", " 그리고 ", " 및 ", " / "])

        for element, action, expected in product(elements, actions, assertions):
            candidate = _normalize_row(
                {
                    **row,
                    "module": row.get("module", ""),
                    "구분": row.get("구분", ""),
                    "element": element,
                    "action": action,
                    "expected": expected,
                    "actual": row.get("actual", ""),
                },
                default_screen=row.get("module", ""),
            )
            key = f"{candidate.get('module','')}::{candidate.get('element','')}::{candidate.get('action','')}::{candidate.get('expected','')}"
            if key in seen:
                continue
            seen.add(key)
            expanded.append(candidate)
            if len(expanded) >= max_rows:
                return expanded

    return expanded or rows[:max_rows]


def _is_board_domain(screen: str, context: str = "") -> bool:
    low = f"{screen} {context}".lower()
    return any(k in low for k in ["board", "post", "article", "notice", "forum", "thread", "게시", "게시판", "글", "공지", "댓글", "첨부"])


def _screen_sections(screen: str, context: str = "") -> List[str]:
    low = f"{screen} {context}".lower()
    sections: List[str] = ["헤더", "메인콘텐츠", "푸터"]
    if any(k in low for k in ["form", "input", "회원", "로그인", "신청", "입력"]):
        sections.append("폼영역")
    if any(k in low for k in ["table", "list", "목록", "게시", "card"]):
        sections.append("목록영역")
    if any(k in low for k in ["modal", "dialog", "popup", "모달"]):
        sections.append("모달영역")
    if _is_board_domain(screen, context):
        sections.extend(["게시목록", "게시상세", "게시작성"])

    dedup: List[str] = []
    seen = set()
    for x in sections:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup


def _heuristic_rows(screen: str, context: str = "", include_auth: bool = False) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for section in _screen_sections(screen, context):
        module = f"{screen}::{section}"
        rows.extend([
            _normalize_row({"화면": module, "구분": "퍼블리싱", "element": section, "action": f"{section} UI 렌더링/정렬을 점검한다", "expected": "레이아웃 깨짐/겹침 없이 노출", "actual": ""}, default_screen=module),
            _normalize_row({"화면": module, "구분": "기능", "element": section, "action": f"{section}의 주요 버튼/링크를 클릭한다", "expected": "의도한 화면 또는 상태로 전환", "actual": ""}, default_screen=module),
            _normalize_row({"화면": module, "구분": "예외", "element": section, "action": f"{section}에서 필수값 누락 또는 잘못된 입력으로 제출한다", "expected": "유효성 오류가 노출되고 제출 차단", "actual": ""}, default_screen=module),
        ])

    if _is_board_domain(screen, context):
        board_module = f"{screen}::게시판핵심"
        rows.extend([
            _normalize_row({"화면": board_module, "구분": "기능", "element": "게시목록", "action": "게시글 목록을 최신순/조회순으로 정렬 전환한다", "expected": "정렬 기준이 반영되고 목록 순서가 즉시 변경", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "기능", "element": "검색/필터", "action": "제목 키워드 검색과 카테고리 필터를 조합한다", "expected": "조건에 맞는 결과만 노출되고 건수 표시가 일치", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "경계", "element": "페이지네이션", "action": "첫/마지막 페이지와 빈 결과 페이지를 이동한다", "expected": "페이지 이동이 정상이며 빈 상태 문구가 노출", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "기능", "element": "게시상세", "action": "목록에서 상세 진입 후 다시 목록으로 복귀한다", "expected": "이전 목록 상태(정렬/필터/페이지)가 유지", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "예외", "element": "게시작성", "action": "제목/본문 필수값 누락 상태에서 임시저장을 시도한다", "expected": "필수값 오류를 노출하고 비정상 저장을 차단", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "기능", "element": "첨부파일", "action": "허용 확장자 파일 첨부 후 첨부목록에서 미리보기를 확인한다", "expected": "첨부 업로드 상태와 파일 메타정보가 정확히 반영", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "예외", "element": "첨부파일", "action": "제한 용량 초과 또는 금지 확장자 첨부를 시도한다", "expected": "업로드가 거부되고 오류 가이드를 노출", "actual": ""}, default_screen=board_module),
            _normalize_row({"화면": board_module, "구분": "회귀", "element": "댓글", "action": "댓글 작성/수정 후 새로고침하여 반영 상태를 확인한다", "expected": "저장 상태가 유지되고 중복 작성이 발생하지 않음", "actual": ""}, default_screen=board_module),
        ])

    if include_auth:
        rows.append(
            _normalize_row({"화면": f"{screen}::접근제어", "구분": "권한", "element": "접근제어", "action": "비로그인/권한없는 사용자로 접근한다", "expected": "접근 차단 또는 로그인 유도", "actual": ""}, default_screen=screen)
        )
    return rows[:40]


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
    expand: bool = False,
    expand_mode: str = "none",
    max_rows: int = 20,
) -> Dict[str, Any]:
    system = (
        "당신은 QA 테스트 설계자다. 반드시 JSON만 반환한다. "
        "마크다운/설명 금지. 오직 JSON. "
        "스키마: {\"rows\":[{\"module\":string,\"element\":string,\"action\":string,\"expected\":string,\"actual\":string,\"구분\":string,\"화면\":string,\"테스트시나리오\":string,\"확인\":string}]}"
    )
    role_hint = "admin" if any(k in (screen + ' ' + context).lower() for k in ["admin", "cms", "관리", "권한"]) else "user"
    user = (
        f"화면: {screen}\n"
        f"컨텍스트: {context}\n"
        f"권한체크 포함: {include_auth}\n"
        f"roleHint: {role_hint}\n"
        "실무용 체크리스트 10~14개를 생성해라. 정상/예외/경계/권한/회귀를 포함하고 중복 금지."
        " 각 row는 module/element/action/expected/actual/구분 값을 채워라(actual은 빈문자열 허용)."
        " roleHint=admin 이면 발행/권한승격/감사로그 항목을 반드시 포함."
    )

    expansion = _resolve_expansion(expand=expand, mode=expand_mode)
    raw_limit = max(6, min(int(max_rows or 20), 300))

    ok, content_or_err, used_provider, used_model = await chat_json(system, user, provider=provider, model=model, llm_auth=llm_auth)
    if not ok:
        rows = _expand_rows(_heuristic_rows(screen, context, include_auth), expansion, raw_limit)
        return {
            "ok": True,
            "mode": "heuristic",
            "reason": content_or_err,
            "columns": COLUMNS,
            "rows": rows,
            "tsv": _rows_to_tsv(rows),
            "provider": used_provider,
            "model": used_model,
            "expansion": {"enabled": bool(expansion), "modes": sorted(list(expansion))},
        }

    data = parse_json_text(content_or_err)
    raw_rows = None
    if isinstance(data, dict):
        raw_rows = data.get("rows") or data.get("items") or data.get("checklist")
    rows: List[Dict[str, str]] = []
    if isinstance(raw_rows, list):
        for r in raw_rows[:40]:
            if not isinstance(r, dict):
                continue
            row = _normalize_row(r, default_screen=screen)
            if row["module"] and row["action"]:
                rows.append(row)

    if len(rows) < 6:
        rows = _heuristic_rows(screen, context, include_auth)
        if "admin" in (screen + ' ' + context).lower() or "cms" in (screen + ' ' + context).lower() or "관리" in (screen + ' ' + context):
            rows.extend([
                _normalize_row({"화면": screen, "구분": "권한", "action": "권한 없는 계정으로 발행/권한승격 시도", "expected": "접근 차단 및 권한 오류 노출", "actual": ""}, default_screen=screen),
                _normalize_row({"화면": screen, "구분": "기능", "action": "게시물 발행/비공개 전환을 수행", "expected": "사용자 화면 반영 상태가 일치", "actual": ""}, default_screen=screen),
                _normalize_row({"화면": screen, "구분": "운영", "action": "게시물 상태를 변경한다", "expected": "감사로그(변경 이력)가 기록", "actual": ""}, default_screen=screen),
            ])
        rows = _expand_rows(rows, expansion, raw_limit)
        return {
            "ok": True,
            "mode": "heuristic",
            "reason": "llm sparse fallback",
            "columns": COLUMNS,
            "rows": rows,
            "tsv": _rows_to_tsv(rows),
            "provider": used_provider,
            "model": used_model,
            "expansion": {"enabled": bool(expansion), "modes": sorted(list(expansion))},
        }

    rows = _expand_rows(rows, expansion, raw_limit)
    return {
        "ok": True,
        "mode": "llm",
        "reason": "",
        "columns": COLUMNS,
        "rows": rows,
        "tsv": _rows_to_tsv(rows),
        "provider": used_provider,
        "model": used_model,
        "expansion": {"enabled": bool(expansion), "modes": sorted(list(expansion))},
    }
