#!/usr/bin/env bash
set -euo pipefail

FASTAPI_BASE="${FASTAPI_BASE:-http://127.0.0.1:8000}"
TARGET_URL="${TARGET_URL:-https://docs.openclaw.ai}"

echo "[be-check] health"
curl -fsS "$FASTAPI_BASE/health" | jq '{ok,service}'

echo "[be-check] api smoke"
python3 - <<PY
import json, urllib.request
BASE='${FASTAPI_BASE}'
TARGET='${TARGET_URL}'

def post(path,obj,timeout=300):
    data=json.dumps(obj).encode()
    req=urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))

def get(path,timeout=60):
    with urllib.request.urlopen(BASE+path, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))

an=post('/api/analyze',{'baseUrl':TARGET,'llmProvider':'ollama','llmModel':'qwen2.5:0.5b'},timeout=180)
aid=an.get('analysisId')
assert an.get('ok') and aid, 'analyze failed'

assert post('/api/flow-map',{'analysisId':aid,'screen':'메인','context':'스모크'}).get('ok')
assert post('/api/structure-map',{'analysisId':aid}).get('ok')
assert post('/api/condition-matrix',{'screen':'메인','context':'기본'}).get('ok')
assert post('/api/checklist',{'screen':'메인','context':'기본','llmProvider':'ollama','llmModel':'qwen2.5:0.5b'}).get('ok')
assert post('/api/checklist/auto',{'analysisId':aid,'source':'sitemap','maxPages':3,'llmProvider':'ollama','llmModel':'qwen2.5:0.5b'},timeout=420).get('ok')
assert post('/api/checklist/execute',{'projectName':'be-check','rows':[{'화면':TARGET+'/','구분':'기본','테스트시나리오':'렌더'}],'maxRows':1,'exhaustive':False},timeout=420).get('ok')
assert get('/api/qa/templates').get('ok')
assert post('/api/flow/transition-check',{'templateKey':'search_filter_flow','baseUrl':TARGET},timeout=180).get('ok')
assert post('/api/report/finalize',{'projectName':'be-check','items':[{'화면':'/','구분':'기본','테스트시나리오':'렌더','실행결과':'PASS'}]}).get('ok')
assert post('/api/oneclick',{'baseUrl':TARGET,'llmProvider':'ollama','llmModel':'qwen2.5:0.5b'},timeout=600).get('ok')
assert post('/api/oneclick',{'dualContext':{'userBaseUrl':TARGET,'adminBaseUrl':TARGET,'autoUserSignup':True,'adminAuth':{'loginUrl':'','userId':'','password':''}},'llmProvider':'ollama','llmModel':'qwen2.5:0.5b'},timeout=900).get('ok')
print('[be-check] ALL PASS')
PY