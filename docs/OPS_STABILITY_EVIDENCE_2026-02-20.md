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

---

## Cycle7 BE Hotfix (Analyze parity: httpbin/docs/example)

### Goal
- Reduce low-candidate failure tendency on sparse form targets (ex: `httpbin/forms/post`)
- Improve docs drift parity signaling while preserving API compatibility

### Code Changes
- `app/services/analyze.py`
  - Added `paritySignals` derivation (`docsDriftRisk`, docs/form counts, single-page-form tendency)
  - Enhanced heuristic candidate inference:
    - new form-aware candidates: `Form Submission Journey`, `Single-Page Form Probe`
    - docs-aware candidate: `Docs Reference Integrity`
  - Added minimum heuristic candidate floor (4) to avoid sparse-site under-generation
  - Kept existing response schema; only additive field inside `metrics`
- `scripts/smoke_candidate_parity.py`
  - Focused smoke targets updated to:
    - `https://httpbin.org/forms/post`
    - `https://docs.openclaw.ai`
    - `http://example.com`
  - Assertions updated for Cycle7 parity checks (candidate floor + form/docs signals)
- `docs/API_SPEC.md`
  - Documented optional `metrics.paritySignals` (additive/backward-compatible)

### Verification Evidence

1) Compile
```bash
python -m compileall app scripts
```
Result: success (no compile errors)

2) Focused smoke
```bash
QA_LLM_PROVIDER=openai python scripts/smoke_candidate_parity.py
```
Result highlights:
- `https://httpbin.org/forms/post`
  - `candidateCount=4`
  - includes `Form Submission Journey`, `Single-Page Form Probe`
  - `paritySignals.formSignalCount=1`
- `https://docs.openclaw.ai`
  - `candidateCount=6`
  - includes `Documentation Discovery`, `Docs Reference Integrity`
  - `paritySignals.docsDriftRisk=MEDIUM`
- `http://example.com`
  - `candidateCount=4`
  - stable generic floor candidates preserved
