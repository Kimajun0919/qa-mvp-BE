from __future__ import annotations

from typing import Any, Dict, List


def _join(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = (path or "").strip()
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if not p.startswith("/"):
        p = "/" + p
    return b + p


TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "auth_login_basic",
        "name": "로그인 기본 플로우",
        "category": "AUTH",
        "steps": [
            {"name": "로그인 페이지 진입", "path": "/login", "expectUrlContains": "/login"},
            {"name": "로그인 후 랜딩 확인", "path": "/", "expectText": "로그아웃"},
        ],
    },
    {
        "key": "auth_signup_basic",
        "name": "회원가입 기본 플로우",
        "category": "AUTH",
        "steps": [
            {"name": "회원가입 진입", "path": "/join", "expectUrlContains": "/join"},
            {"name": "가입 폼 확인", "path": "/join", "expectText": "회원가입"},
        ],
    },
    {
        "key": "payment_entry_basic",
        "name": "결제 진입 플로우(안전)",
        "category": "PAYMENT",
        "steps": [
            {"name": "결제 진입 페이지", "path": "/payment", "expectUrlContains": "payment"},
            {"name": "결제 수단 영역 노출", "path": "/payment", "expectText": "결제"},
        ],
    },
    {
        "key": "reservation_apply_flow",
        "name": "예약 신청 진입 플로우",
        "category": "RESERVATION",
        "steps": [
            {"name": "예약 리스트", "path": "/devices", "expectText": "예약"},
            {"name": "예약 신청", "path": "/devices/application", "expectText": "신청"},
        ],
    },
    {
        "key": "mypage_status_flow",
        "name": "마이페이지 상태 플로우",
        "category": "MYPAGE",
        "steps": [
            {"name": "마이페이지 진입", "path": "/mypage", "expectUrlContains": "mypage"},
            {"name": "신청/결제 상태 확인", "path": "/mypage", "expectText": "상태"},
        ],
    },
    {
        "key": "admin_crud_board",
        "name": "관리자 게시판 CRUD",
        "category": "ADMIN_CRUD",
        "steps": [
            {"name": "관리자 게시판 목록", "path": "/boffice/actBoard/actBoardList.do", "expectText": "게시판"},
            {"name": "게시판 등록/수정 페이지", "path": "/boffice/actBoard/actBoardView.do", "expectText": "저장"},
        ],
    },
    {
        "key": "admin_crud_equipment",
        "name": "관리자 기기 CRUD",
        "category": "ADMIN_CRUD",
        "steps": [
            {"name": "기기 목록", "path": "/boffice/actEquipment/actEquipmentList.do", "expectText": "기기"},
            {"name": "기기 등록/수정", "path": "/boffice/actEquipment/actEquipmentView.do", "expectText": "저장"},
        ],
    },
    {
        "key": "admin_approval_flow",
        "name": "관리자 승인 상태전이",
        "category": "STATE_TRANSITION",
        "steps": [
            {"name": "신청/승인 목록", "path": "/boffice/actRsvt/actRsvtList.do", "expectText": "신청"},
            {"name": "결과등록 목록", "path": "/boffice/actRsvt/actAnalyResultList.do", "expectText": "결과"},
            {"name": "청구등록 목록", "path": "/boffice/actRsvt/actClaimList.do", "expectText": "청구"},
        ],
    },
    {
        "key": "search_filter_flow",
        "name": "검색/필터 플로우",
        "category": "SEARCH_FILTER",
        "steps": [
            {"name": "검색 대상 페이지", "path": "/notice/notice.do", "expectText": "검색"},
            {"name": "필터 적용 페이지", "path": "/devices/devices.do", "expectText": "필터"},
        ],
    },
    {
        "key": "file_upload_flow",
        "name": "파일 업로드 플로우",
        "category": "FILE_UPLOAD",
        "steps": [
            {"name": "업로드 화면", "path": "/boffice/actBoard/actBoardView.do", "expectText": "첨부"},
            {"name": "업로드 결과 확인", "path": "/boffice/actBoard/actBoardList.do", "expectText": "목록"},
        ],
    },
]


def list_templates() -> List[Dict[str, Any]]:
    return TEMPLATES


def build_template_steps(template_key: str, base_url: str) -> List[Dict[str, Any]]:
    key = (template_key or "").strip()
    for t in TEMPLATES:
        if t.get("key") != key:
            continue
        out = []
        for s in t.get("steps") or []:
            row = dict(s)
            row["url"] = _join(base_url, str(s.get("path") or ""))
            out.append(row)
        return out
    return []
