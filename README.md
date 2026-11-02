# TokenPilot

TokenPilot measures the cost of *successfully completed* engineering work.

Token counters tell you how many tokens left the building. Provider bills tell you what you paid. Neither tells you whether that spend fixed a bug, shipped a feature, or burned retries into a dead end. TokenPilot sits between your coding agent and the model API, records every request with project/session/task labels, finds waste with deterministic rules, asks Meta Muse to explain the evidence, then runs a paired benchmark that only labels **Verified savings** when the alternative still passes your acceptance tests.

The product loop:

1. **Observe:** agent traffic through a local OpenAI-compatible gateway
2. **Attribute:** cost to projects, sessions, and tasks
3. **Detect:** seven rule-based inefficiency detectors
4. **Explain:** Muse investigation with citations into recorded events
5. **Experiment:** same repo revision, baseline vs alternative, same tests
6. **Verify:** compare cost, runtime, retries, and correctness
7. **Report:** methodology and evidence in a project report

Local-first by default: SQLite on your machine, secrets stay on the API process, content storage and content-bearing investigation off unless you flip the flags.

## What you can do

### Capture usage through a gateway

Point Codex, Muse, or any OpenAI-shaped client at TokenPilot instead of Meta directly:

| Setting | Value |
|--------|--------|
| Base URL | `http://127.0.0.1:8787/gateway/v1` |
| API key | your `TOKENPILOT_LOCAL_TOKEN` (Bearer) |
| Upstream secret | `MODEL_API_KEY` stays on the TokenPilot server |

Supported surfaces: Chat Completions, Responses, model list relays, Muse `/muse-code/models`. Project-scoped base for tooling that wants a fixed project: `http://127.0.0.1:8787/gateway/p/<project-slug>/v1`.

Optional headers bind spend to your work:

- `X-TokenPilot-Project`
- `X-TokenPilot-Session`
- `X-TokenPilot-Task`
- `X-TokenPilot-Retry-Of`

Each completed call writes a ledger event (`usage_events` + `cost_records`) and returns `X-TokenPilot-Event-Id`. Costs come from a versioned pricing catalogue with an explicit basis badge in the UI (**Estimated**, **Simulated**, or **Unavailable** when usage never arrived).

### See where money goes

| Page | Capability |
|------|------------|
| **Overview** (`/`) | Spend over time, basis badge, high-level usage |
| **Projects** | Register repos, open a project’s activity |
| **Sessions** | Per-session cost, latency, failures, drill into events |
| **Insights** | Detector findings with links into evidence |
| **Benchmarks** | Define tasks, run pairs, read comparisons |
| **Reports** | Project markdown/JSON with methodology |
| **Settings** | Privacy flags, detector thresholds, pricing, retention |

The browser never holds the local token. Next.js proxies `/api/tp/*` server-side. CORS allows `http://localhost:3000` only.

### Catch waste without an LLM first

Analysis runs seven deterministic detectors over the ledger:

| Rule id | What it looks for |
|---------|-------------------|
| `repeated_request` | Same request fingerprint fired again |
| `retry_amplification` | Retry chains that multiply spend |
| `repeated_context` | Large context resent turn after turn |
| `unsuccessful_task` | Spend on tasks that ended failed / abandoned |
| `context_ratio` | Prompt bulk out of proportion to useful output |
| `runaway_session` | Sessions that keep spending past a threshold |
| `model_inefficiency` | Costly model choice relative to peers on similar work |

Findings link back to recorded events. You can re-run analysis from the UI or `POST /api/v1/insights/analyze`.

### Investigate with Meta Muse

From an insight, start an investigation. Muse receives an evidence bundle (metadata by default; prompt/response excerpts only if both `TOKENPILOT_STORE_CONTENT` and `TOKENPILOT_ALLOW_CONTENT_TRANSMISSION` are true). It returns a structured explanation and a concrete, testable recommendation. Investigator traffic uses a direct Meta client (`TOKENPILOT_INVESTIGATOR_MODEL`, default `muse-spark-1.3-contributor`); that usage lands under an internal project so it stays visible in the ledger.

### Prove an optimization with benchmarks

Create a benchmark from an insight or by hand:

- Pin a git revision and acceptance command (pytest in the demo fixture)
- Run **baseline** and **alternative** configs (model, prompt, or agent settings)
- Each run gets an isolated git worktree; acceptance tests run under macOS `sandbox-exec` when available (otherwise env-scrub + rlimits)
- The benchmark agent calls the **same gateway**, so its tokens show up like any other session

Comparison outcomes you will see:

- **Verified savings:** alternative cheaper on the cost rules *and* correctness preserved
- **Not an optimization:** tests failed or correctness not preserved
- `low_sample` when either side has fewer than three eligible runs

Realized (production) savings are **not** measured in this version; reports say so explicitly.

### Export evidence

Project reports include spend, insights, benchmark comparisons, and the methodology block (sample size flags, classification rules, realized-savings limitation). Fetch them in the UI or via `GET /api/v1/reports/project/{id}`.

### Run an end-to-end demo

```bash
cp .env.example .env
# TOKENPILOT_LOCAL_TOKEN=any-non-empty-string
# MODEL_API_KEY=…   # required for live Meta only

make demo-offline   # fake upstream; no Meta key
# or
make demo           # live Meta
```

Both commands reset `demo/.data`, seed the `invoicing-demo` project **through the gateway** (no fake DB inserts), run insight analysis, and start the API on **8790** / web on **3010**. Open the printed `/insights` URL. Offline shows a **Simulated** basis badge; live prices against Meta with **Estimated**.

Day-to-day servers (different ports):

```bash
make dev-api   # http://127.0.0.1:8787
make dev-web   # http://127.0.0.1:3000
```

### Real demo with Muse

Point a live Muse session at TokenPilot so every coding call is attributed and visible in the UI.

1. **Configure `.env`** (from `.env.example`):
   - `TOKENPILOT_LOCAL_TOKEN` — any non-empty string; Muse will send this as the Bearer token to the gateway.
   - `MODEL_API_KEY` — your real Meta API key; TokenPilot keeps it server-side and forwards upstream.
2. **Start the stack** in two terminals:

```bash
make dev-api   # gateway + API on :8787
make dev-web   # UI on :3000
```

3. **Create a project** whose slug matches the gateway path you’ll use. In the UI (**Projects**), create one named e.g. Knowledge Base so the slug is `knowledge-base`, or `POST /api/v1/projects` with `"slug": "knowledge-base"`. Spend on `/gateway/p/knowledge-base/v1` attributes to that project automatically.
4. **Export the local token for Muse.** Muse reads `META_API_KEY` as the Bearer credential when `endpoint_transport.auth="bearer"`. Set it to the *same* value as `TOKENPILOT_LOCAL_TOKEN` (not your Meta upstream key):

```bash
export META_API_KEY="your-TOKENPILOT_LOCAL_TOKEN-value"
```

5. **Launch Muse** against the project-scoped gateway:

```bash
muse \
  -c 'endpoint_transport.base_url="http://127.0.0.1:8787/gateway/p/knowledge-base/v1"' \
  -c 'endpoint_transport.auth="bearer"' \
  --model muse-spark-1.3-contributor
```

Work in that Muse session as usual. Requests hit TokenPilot → Meta; Overview / Sessions / Insights update for `knowledge-base`. Swap the slug in the base URL if you use a different project.

`make test` → backend pytest + frontend vitest. `make e2e` → Playwright (includes the offline demo loop and the “Not an optimization” honesty path).

## Where Meta Muse runs

| Path | How |
|------|-----|
| Coding agent traffic | `/gateway/v1/chat/completions` or `/gateway/v1/responses` → Meta (or offline fake) |
| Insight investigation | Direct `MetaClient` with `TOKENPILOT_INVESTIGATOR_MODEL` |
| Benchmark agent | Same gateway; model from the run config |

## What this MVP does not do

No Anthropic Messages adapter, no automatic production routing, no realized-savings meter, macOS-first sandbox (`env-scrub-only` elsewhere), token pricing only (no Meta non-token surcharges).