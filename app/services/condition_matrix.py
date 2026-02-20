from __future__ import annotations

from typing import Any, Dict, List

CONDITIONS = ["정상", "예외", "권한", "회귀"]
ROLES = ["guest", "user", "editor", "admin"]


def _surface_from_screen(screen: str, context: str) -> str:
    s = f"{screen} {context}".lower()
    if any(k in s for k in ["admin", "cms", "관리"]):
        return "cms"
    if any(k in s for k in ["checkout", "결제", "order", "mypage", "프로필"]):
        return "user"
    return "public"


def _scenario(role: str, cond: str, screen: str, surface: str) -> str:
    base = f"[{surface}/{role}] {screen}"
    if cond == "정상":
        return f"{base} 핵심 경로 정상 동작 확인"
    if cond == "예외":
        return f"{base} 잘못된 입력/상태에서 오류 처리 확인"
    if cond == "권한":
        return f"{base} 권한 없는 접근/조작 차단 확인"
    return f"{base} 변경 후 기존 기능 회귀 여부 확인"


def build_condition_matrix(screen: str, context: str = "", include_auth: bool = True) -> Dict[str, Any]:
    surface = _surface_from_screen(screen, context)

    roles = ROLES.copy()
    if surface == "public":
        roles = ["guest", "user"]
    elif surface == "user":
        roles = ["guest", "user"]
    elif surface == "cms":
        roles = ["editor", "admin", "user"]

    rows: List[Dict[str, str]] = []
    for role in roles:
        for cond in CONDITIONS:
            if cond == "권한" and not include_auth:
                continue
            rows.append(
                {
                    "화면": screen,
                    "구분": cond,
                    "테스트시나리오": _scenario(role, cond, screen, surface),
                    "확인": "",
                }
            )

    # CMS 강화 항목
    if surface == "cms":
        rows.extend(
            [
                {"화면": screen, "구분": "권한", "테스트시나리오": "editor 계정은 발행/권한승격 제한 정책 준수 확인", "확인": ""},
                {"화면": screen, "구분": "회귀", "테스트시나리오": "관리자 변경사항이 사용자 화면에 의도대로 반영되는지 확인", "확인": ""},
                {"화면": screen, "구분": "예외", "테스트시나리오": "발행 실패/충돌 상황에서 롤백 또는 재시도 동작 확인", "확인": ""},
            ]
        )

    return {
        "ok": True,
        "screen": screen,
        "surface": surface,
        "roles": roles,
        "conditions": CONDITIONS,
        "rows": rows,
    }
