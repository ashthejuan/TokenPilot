# TokenPilot web UI

Local-only Next.js 15 dashboard for Phase 1 (Overview + API proxy).

## Run

From the repo root (loads `TOKENPILOT_LOCAL_TOKEN` / `TOKENPILOT_API_URL` from the root `.env` into the Next **server** process only):

```bash
make dev-api   # terminal 1 — backend on 127.0.0.1:8787
make dev-web   # terminal 2 — UI on 127.0.0.1:3000
```

Then open http://127.0.0.1:3000. Do not use bare `npm run dev` from another machine’s perspective: scripts bind **127.0.0.1** so the token-injecting `/api/tp` proxy is not reachable on the LAN.

## Checks

```bash
cd frontend && npm test          # Vitest
cd frontend && npm run lint && npx tsc --noEmit
make test && make lint           # from repo root (backend + frontend)
```

Regenerate OpenAPI types after backend API changes:

```bash
make types
```
