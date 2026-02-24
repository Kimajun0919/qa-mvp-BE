#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

git config core.hooksPath .githooks
echo "[ci-guard] git hooks path configured: $(git config --get core.hooksPath)"
echo "[ci-guard] pre-push hook will run scripts/ci_guard.sh \${CI_GUARD_PUSH_MODE:-quick}"
