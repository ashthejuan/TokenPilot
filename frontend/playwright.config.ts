import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

const dataDir = join(tmpdir(), `tp-e2e-${process.pid}`);
mkdirSync(dataDir, { recursive: true });
const dbPath = join(dataDir, `tp-e2e-${process.pid}.sqlite3`);
// Fixed port (not pid-derived): Playwright reloads this config in the worker
// with a different pid, and demo-loop.spec.ts must hit the same fake.
const fakePort = Number(process.env.TOKENPILOT_E2E_FAKE_PORT || 18799);
const fakeUrl = `http://127.0.0.1:${fakePort}`;

// Expose for demo-loop.spec.ts (scenario switching on the fake).
process.env.TOKENPILOT_E2E_FAKE_URL = fakeUrl;
process.env.TOKENPILOT_E2E_FAKE_PORT = String(fakePort);
process.env.TOKENPILOT_E2E_DATA_DIR = dataDir;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `cd ../backend && TOKENPILOT_FAKE_DEMO_MODE=1 TOKENPILOT_FAKE_DEMO_SCENARIO=success uv run python -m tests.fakes.fake_upstream --port ${fakePort}`,
      url: fakeUrl,
      reuseExistingServer: false,
    },
    {
      command:
        "cd ../backend && uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port 8788",
      url: "http://127.0.0.1:8788/api/v1/health",
      reuseExistingServer: false,
      env: {
        ...process.env,
        TOKENPILOT_LOCAL_TOKEN: "e2e-local-token",
        TOKENPILOT_DB_PATH: dbPath,
        TOKENPILOT_DATA_DIR: dataDir,
        TOKENPILOT_UPSTREAM_BASE_URL: fakeUrl,
        TOKENPILOT_UPSTREAM_PROVIDER: "fake",
        TOKENPILOT_FAKE_DEMO_MODE: "1",
        TOKENPILOT_FAKE_DEMO_SCENARIO: "success",
        TOKENPILOT_INVESTIGATOR_MODEL: "fake-large",
        MODEL_API_KEY: "e2e-fake-key",
      },
    },
    {
      command: "npx next dev -H 127.0.0.1 -p 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      env: {
        ...process.env,
        TOKENPILOT_API_URL: "http://127.0.0.1:8788",
        TOKENPILOT_LOCAL_TOKEN: "e2e-local-token",
      },
    },
  ],
});
