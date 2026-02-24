# QA Guard (BE)

Backend 로컬 푸시 전에 **필수 회귀 테스트**를 강제하기 위한 가드입니다.

## 목적
- 모든 push 경로에서 최소 회귀(quick) 보장
- 필요 시 전체 회귀(full) 실행
- cleanup route 관련 회귀를 quick/full 공통 필수로 고정

## 구성
- `scripts/ci_guard.sh`
  - `quick`: cleanup route 회귀 + 핵심 회귀 세트
  - `full`: cleanup route 회귀 + 전체 테스트(`tests/`)
- `.githooks/pre-push`
  - push 전에 `scripts/ci_guard.sh` 실행
  - 기본 모드: `quick`
- `scripts/setup_ci_guard_hooks.sh`
  - `git config core.hooksPath .githooks` 설정
- `scripts/guarded_push_main.sh`
  - 수동 우회 방지를 위한 권장 푸시 래퍼 (`guard -> push`)

## 1) 1회 설정
```bash
bash ./scripts/setup_ci_guard_hooks.sh
```

## 2) 수동 실행
```bash
# 빠른 필수 회귀
bash ./scripts/ci_guard.sh quick

# 전체 회귀
bash ./scripts/ci_guard.sh full
```

## 3) Push 경로
### A. 일반 push (권장 기본)
```bash
git push origin main
```
- pre-push hook에서 `quick` 모드 자동 실행

### B. full 강제 push
```bash
CI_GUARD_PUSH_MODE=full git push origin main
```
- pre-push hook에서 `full` 모드 실행

### C. 래퍼 사용
```bash
bash ./scripts/guarded_push_main.sh quick
bash ./scripts/guarded_push_main.sh full
```

## quick / full 상세
### quick (필수)
1. `tests/test_cleanup_and_route_role.py`
2. `tests/test_density_and_finalize.py`
3. `tests/test_fix_sheet_autoroute.py`
4. `tests/test_interaction_linking.py`

### full
1. `tests/test_cleanup_and_route_role.py`
2. `pytest -q tests`

## 참고
- 로컬 venv 기준: `.venv` + `requirements.txt`
- `PYTHONPATH`는 가드 스크립트에서 프로젝트 루트로 자동 설정
