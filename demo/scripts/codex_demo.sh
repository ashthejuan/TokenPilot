#!/usr/bin/env bash
# Codex demo: start TokenPilot offline, drive it the way Codex does (OpenAI
# Responses API + custom attribution headers), print the X-TokenPilot-Event-Id
# header the gateway returns, and verify insights were created.
#
#   bash demo/scripts/codex_demo.sh           # run, verify, exit
#   bash demo/scripts/codex_demo.sh --serve   # also start web on /insights until Ctrl-C
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${TOKENPILOT_DEMO_DATA_DIR:-${ROOT}/demo/.data/codex}"
API_PORT="${TOKENPILOT_DEMO_API_PORT:-8790}"
WEB_PORT="${TOKENPILOT_DEMO_WEB_PORT:-3010}"
FAKE_PORT="${TOKENPILOT_DEMO_FAKE_PORT:-8799}"
PROJECT="invoicing-demo"
SESSION="codex-demo"
SERVE=0

case "${1:-}" in
  "") ;;
  --serve) SERVE=1 ;;
  *) echo "usage: $0 [--serve]" >&2; exit 2 ;;
esac

PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    # `uv run` / `npx` spawn the real server as a child: stop children first.
    pkill -P "$pid" 2>/dev/null || true
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT INT TERM

# Isolated DB + fixture repo; never reads or prints the root .env.
export TOKENPILOT_LOCAL_TOKEN="${TOKENPILOT_LOCAL_TOKEN:-demo-local-token}"
export TOKENPILOT_API_URL="http://127.0.0.1:${API_PORT}"
export TOKENPILOT_DB_PATH="${DATA_DIR}/tokenpilot.sqlite3"
export TOKENPILOT_DATA_DIR="${DATA_DIR}"
export MODEL_API_KEY="demo-fake-key"
export TOKENPILOT_UPSTREAM_PROVIDER=fake
export TOKENPILOT_UPSTREAM_BASE_URL="http://127.0.0.1:${FAKE_PORT}"
export TOKENPILOT_FAKE_DEMO_MODE=1
export TOKENPILOT_FAKE_DEMO_SCENARIO=success
export TOKENPILOT_INVESTIGATOR_MODEL=fake-large
AUTH=(-H "Authorization: Bearer ${TOKENPILOT_LOCAL_TOKEN}")
API="${TOKENPILOT_API_URL}"

rm -rf "${DATA_DIR}"
mkdir -p "${DATA_DIR}"
bash "${ROOT}/demo/scripts/init_fixture_repo.sh" "${DATA_DIR}/fixture-repo" >/dev/null

echo "==> start fake upstream :${FAKE_PORT} and API :${API_PORT}"
(cd "${ROOT}/backend" && exec uv run python -m tests.fakes.fake_upstream --port "${FAKE_PORT}") &
PIDS+=($!)
(cd "${ROOT}/backend" && exec uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port "${API_PORT}") &
PIDS+=($!)
for _ in $(seq 1 100); do
  curl -sf "${AUTH[@]}" "${API}/api/v1/health" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -sf "${AUTH[@]}" "${API}/api/v1/health" >/dev/null || { echo "ERROR: API did not become healthy" >&2; exit 1; }

echo "==> register project ${PROJECT}"
curl -sf -X POST "${API}/api/v1/projects" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"name\":\"${PROJECT}\",\"slug\":\"${PROJECT}\",\"repository_path\":\"${DATA_DIR}/fixture-repo\"}" >/dev/null

echo "==> seed sessions (repeated context, 429 retries, expensive failure)"
PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}" \
  uv run --directory "${ROOT}/backend" python "${ROOT}/demo/scripts/seed_sessions.py" \
    --mode offline --project "${PROJECT}"

echo "==> Codex-style request: POST /gateway/p/${PROJECT}/v1/responses"
HEADERS_OUT="$(curl -s -D - -o /dev/null -X POST "${API}/gateway/p/${PROJECT}/v1/responses" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -H "X-TokenPilot-Project: ${PROJECT}" -H "X-TokenPilot-Session: ${SESSION}" \
  -d '{"model":"fake-small","input":"Say ok.","stream":false}')"
EVENT_ID="$(printf '%s' "${HEADERS_OUT}" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-tokenpilot-event-id"{print $2}')"
if [[ -z "${EVENT_ID}" ]]; then
  echo "ERROR: gateway response had no X-TokenPilot-Event-Id header" >&2
  printf '%s\n' "${HEADERS_OUT}" >&2
  exit 1
fi
echo "X-TokenPilot-Event-Id: ${EVENT_ID}"

echo "==> analyze insights"
JOB_ID="$(curl -sf -X POST "${API}/api/v1/insights/analyze" "${AUTH[@]}" -H "Content-Type: application/json" -d '{}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
STATUS=""
for _ in $(seq 1 120); do
  STATUS="$(curl -sf "${API}/api/v1/jobs/${JOB_ID}" "${AUTH[@]}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  [[ "${STATUS}" == "succeeded" || "${STATUS}" == "failed" ]] && break
  sleep 0.25
done
[[ "${STATUS}" == "succeeded" ]] || { echo "ERROR: analyze job ${JOB_ID} ended as ${STATUS}" >&2; exit 1; }

COUNT="$(curl -sf "${API}/api/v1/insights?limit=50" "${AUTH[@]}" | python3 -c '
import json, sys
items = json.load(sys.stdin).get("items") or []
for i in items:
    print("  %s  %s  %s" % (i["id"], i["rule_id"], i.get("title", "")), file=sys.stderr)
print(len(items))')"
if [[ "${COUNT}" -lt 1 ]]; then
  echo "ERROR: analysis created no insights" >&2
  exit 1
fi
echo "==> ${COUNT} insight(s) created"

cat <<EOF

To point a real Codex at this gateway (while the API is up):
  export TOKENPILOT_LOCAL_TOKEN=${TOKENPILOT_LOCAL_TOKEN}
  codex exec \\
    -c model_provider=tokenpilot \\
    -c 'model_providers.tokenpilot={name="TokenPilot",base_url="${API}/gateway/p/${PROJECT}/v1",env_key="TOKENPILOT_LOCAL_TOKEN",wire_api="responses",http_headers={"X-TokenPilot-Project"="${PROJECT}","X-TokenPilot-Session"="codex-live"}}' \\
    -m fake-small "say ok"
EOF

if [[ "${SERVE}" -eq 1 ]]; then
  echo "==> start web on :${WEB_PORT}"
  (cd "${ROOT}/frontend" && exec npx next dev -H 127.0.0.1 -p "${WEB_PORT}") &
  PIDS+=($!)
  for _ in $(seq 1 100); do curl -sf "http://127.0.0.1:${WEB_PORT}/" >/dev/null && break; sleep 0.2; done
  echo "Insights: http://127.0.0.1:${WEB_PORT}/insights  (Ctrl-C to stop)"
  wait
fi
