#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/apps/setup-center"

if [[ ! -d "${APP_DIR}/node_modules" ]]; then
  echo "node_modules not found at ${APP_DIR}/node_modules" >&2
  echo "Run 'cd ${APP_DIR} && npm install' first." >&2
  exit 1
fi

BACKEND_HOST="${OPENAKITA_API_HOST:-127.0.0.1}"
BACKEND_PORT="${OPENAKITA_API_PORT:-${API_PORT:-18901}}"
PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://${BACKEND_HOST}:${BACKEND_PORT}}"

cd "${APP_DIR}"
echo "Starting OpenAkita web UI from ${APP_DIR}"
echo "Web UI: http://127.0.0.1:5173/web/#/chat"
echo "API proxy: ${PROXY_TARGET}"
exec env VITE_API_PROXY_TARGET="${PROXY_TARGET}" npm run dev:web
