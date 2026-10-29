import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

const dataDir = join(tmpdir(), `tp-e2e-${process.pid}`);
mkdirSync(dataDir, { recursive: true });
const dbPath = join(dataDir, `tp-e2e-${process.pid}.sqlite3`);

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
      command:
        "cd ../backend && uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port 8788",
      url: "http://127.0.0.1:8788/api/v1/health",
      reuseExistingServer: false,
      env: {
        ...process.env,
        TOKENPILOT_LOCAL_TOKEN: "e2e-local-token",
        TOKENPILOT_DB_PATH: dbPath,
        TOKENPILOT_DATA_DIR: dataDir,
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
