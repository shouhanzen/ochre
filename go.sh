#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"

wait_for_backend() {
  local url="http://127.0.0.1:${BACKEND_PORT}/api/health"
  echo "Waiting for backend readiness: ${url}"
  # curl retries without sleeping by default when retry-delay=0; this avoids "guessing" timing.
  if ! curl -fsS --max-time 0.25 --retry 200 --retry-all-errors --retry-delay 0 --retry-max-time 20 "${url}" >/dev/null; then
    echo "ERROR: backend did not become ready in time at ${url}" >&2
    return 1
  fi
  echo "Backend ready."
}

kill_port() {
  local port="$1"
  local pids=""

  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    # fuser prints to stderr; parse PIDs from output
    pids="$(fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true)"
  elif command -v ss >/dev/null 2>&1; then
    # ss output example: users:(("node",pid=123,fd=20))
    pids="$(ss -H -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u || true)"
  else
    echo "WARN: can't free port $port (need lsof/fuser/ss)" >&2
    return 0
  fi

  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Freeing port ${port} (pids: ${pids})"
  kill -TERM ${pids} 2>/dev/null || true

  local tries=20
  while (( tries > 0 )); do
    sleep 0.1
    local alive=""
    for pid in ${pids}; do
      if kill -0 "$pid" 2>/dev/null; then
        alive+=" $pid"
      fi
    done
    if [[ -z "${alive}" ]]; then
      return 0
    fi
    tries=$((tries - 1))
  done

  echo "Force killing lingering pids on port ${port}: ${pids}"
  kill -KILL ${pids} 2>/dev/null || true
}

echo "Ochre dev runner"
echo "- root: ${ROOT}"
echo "- backend port: ${BACKEND_PORT}"
echo "- frontend port: ${FRONTEND_PORT}"
echo "- frontend host: ${FRONTEND_HOST}"

# Optional env file at repo root
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

kill_port "${BACKEND_PORT}"
kill_port "${FRONTEND_PORT}"

cleanup() {
  echo
  echo "Shutting down..."
  if [[ -n "${BACK_PID:-}" ]]; then kill -TERM "${BACK_PID}" 2>/dev/null || true; fi
  if [[ -n "${FRONT_PID:-}" ]]; then kill -TERM "${FRONT_PID}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting backend..."
(
  cd "${ROOT}/backend"
  exec uv run uvicorn app.main:app --reload --port "${BACKEND_PORT}"
) &
BACK_PID=$!

wait_for_backend

echo "Starting frontend..."
(
  cd "${ROOT}/frontend"
  exec npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
) &
FRONT_PID=$!

echo "Backend pid: ${BACK_PID}"
echo "Frontend pid: ${FRONT_PID}"
echo "Ctrl+C to stop both."

wait -n "${BACK_PID}" "${FRONT_PID}"
