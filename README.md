# qa-mvp-BE

Backend repo for QA MVP (FastAPI).

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Main endpoints
- `/api/analyze`
- `/api/checklist/auto`
- `/api/checklist/execute`
- `/api/flow/transition-check`
- `/api/report/finalize`

See `docs/API_SPEC.md`.

OAuth setup: `docs/OAUTH_SETUP.md`

## Backend full smoke
```bash
FASTAPI_BASE=http://127.0.0.1:8000 bash ./scripts/ops_split_check.sh
```
