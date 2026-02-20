import os
import time
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.services.analyze import analyze_site
from app.services.checklist import generate_checklist
from app.services.condition_matrix import build_condition_matrix
from app.services.flow_map import build_flow_map
from app.services.flows import finalize_flows, run_flows
from app.services.page_audit import auto_checklist_from_sitemap
from app.services.final_output import write_final_testsheet
from app.services.execute_checklist import execute_checklist_rows
from app.services.storage import get_bundle, migrate, save_analysis, save_flows
from app.services.structure_map import build_structure_map
from app.services.state_transition import run_transition_check
from app.services.qa_templates import build_template_steps, list_templates

APP_NAME = "qa-mvp-fastapi"
NODE_API_BASE = os.getenv("QA_NODE_API_BASE", "http://127.0.0.1:4173").rstrip("/")
WEB_ORIGIN = os.getenv("QA_WEB_ORIGIN", "*").strip() or "*"
REQUEST_TIMEOUT_SEC = float(os.getenv("QA_API_TIMEOUT_SEC", "180"))

app = FastAPI(title=APP_NAME, version="0.1.0")

native_analysis_store: Dict[str, Dict[str, Any]] = {}
Path("out").mkdir(parents=True, exist_ok=True)
app.mount("/out", StaticFiles(directory="out"), name="out")


@app.on_event("startup")
def _startup() -> None:
    migrate()

allow_origins = ["*"] if WEB_ORIGIN == "*" else [WEB_ORIGIN]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _save_native_bundle(analysis_id: str, base_url: str, pages: list[dict[str, Any]], elements: list[dict[str, Any]], candidates: list[dict[str, Any]], reports: Dict[str, Any] | None = None, auth: Dict[str, Any] | None = None) -> None:
    bundle = {
        "analysis": {"analysisId": analysis_id, "baseUrl": base_url},
        "pages": pages,
        "elements": elements,
        "candidates": candidates,
        "reports": reports or {},
        "auth": auth or {},
        "createdAt": int(time.time()),
    }
    native_analysis_store[analysis_id] = bundle
    save_analysis(analysis_id, base_url, pages, elements, candidates)


def _load_bundle(analysis_id: str) -> Dict[str, Any] | None:
    if analysis_id in native_analysis_store:
        return native_analysis_store[analysis_id]
    db = get_bundle(analysis_id)
    if db:
        native_analysis_store[analysis_id] = db
    return db


async def proxy_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{NODE_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
            resp = await client.post(url, json=payload)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"upstream unavailable: {e}") from e

    if resp.status_code >= 400:
        detail: Any
        try:
            detail = resp.json()
        except Exception:
            detail = {"error": resp.text}
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


async def proxy_get(path: str) -> Dict[str, Any]:
    url = f"{NODE_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"upstream unavailable: {e}") from e

    if resp.status_code >= 400:
        detail: Any
        try:
            detail = resp.json()
        except Exception:
            detail = {"error": resp.text}
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "text": resp.text[:500]}


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "nodeApiBase": NODE_API_BASE,
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    upstream_ok = False
    upstream_detail: Any = None
    try:
        upstream_detail = await proxy_get("/")
        upstream_ok = True
    except HTTPException as e:
        upstream_detail = e.detail

    return {
        "ok": upstream_ok,
        "service": APP_NAME,
        "upstream": NODE_API_BASE,
        "upstreamDetail": upstream_detail,
    }


@app.post("/api/analyze")
async def analyze(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    base_url = str(payload.get("baseUrl", "")).strip()
    if not base_url:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "baseUrl required"})

    # Native FastAPI implementation (phase-2 migration target)
    provider = payload.get("llmProvider")
    model = (str(payload.get("llmModel", "")).strip() or None)
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    try:
        result = await analyze_site(base_url, provider=provider, model=model)
        analysis_id = str(result.get("analysisId") or f"py_analysis_{int(time.time() * 1000)}")
        native_pages = result.get("_native", {}).get("pages") or [result.get("_native", {}).get("page", {})]
        _save_native_bundle(
            analysis_id,
            base_url,
            native_pages,
            [],
            result.get("candidates", []),
            reports=result.get("reports", {}),
            auth=auth,
        )
        result["analysisId"] = analysis_id
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)}) from e


@app.get("/api/analysis/{analysis_id}")
async def analysis_get(analysis_id: str) -> Dict[str, Any]:
    bundle = _load_bundle(analysis_id)
    if bundle:
        return {
            "ok": True,
            "storage": "fastapi-sqlite",
            "analysis": bundle.get("analysis"),
            "pages": bundle.get("pages", []),
            "elements": bundle.get("elements", []),
            "candidates": bundle.get("candidates", []),
        }
    return await proxy_get(f"/api/analysis/{analysis_id}")


@app.post("/api/flow-map")
async def flow_map(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    analysis_id = str(payload.get("analysisId", "")).strip()
    if not analysis_id:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "analysisId required"})

    bundle = _load_bundle(analysis_id)
    if not bundle:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "analysis not found"})

    screen = str(payload.get("screen", "")).strip()
    context = str(payload.get("context", "")).strip()
    return build_flow_map(bundle, screen=screen, context=context)


@app.post("/api/structure-map")
async def structure_map(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    analysis_id = str(payload.get("analysisId", "")).strip()
    if not analysis_id:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "analysisId required"})

    bundle = _load_bundle(analysis_id)
    if not bundle:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "analysis not found"})

    flowmap = build_flow_map(bundle, screen=str(payload.get("screen", "")).strip(), context=str(payload.get("context", "")).strip())
    return build_structure_map(bundle, flowmap)


@app.post("/api/condition-matrix")
async def condition_matrix(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    screen = str(payload.get("screen", "")).strip()
    if not screen:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "screen required"})

    context = str(payload.get("context", "")).strip()
    include_auth = bool(payload.get("includeAuth", True))
    return build_condition_matrix(screen, context=context, include_auth=include_auth)


@app.post("/api/checklist")
async def checklist(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    screen = str(payload.get("screen", "")).strip()
    if not screen:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "screen required"})

    context = str(payload.get("context", "")).strip()
    include_auth = bool(payload.get("includeAuth", False))
    provider = payload.get("llmProvider")
    model = (str(payload.get("llmModel", "")).strip() or None)

    # Native FastAPI implementation + condition matrix expansion
    out = await generate_checklist(
        screen,
        context,
        include_auth,
        provider=provider,
        model=model,
    )
    matrix = build_condition_matrix(screen, context=context, include_auth=include_auth)

    # merge/dedup by 시나리오 text
    merged = []
    seen = set()
    for r in (out.get("rows") or []) + (matrix.get("rows") or []):
        k = str(r.get("테스트시나리오") or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        merged.append(r)

    out["rows"] = merged[:40]
    out["tsv"] = "\n".join([
        "\t".join(out.get("columns") or ["화면", "구분", "테스트시나리오", "확인"]),
        *["\t".join(str(x.get(c, "")) for c in (out.get("columns") or ["화면", "구분", "테스트시나리오", "확인"])) for x in out["rows"]],
    ])
    out["conditionMatrix"] = {
        "surface": matrix.get("surface"),
        "roles": matrix.get("roles"),
        "conditions": matrix.get("conditions"),
        "count": len(matrix.get("rows") or []),
    }
    return out


@app.post("/api/checklist/execute")
async def checklist_execute(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "rows required"})
    max_rows = int(payload.get("maxRows", 20) or 20)
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    exhaustive = bool(payload.get("exhaustive", False))
    exhaustive_clicks = int(payload.get("exhaustiveClicks", 12) or 12)
    exhaustive_inputs = int(payload.get("exhaustiveInputs", 12) or 12)
    exhaustive_depth = int(payload.get("exhaustiveDepth", 1) or 1)
    exhaustive_budget_ms = int(payload.get("exhaustiveBudgetMs", 20000) or 20000)
    allow_risky_actions = bool(payload.get("allowRiskyActions", False))

    result = await execute_checklist_rows(
        rows,
        max_rows=max_rows,
        auth=auth,
        exhaustive=exhaustive,
        exhaustive_clicks=exhaustive_clicks,
        exhaustive_inputs=exhaustive_inputs,
        exhaustive_depth=exhaustive_depth,
        exhaustive_budget_ms=exhaustive_budget_ms,
        allow_risky_actions=allow_risky_actions,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail={"ok": False, "error": result.get("error")})

    run_id = str(payload.get("runId", "")).strip() or f"exec_{int(time.time()*1000)}"
    project_name = str(payload.get("projectName", "QA 테스트시트")).strip()
    final_sheet = write_final_testsheet(run_id, project_name, result.get("rows") or [])
    return {"ok": True, "summary": result.get("summary"), "coverage": result.get("coverage"), "loginUsed": result.get("loginUsed", False), "rows": result.get("rows"), "finalSheet": final_sheet}


@app.get("/api/qa/templates")
async def qa_templates() -> Dict[str, Any]:
    return {"ok": True, "templates": list_templates()}


@app.post("/api/flow/transition-check")
async def flow_transition_check(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    steps = payload.get("steps") or []
    template_key = str(payload.get("templateKey") or "").strip()
    base_url = str(payload.get("baseUrl") or "").strip()
    if template_key:
        steps = build_template_steps(template_key, base_url)

    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "steps required (or invalid templateKey/baseUrl)"})
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}

    out = await run_transition_check(steps, auth=auth)
    if not out.get("ok"):
        raise HTTPException(status_code=500, detail={"ok": False, "error": out.get("error")})
    return out


@app.post("/api/report/finalize")
async def report_finalize(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    run_id = str(payload.get("runId", "")).strip() or f"run_{int(time.time()*1000)}"
    project_name = str(payload.get("projectName", "QA 테스트시트")).strip()
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "items required"})

    paths = write_final_testsheet(run_id, project_name, items)
    return {"ok": True, "runId": run_id, "projectName": project_name, "finalSheet": paths}


@app.post("/api/checklist/auto")
async def checklist_auto(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    analysis_id = str(payload.get("analysisId", "")).strip()
    if not analysis_id:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "analysisId required"})

    bundle = _load_bundle(analysis_id)
    if not bundle:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "analysis not found"})

    provider = payload.get("llmProvider")
    model = (str(payload.get("llmModel", "")).strip() or None)
    include_auth = bool(payload.get("includeAuth", True))
    max_pages_raw = payload.get("maxPages", None)
    max_pages = int(max_pages_raw) if str(max_pages_raw or "").strip() else None
    source = str(payload.get("source", "sitemap")).strip().lower() or "sitemap"
    auth_payload = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    auth_bundle = bundle.get("auth") if isinstance(bundle.get("auth"), dict) else {}
    auth = {**auth_bundle, **auth_payload}

    out = await auto_checklist_from_sitemap(
        bundle,
        provider=provider,
        model=model,
        include_auth=include_auth,
        max_pages=max_pages,
        source=source,
        auth=auth,
    )
    try:
        run_id = f"auto_{analysis_id}_{int(time.time())}"
        out["finalSheet"] = write_final_testsheet(
            run_id,
            str(payload.get("projectName") or "QA 테스트시트"),
            out.get("rows") or [],
        )
    except Exception:
        pass
    return out


@app.post("/api/oneclick")
async def oneclick(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    base_url = str(payload.get("baseUrl", "")).strip()
    if not base_url:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "baseUrl required"})

    provider = payload.get("llmProvider")
    model = (str(payload.get("llmModel", "")).strip() or None)
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}

    # 1) analyze
    analyzed = await analyze_site(base_url, provider=provider, model=model)
    analysis_id = str(analyzed.get("analysisId") or f"py_analysis_{int(time.time() * 1000)}")
    native_pages = analyzed.get("_native", {}).get("pages") or [analyzed.get("_native", {}).get("page", {})]
    _save_native_bundle(
        analysis_id,
        base_url,
        native_pages,
        [],
        analyzed.get("candidates", []),
        reports=analyzed.get("reports", {}),
        auth=auth,
    )

    # 2) auto finalize flows from candidates
    candidates = analyzed.get("candidates", [])
    auto_flows = []
    for c in candidates[:3]:
        auto_flows.append(
            {
                "name": str(c.get("name") or "Auto Flow"),
                "loginMode": "OPTIONAL" if analyzed.get("authLikely") else "OFF",
                "steps": [
                    {"action": "NAVIGATE", "targetUrl": "/"},
                    {"action": "ASSERT_URL", "targetUrl": urlparse(base_url).hostname or "/"},
                ],
            }
        )

    if not auto_flows:
        auto_flows = [
            {
                "name": "Smoke",
                "loginMode": "OFF",
                "steps": [
                    {"action": "NAVIGATE", "targetUrl": "/"},
                    {"action": "ASSERT_URL", "targetUrl": urlparse(base_url).hostname or "/"},
                ],
            }
        ]

    finalized = finalize_flows(native_analysis_store, analysis_id, auto_flows)
    if not finalized.get("ok"):
        raise HTTPException(status_code=500, detail={"ok": False, "error": finalized.get("error") or "finalize failed"})
    save_flows(analysis_id, auto_flows)

    # 3) run
    ran = await run_flows(native_analysis_store, analysis_id, provider=provider, model=model)
    if not ran.get("ok"):
        code = int(ran.get("status") or 500)
        raise HTTPException(status_code=code, detail={"ok": False, "error": ran.get("error")})

    return {
        "ok": True,
        "oneClick": True,
        "analysisId": analysis_id,
        "runId": ran.get("runId"),
        "finalStatus": ran.get("finalStatus"),
        "summary": ran.get("summary"),
        "judge": ran.get("judge"),
        "reportPath": ran.get("reportPath", ""),
        "reportJson": ran.get("reportJson", ""),
        "fixSheet": ran.get("fixSheet"),
        "discovered": {
            "pages": analyzed.get("pages"),
            "elements": analyzed.get("elements"),
            "serviceType": analyzed.get("serviceType"),
            "authLikely": analyzed.get("authLikely"),
            "metrics": analyzed.get("metrics"),
        },
        "plannerMode": analyzed.get("plannerMode"),
        "plannerReason": analyzed.get("plannerReason"),
        "analysisReports": analyzed.get("reports", {}),
    }


@app.post("/api/flows/finalize")
async def flows_finalize(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    analysis_id = str(payload.get("analysisId", "")).strip()
    flows = payload.get("flows") or []
    if not analysis_id:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "analysisId required"})
    if not isinstance(flows, list) or len(flows) == 0:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "flows required"})

    _load_bundle(analysis_id)
    r = finalize_flows(native_analysis_store, analysis_id, flows)
    if not r.get("ok"):
        code = int(r.get("status") or 400)
        raise HTTPException(status_code=code, detail={"ok": False, "error": r.get("error")})
    save_flows(analysis_id, flows)
    return r


@app.post("/api/flows/run")
async def flows_run(req: Request) -> Dict[str, Any]:
    payload = await req.json()
    analysis_id = str(payload.get("analysisId", "")).strip()
    if not analysis_id:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "analysisId required"})

    provider = payload.get("llmProvider")
    model = (str(payload.get("llmModel", "")).strip() or None)
    _load_bundle(analysis_id)
    r = await run_flows(native_analysis_store, analysis_id, provider=provider, model=model)
    if not r.get("ok"):
        code = int(r.get("status") or 400)
        raise HTTPException(status_code=code, detail={"ok": False, "error": r.get("error")})
    return r
