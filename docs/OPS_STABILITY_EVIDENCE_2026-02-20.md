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

---

## Cycle9 BE Guardrails (Checklist expansion + parity signal consistency)

### Goal
- Add anti-regression guardrails for checklist expansion behavior (legacy flag compatibility)
- Keep `metrics.paritySignals` schema stable/consistent across targets
- Preserve backward compatibility (additive changes only)

### Code Changes
- `app/services/checklist.py`
  - `_resolve_expansion` guardrail:
    - `expand=true` + `expand_mode=none|off|false|0|""` now resolves to full expansion (`field,action,assertion`) for legacy callers
  - `_expand_rows` guardrail:
    - if expansion yields no rows unexpectedly, fallback to original rows (`rows[:max_rows]`) to prevent empty-result regression
- `app/services/analyze.py`
  - Added `_normalize_parity_signals()` to coerce parity fields into stable schema/types
  - `_collect_parity_signals()` now returns normalized shape
  - `_infer_candidate_flows()` now consumes normalized parity signals to avoid schema/type drift
- `scripts/smoke_candidate_parity.py`
  - Added parity schema assertions for all smoke targets
  - Added checklist expansion guardrail assertions:
    - legacy expansion (`expand=true` + `mode=none`) must expose full expansion modes
    - field-only expansion mode must stay exact (`["field"]`)
- `docs/API_SPEC.md`
  - Documented stable `metrics.paritySignals` schema explicitly
  - Documented backward-compatible expansion semantics for `checklistExpand=true` + `checklistExpandMode=none`
- `docs/OPS_AUTOMATION.md`
  - Updated parity smoke reference to `python scripts/smoke_candidate_parity.py`

### Verification Evidence

1) Compile
```bash
/tmp/qa-mvp-BE/.venv/bin/python -m compileall app scripts
```
Result: success

2) Guardrail smoke
```bash
QA_ANALYZE_DYNAMIC=0 QA_ANALYZE_MAX_PAGES=8 QA_ANALYZE_MAX_DEPTH=1 /tmp/qa-mvp-BE/.venv/bin/python scripts/smoke_candidate_parity.py
```
Result: success (exit 0)

3) Persisted smoke artifact
- `/tmp/cycle9_guardrails_smoke.json`
- includes:
  - per-target parity signals with stable keys
  - checklist guardrail summary with
    - `legacyExpansion.modes=["action","assertion","field"]`
    - `fieldExpansion.modes=["field"]`
