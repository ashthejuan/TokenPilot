#!/usr/bin/env bash
# One-command TokenPilot demo: fixture → API (+ fake upstream offline) → seed →
# analyze → print insight ids → start web and print /insights URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${ROOT}/demo/.data"
FIXTURE_REPO="${DATA_DIR}/fixture-repo"
DB_PATH="${DATA_DIR}/tokenpilot.sqlite3"
API_PORT="${TOKENPILOT_DEMO_API_PORT:-8790}"
WEB_PORT="${TOKENPILOT_DEMO_WEB_PORT:-3010}"
FAKE_PORT="${TOKENPILOT_DEMO_FAKE_PORT:-8799}"
LOCAL_TOKEN="${TOKENPILOT_LOCAL_TOKEN:-demo-local-token}"
MODE="live"
ONCE=0

usage() {
  echo "usage: $0 [--offline|--live] [--once]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) MODE="offline"; shift ;;
    --live) MODE="live"; shift ;;
    --once) ONCE=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

mkdir -p "${DATA_DIR}"
rm -f "${DB_PATH}" "${DB_PATH}-wal" "${DB_PATH}-shm"

echo "==> init fixture repo at ${FIXTURE_REPO}"
rm -rf "${FIXTURE_REPO}"
bash "${ROOT}/demo/scripts/init_fixture_repo.sh" "${FIXTURE_REPO}" >/dev/null

# Optional root .env for live MODEL_API_KEY / tokens (never printed).
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

# CLI / seed token: prefer existing env, else demo default.
export TOKENPILOT_LOCAL_TOKEN="${TOKENPILOT_LOCAL_TOKEN:-$LOCAL_TOKEN}"
LOCAL_TOKEN="${TOKENPILOT_LOCAL_TOKEN}"
export TOKENPILOT_API_URL="http://127.0.0.1:${API_PORT}"
export TOKENPILOT_DB_PATH="${DB_PATH}"
export TOKENPILOT_DATA_DIR="${DATA_DIR}"

if [[ "${MODE}" == "offline" ]]; then
  if [[ -z "${MODEL_API_KEY:-}" ]]; then
    export MODEL_API_KEY="demo-fake-key"
  fi
  export TOKENPILOT_UPSTREAM_PROVIDER=fake
  export TOKENPILOT_UPSTREAM_BASE_URL="http://127.0.0.1:${FAKE_PORT}"
  export TOKENPILOT_FAKE_DEMO_MODE=1
  export TOKENPILOT_FAKE_DEMO_SCENARIO="${TOKENPILOT_FAKE_DEMO_SCENARIO:-success}"
  export TOKENPILOT_INVESTIGATOR_MODEL="${TOKENPILOT_INVESTIGATOR_MODEL:-fake-large}"

  echo "==> start fake upstream on :${FAKE_PORT}"
  (
    cd "${ROOT}/backend"
    uv run python -m tests.fakes.fake_upstream --port "${FAKE_PORT}"
  ) &
  PIDS+=($!)
  for _ in $(seq 1 50); do
    if curl -sf "http://127.0.0.1:${FAKE_PORT}/" >/dev/null 2>&1 \
      || curl -sf -X POST "http://127.0.0.1:${FAKE_PORT}/v1/models" >/dev/null 2>&1 \
      || nc -z 127.0.0.1 "${FAKE_PORT}" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
else
  if [[ -z "${MODEL_API_KEY:-}" ]]; then
    echo "ERROR: MODEL_API_KEY is required for --live" >&2
    exit 1
  fi
  export TOKENPILOT_UPSTREAM_PROVIDER="${TOKENPILOT_UPSTREAM_PROVIDER:-meta}"
  export TOKENPILOT_UPSTREAM_BASE_URL="${TOKENPILOT_UPSTREAM_BASE_URL:-https://api.meta.ai/v1}"
fi

echo "==> start API on :${API_PORT}"
(
  cd "${ROOT}/backend"
  uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port "${API_PORT}"
) &
PIDS+=($!)

echo "==> wait for API health"
for _ in $(seq 1 100); do
  if curl -sf -H "Authorization: Bearer ${LOCAL_TOKEN}" \
    "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
curl -sf -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null

echo "==> register project invoicing-demo"
REGISTER_BODY=$(python3 - <<PY
import json
print(json.dumps({
  "name": "invoicing-demo",
  "slug": "invoicing-demo",
  "repository_path": r"""${FIXTURE_REPO}""",
}))
PY
)
curl -sf -X POST "http://127.0.0.1:${API_PORT}/api/v1/projects" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${REGISTER_BODY}" >/dev/null \
  || curl -sf "http://127.0.0.1:${API_PORT}/api/v1/projects" \
    -H "Authorization: Bearer ${LOCAL_TOKEN}" >/dev/null

echo "==> seed sessions (${MODE})"
(
  cd "${ROOT}"
  PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}" \
    uv run --directory "${ROOT}/backend" python "${ROOT}/demo/scripts/seed_sessions.py" \
      --mode "${MODE}" --project invoicing-demo
)

echo "==> analyze insights"
JOB_JSON=$(curl -sf -X POST "http://127.0.0.1:${API_PORT}/api/v1/insights/analyze" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}')
JOB_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"${JOB_JSON}")
for _ in $(seq 1 120); do
  STATUS=$(curl -sf "http://127.0.0.1:${API_PORT}/api/v1/jobs/${JOB_ID}" \
    -H "Authorization: Bearer ${LOCAL_TOKEN}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  if [[ "${STATUS}" == "succeeded" || "${STATUS}" == "failed" ]]; then
    break
  fi
  sleep 0.25
done
if [[ "${STATUS}" != "succeeded" ]]; then
  echo "ERROR: analyze job ${JOB_ID} ended as ${STATUS}" >&2
  exit 1
fi

echo "==> insight ids"
curl -sf "http://127.0.0.1:${API_PORT}/api/v1/insights?limit=50" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  | python3 -c "import json,sys; data=json.load(sys.stdin); items=data.get('items') or [];
print('(none)' if not items else '');
[print(f\"{i['id']}  {i['rule_id']}  {i.get('title','')}\") for i in items]"

echo "==> spend / session costs (for phase note)"
curl -sf "http://127.0.0.1:${API_PORT}/api/v1/usage/summary" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  | python3 -c "import json,sys; s=json.load(sys.stdin); print(f\"total_estimated_cost={s.get('total_estimated_cost')} {s.get('currency')} basis={s.get('cost_basis')} requests={s.get('request_count')}\")"
curl -sf "http://127.0.0.1:${API_PORT}/api/v1/sessions?limit=20" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  | python3 -c "import json,sys; 
for i in (json.load(sys.stdin).get('items') or []):
 print(f\"{i.get('external_session_id')} outcome={i.get('outcome')} cost={i.get('total_estimated_cost')} {i.get('currency')} reqs={i.get('request_count')}\")"
PROJECT_ID=$(curl -sf "http://127.0.0.1:${API_PORT}/api/v1/projects" \
  -H "Authorization: Bearer ${LOCAL_TOKEN}" \
  | python3 -c "import json,sys; ps=json.load(sys.stdin); print(next((p['id'] for p in ps if p.get('slug')=='invoicing-demo'), ps[0]['id'] if ps else ''))")
if [[ -n "${PROJECT_ID}" ]]; then
  curl -sf "http://127.0.0.1:${API_PORT}/api/v1/reports/project/${PROJECT_ID}?format=markdown" \
    -H "Authorization: Bearer ${LOCAL_TOKEN}" \
    | head -n 35
fi

echo "==> start web on :${WEB_PORT}"
(
  cd "${ROOT}/frontend"
  TOKENPILOT_API_URL="http://127.0.0.1:${API_PORT}" \
  TOKENPILOT_LOCAL_TOKEN="${LOCAL_TOKEN}" \
    npx next dev -H 127.0.0.1 -p "${WEB_PORT}"
) &
PIDS+=($!)

for _ in $(seq 1 100); do
  if curl -sf "http://127.0.0.1:${WEB_PORT}/" >/dev/null; then
    break
  fi
  sleep 0.2
done

INSIGHTS_URL="http://127.0.0.1:${WEB_PORT}/insights"
echo ""
echo "Demo ready (${MODE})."
echo "  API:      http://127.0.0.1:${API_PORT}"
echo "  Insights: ${INSIGHTS_URL}"
if command -v open >/dev/null 2>&1 && [[ "${ONCE}" -eq 0 ]]; then
  open "${INSIGHTS_URL}" >/dev/null 2>&1 || true
fi

if [[ "${ONCE}" -eq 1 ]]; then
  echo "Once mode: services verified reachable; shutting down."
  exit 0
fi

# Keep services up until interrupted (trap cleans up).
echo "Services running (Ctrl-C to stop)…"
wait
