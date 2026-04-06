#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [[ ! -x "${VENV_DIR}/bin/openakita" ]]; then
  echo "openakita executable not found at ${VENV_DIR}/bin/openakita" >&2
  echo "Create/setup the virtualenv first." >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "Warning: ${REPO_ROOT}/.env is missing." >&2
fi

if [[ ! -f "${REPO_ROOT}/data/llm_endpoints.json" ]]; then
  echo "Warning: ${REPO_ROOT}/data/llm_endpoints.json is missing." >&2
fi

export API_HOST="${API_HOST:-127.0.0.1}"
export API_PORT="${API_PORT:-18901}"

cd "${REPO_ROOT}"
echo "Starting OpenAkita from ${REPO_ROOT}"
echo "API: http://${API_HOST}:${API_PORT}"
exec "${VENV_DIR}/bin/openakita" serve
