# FastAPI Stability Evidence (2026-02-20)

## Scope
Immediate BE lane hardening for intermittent `empty reply/down` symptoms during ops checks.

## Root Cause Pattern Addressed
- Health endpoint depended on upstream node API with the full request timeout (`QA_API_TIMEOUT_SEC`, default 180s), which could make health checks appear down/hung under upstream issues.
- Several endpoints used raw `await req.json()` and could throw unstructured errors for invalid/empty bodies.
- Unhandled runtime exceptions were not normalized into stable JSON error responses.

## Patch Summary
- Added fast, isolated upstream timeout for health checks:
  - `QA_HEALTH_UPSTREAM_TIMEOUT_SEC` (default `2.5`)
- Changed `/health` behavior to always report FastAPI liveness (`ok: true`) while exposing upstream dependency state separately:
  - `upstreamOk` + `upstreamDetail`
- Added request JSON guard helper `_json_payload(req)`:
  - returns 400 with `{ok:false,error:"invalid JSON body"}` for bad payloads
- Added global middleware error normalization:
  - catches unexpected exceptions, logs, returns JSON 500 instead of unstable response behavior

## Local Verification
Server: `uvicorn app.main:app --host 127.0.0.1 --port 8010`

### 1) Health Loop
- 30 cycles, checking `/health` + `/`
- Result:

```json
{"health_fail": 0, "root_fail": 0}
```

### 2) Minimal Endpoint Smoke
- `POST /api/analyze` with `{"baseUrl":"https://example.com"}`
- `POST /api/flow-map` using returned `analysisId`
- Result:

```json
{"analyze_ok": true, "analysisId": "py_analysis_1771580628985", "pages": 1}
{"flow_ok": true, "links": 3}
```

## API Compatibility Notes
- No endpoint paths removed/renamed.
- Existing fields retained; `/health.ok` now reflects service liveness while upstream dependency state moved to explicit `upstreamOk`.
