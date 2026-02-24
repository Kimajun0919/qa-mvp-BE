# Sheet Atomicity Transformation Rules (Strict)

## Goal
각 시트 행(row)은 **검증 포인트 1개**만 표현한다.

필수 슬롯(명시적):
- `field`
- `action`
- `assertion`
- `error`
- `evidence`

즉, 한 행 안에서 `field/action/assertion/error/evidence`가 모두 닫혀야 하며,
여러 행(FIELD/ACTION/ASSERTION)으로 분해해서 하나의 검증을 표현하지 않는다.

---

## Transformation Rule

### Before (legacy, one checklist row -> multiple decomposition rows)
```json
[
  {"kind":"FIELD","field":"/login","action":"detect-surface","assertion":{"expected":"surface exists","observed":"surface=3","pass":true,"failureCode":"OK"},"evidence":{...}},
  {"kind":"ACTION","field":"/login","action":"click-submit","assertion":{"expected":"submit executable","observed":"click-submit","pass":true,"failureCode":"OK"},"evidence":{...}},
  {"kind":"ASSERTION","field":"/login","action":"click-submit","assertion":{"expected":"error shown","observed":"not shown","pass":false,"failureCode":"ASSERT_TEXT_MISMATCH"},"evidence":{...}}
]
```

### After (strict, one checklist row -> one validation point row)
```json
[
  {
    "kind": "VALIDATION_POINT",
    "field": "/login",
    "action": "click-submit",
    "assertion": {
      "expected": "error shown",
      "observed": "not shown",
      "pass": false,
      "failureCode": "ASSERT_TEXT_MISMATCH"
    },
    "error": {
      "code": "ASSERT_TEXT_MISMATCH",
      "reason": "message missing"
    },
    "evidence": {
      "httpStatus": 200,
      "observedUrl": "https://example.com/login",
      "scenarioKind": "AUTH",
      "timestamp": 1700000001,
      "screenshotPath": "out/login.png"
    }
  }
]
```

---

## Compatibility
- Final sheet density parser는 strict `VALIDATION_POINT`를 우선 사용한다.
- 기존 분리형(FIELD/ACTION/ASSERTION) 입력은 fallback으로 계속 파싱한다.

## Patched Areas
- `app/services/execute_checklist.py`
  - `_atomic_decomposition_rows`를 strict single-row 생성으로 변경
- `app/services/final_output.py`
  - `_row_decomposition_refs`가 strict shape(`error.code` 포함)를 우선 해석
- `tests/test_density_and_finalize.py`
  - strict atomicity 단위 테스트 추가
