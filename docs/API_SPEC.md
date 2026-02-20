# QA MVP API Specification (v1)

Base URL
- Node backend (local): `http://127.0.0.1:4173`
- FastAPI backend (local): `http://127.0.0.1:8000`

Content-Type
- Request: `application/json`
- Response: `application/json`

LLM options (common)
- `llmProvider`: `"openai" | "ollama"` (optional)
- `llmModel`: string (optional)

---

## Health / Root

### GET `/`
Service root info.

Example response:
```json
{
  "ok": true,
  "service": "qa-mvp-fastapi",
  "nodeApiBase": "http://127.0.0.1:4173"
}
```

### GET `/health` (FastAPI)
Health of FastAPI + upstream visibility.

Example response:
```json
{
  "ok": true,
  "service": "qa-mvp-fastapi",
  "upstream": "http://127.0.0.1:4173",
  "upstreamDetail": {"status": 200}
}
```

---

## 1) Analyze

### POST `/api/analyze`
Analyze target site and generate candidate flows.

Request body:
```json
{
  "baseUrl": "https://example.com",
  "llmProvider": "ollama",
  "llmModel": "qwen2.5:0.5b"
}
```

Required fields
- `baseUrl`

Response fields
- `ok`: boolean
- `analysisId`: string
- `pages`: number
- `elements`: number
- `serviceType`: string
- `authLikely`: boolean
- `limits`: object
- `plannerMode`: `"llm" | "heuristic"`
- `plannerReason`: string
- `metrics`: object
- `reports`: object (`sitemapPath`, `menuPath`, `qualityPath`)
- `advisories`: array (robots/auth/limited-crawl 안내)
- `robots`: object (`blockAll`, `hasRules`)
- `candidates`: array of candidate flow objects

Candidate object:
```json
{
  "id": "cand_xxx",
  "name": "User-Flow Navigation",
  "platformType": "LANDING",
  "confidence": 0.7,
  "status": "PROPOSED"
}
```

Errors
- `400`: `baseUrl required`
- `500`: analysis failure

---

## 2) Analysis Bundle

### GET `/api/analysis/:analysisId`
Return analysis bundle for a previous analyze call.

Response fields
- `ok`: boolean
- `storage`: `sqlite | memory | fastapi-sqlite | fastapi-memory`
- `analysis`: object
- `pages`: array
- `elements`: array
- `candidates`: array

Errors
- `404`: analysis not found

---

## 3) Structure Map (Tree + Role Graph + Entity Links)

### POST `/api/structure-map`
Build integrated structure map from analysis.

Request body:
```json
{
  "analysisId": "analysis_...",
  "screen": "CMS 게시물 발행",
  "context": "관리자-사용자 영향 검증"
}
```

Required fields
- `analysisId`

Response fields
- `ok`: boolean
- `analysisId`: string
- `pathTree`: object (URL path tree)
- `roleGraph`: array (`role`, `paths`, `to`)
- `entityLinks`: array (same as flow-map links)
- `stats`: object

Errors
- `400`: `analysisId required`
- `404`: analysis not found

---

## 4) Flow Map (Analyze ↔ Checklist bridge)

### POST `/api/flow-map`
Build admin↔user linkage map from analysis bundle.

Request body:
```json
{
  "analysisId": "analysis_...",
  "screen": "CMS 게시물 발행",
  "context": "관리자 변경이 사용자 노출에 미치는 영향 확인"
}
```

Required fields
- `analysisId`

Response fields
- `ok`: boolean
- `analysisId`: string
- `siteProfile`: string
- `totalLinks`: number
- `avgScore`: number
- `links`: array of linkage objects

Link object:
```json
{
  "entity": "CONTENT|PRODUCT|BANNER|CATEGORY|USER_ROLE|CONTEXT|CANDIDATE",
  "adminAction": "...",
  "userImpact": "...",
  "verificationPath": ["/admin", "/content"],
  "priority": "P1|P2|P3",
  "reason": "...",
  "evidencePath": "rule/source",
  "score": 0.0,
  "riskLevel": "LOW|MEDIUM|HIGH"
}
```

Errors
- `400`: `analysisId required`
- `404`: analysis not found

---

## 5) Condition Matrix (Role × Condition)

### POST `/api/condition-matrix`
Generate condition matrix rows by role and condition set.

Request body:
```json
{
  "screen": "CMS 관리자 게시물 발행",
  "context": "관리자-사용자 영향 검증",
  "includeAuth": true
}
```

Required fields
- `screen`

Response fields
- `ok`: boolean
- `screen`: string
- `surface`: `public|user|cms`
- `roles`: array
- `conditions`: array (`정상, 예외, 권한, 회귀`)
- `rows`: checklist-like rows

Errors
- `400`: `screen required`

---

## 6) Checklist

### POST `/api/checklist`
Generate QA checklist rows and TSV.

Request body:
```json
{
  "screen": "로그인 화면",
  "context": "E2E smoke",
  "includeAuth": true,
  "llmProvider": "ollama",
  "llmModel": "qwen2.5:0.5b"
}
```

Required fields
- `screen`

Response fields
- `ok`: boolean
- `mode`: `"llm" | "heuristic"`
- `reason`: string
- `columns`: fixed array: `["화면","구분","테스트시나리오","확인"]`
- `rows`: array
- `tsv`: string
- `conditionMatrix`: object (`surface`, `roles`, `conditions`, `count`)

Row schema:
```json
{
  "화면": "로그인 화면",
  "구분": "기능",
  "테스트시나리오": "유효한 계정 로그인 성공 확인",
  "확인": ""
}
```

Errors
- `400`: `screen required`

### POST `/api/checklist/auto`
Sitemap 기반 자동 체크리스트 파이프라인.
(Analyze 결과 페이지별 URL 확인 → 스크린샷 캡처 → 시각 컨텍스트 포함 체크리스트 생성)

Request body:
```json
{
  "analysisId": "py_analysis_...",
  "includeAuth": true,
  "source": "sitemap",
  "maxPages": 20,
  "auth": {
    "loginUrl": "https://example.com/login",
    "userId": "tester@example.com",
    "password": "********"
  },
  "llmProvider": "ollama",
  "llmModel": "qwen2.5:0.5b"
}
```

Required fields
- `analysisId`

Notes
- `source`: `sitemap|menu` (기본 `sitemap`)
- `auth`: 로그인 입력값 (`loginUrl`, `userId`, `password`)
- `maxPages` 생략 시 선택된 source의 전체 URL 대상으로 실행
- 안전 상한: `QA_AUTO_MAX_PAGES` (기본 30)

Response fields
- `ok`: boolean
- `analysisId`: string
- `baseUrl`: string
- `pagesAudited`: number
- `screenshotOk`: number
- `screenshotFailed`: number
- `authProvided`: boolean
- `columns`: fixed array
- `rows`: merged checklist rows
- `tsv`: merged TSV
- `pageResults`: per-page audit result (`path`,`url`,`title`,`screenshot`,`rows`)
- `finalSheet`: object (`csv`,`xlsx`) 최종 산출물 경로
- `note`: pipeline description

Errors
- `400`: `analysisId required`
- `404`: `analysis not found`

### POST `/api/checklist/execute`
체크리스트 항목 실제 수행(Playwright) + 실행결과 기반 최종 시트 생성.

Request body:
```json
{
  "runId": "exec_20260220",
  "projectName": "한양대학교 테스트시트(HK)",
  "maxRows": 20,
  "exhaustive": true,
  "exhaustiveClicks": 12,
  "exhaustiveInputs": 12,
  "exhaustiveDepth": 1,
  "exhaustiveBudgetMs": 20000,
  "allowRiskyActions": false,
  "auth": {"loginUrl":"https://example.com/login","userId":"tester","password":"***"},
  "rows": [
    {"화면":"https://example.com/login","구분":"권한","테스트시나리오":"비로그인 접근 차단 확인","확인":""}
  ]
}
```

Response fields
- `ok`: boolean
- `summary`: object (`PASS`,`FAIL`,`BLOCKED`)
- `coverage`: object (`totalsObserved`,`coveredSignals`,`untestedEstimate`,`rowCoverage`,`exhaustive`)
  - `coverage.exhaustive.allowRiskyActions`: 위험 액션 클릭 허용 여부
  - `coverage.exhaustive.fuzzProfile`: 적용된 폼 퍼징 프로필명
- `loginUsed`: boolean
- `rows`: executed rows (`실행결과`,`증거`,`실패사유`,`실행메타`,`요소통계` 포함)
  - `실행메타.scenarioKind`: `AUTH|VALIDATION|INTERACTION|RESPONSIVE|PUBLISHING|SMOKE`
- `finalSheet`: object (`csv`,`xlsx`)

### GET `/api/qa/templates`
QA 참고 플로우 템플릿 목록 조회.

Response fields
- `ok`: boolean
- `templates`: array (`key`,`name`,`category`,`steps`)

### POST `/api/flow/transition-check`
상태전이(예: 로그인→신청→승인→결제) 단계별 검증.

Request body:
```json
{
  "auth": {"loginUrl":"https://example.com/login","userId":"tester","password":"***"},
  "steps": [
    {"name":"로그인","url":"https://example.com/login","expectText":"로그인"},
    {"name":"신청페이지","url":"https://example.com/apply","expectUrlContains":"/apply"}
  ]
}
```

또는 템플릿 기반:
```json
{
  "templateKey": "admin_approval_flow",
  "baseUrl": "https://korea-university.hk-test.co.kr",
  "auth": {"loginUrl":"https://.../login","userId":"...","password":"..."}
}
```

Response fields
- `ok`: boolean
- `summary`: object (`PASS`,`FAIL`,`BLOCKED`)
- `steps`: array (`name`,`status`,`reason`,`observed`)

### POST `/api/report/finalize`
최종 테스트시트 산출물(csv/xlsx) 생성.

Request body:
```json
{
  "runId": "run_20260220",
  "projectName": "한양대학교 테스트시트(HK)",
  "items": [
    {"경로":"/front/main.do","우선순위":"P2","상세":"로그인 후 이동 오류","진행사항":"수정 필요"}
  ]
}
```

Response fields
- `ok`: boolean
- `runId`: string
- `projectName`: string
- `finalSheet`: object (`csv`, `xlsx`)

---

## 4) Finalize Flows

### POST `/api/flows/finalize`
Persist finalized flows for an analysis.

Request body:
```json
{
  "analysisId": "analysis_...",
  "flows": [
    {
      "name": "Smoke",
      "loginMode": "OFF",
      "steps": [
        {"action": "NAVIGATE", "targetUrl": "/"},
        {"action": "ASSERT_URL", "targetUrl": "/"}
      ]
    }
  ]
}
```

Required fields
- `analysisId`
- `flows` (non-empty array)

Response fields
- `ok`: boolean
- `saved`: number
- `storage`: string

Errors
- `400`: `analysisId required` / `flows required`
- `404`: analysis not found

---

## 5) Run Finalized Flows

### POST `/api/flows/run`
Run finalized flows and return summary/judge.

Request body:
```json
{
  "analysisId": "analysis_...",
  "llmProvider": "ollama",
  "llmModel": "qwen2.5:0.5b"
}
```

Required fields
- `analysisId`

Response fields
- `ok`: boolean
- `runId`: string
- `finalStatus`: `"PASS" | "PASS_WITH_WARNINGS" | "FAIL"`
- `summary`: object (`PASS`, `WARNING`, `FAIL`, `BLOCKED`, `ERROR`, `FINAL`)
- `flowSummary`: array
- `judge`: object
- `reportPath`: string
- `reportJson`: string
- `fixSheet`: object (`csv`, `xlsx`)

Errors
- `400`: `analysisId required` / `no finalized flows`
- `404`: analysis not found
- `500`: run failure

---

## 6) One-click Pipeline

### POST `/api/oneclick`
Analyze → auto finalize → run in a single call.

Request body:
```json
{
  "baseUrl": "https://example.com",
  "llmProvider": "ollama",
  "llmModel": "qwen2.5:0.5b"
}
```

Required fields
- `baseUrl`

Response fields
- `ok`: boolean
- `oneClick`: true
- `analysisId`: string
- `runId`: string
- `finalStatus`: string
- `summary`: object
- `judge`: object
- `reportPath`: string
- `reportJson`: string
- `fixSheet`: object (`csv`, `xlsx`)
- `discovered`: object
- `plannerMode`: string
- `plannerReason`: string
- `analysisReports`: object

Errors
- `400`: `baseUrl required`
- `500`: oneclick failure

---

## 7) Legacy Quick Run (Node only)

### POST `/api/run`
Legacy quick QA run endpoint.

Response includes:
- `ok`, `runId`, `results`, `reportPath`

---

## Flow Step Actions

Common step actions used by runner:
- `NAVIGATE` (`targetUrl`)
- `ASSERT_URL` (`targetUrl`)
- `CLICK` (`selector`)
- `TYPE` (`selector`, `value`)
- `ASSERT_VISIBLE` (`selector`)
- `WAIT` (`value` in ms)

Note
- FastAPI native runner supports Playwright mode + light fallback.

---

## CORS

FastAPI CORS is controlled by:
- `QA_WEB_ORIGIN`

Examples:
- Development: `*`
- Production: `https://qa-test-cyr.pages.dev`

---

## Standard Error Shape

Typical error response:
```json
{
  "ok": false,
  "error": "message"
}
```

FastAPI may return:
```json
{
  "detail": {
    "ok": false,
    "error": "message"
  }
}
```
