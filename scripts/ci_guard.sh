#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-quick}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "[ci-guard] missing .venv in $ROOT_DIR"
  echo "[ci-guard] create it first: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

run_cleanup_regression() {
  echo "[ci-guard] cleanup route regression"
  pytest -q tests/test_cleanup_and_route_role.py
}

run_quick_suite() {
  echo "[ci-guard] quick required tests"
  pytest -q \
    tests/test_density_and_finalize.py \
    tests/test_fix_sheet_autoroute.py \
    tests/test_interaction_linking.py
}

run_full_suite() {
  echo "[ci-guard] full required tests"
  pytest -q tests
}

case "$MODE" in
  quick)
    run_cleanup_regression
    run_quick_suite
    ;;
  full)
    run_cleanup_regression
    run_full_suite
    ;;
  *)
    echo "Usage: $0 [quick|full]"
    exit 2
    ;;
esac

echo "[ci-guard] PASS ($MODE)"
