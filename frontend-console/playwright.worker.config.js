import { createE2EConfig } from "./playwright.base.config.js"

const workerTestTimeoutMs = Number(process.env.WORKER_E2E_TEST_TIMEOUT_MS || 2_700_000)
if (!Number.isFinite(workerTestTimeoutMs) || workerTestTimeoutMs < 60_000) {
  throw new Error("WORKER_E2E_TEST_TIMEOUT_MS must be a finite value >= 60000")
}

if (process.env.RUN_WORKER_E2E !== "1") {
  throw new Error("test:e2e:worker requires RUN_WORKER_E2E=1")
}

export default createE2EConfig({
  profile: "test:e2e:worker",
  testMatch: "deep-import-worker.spec.js",
  timeout: workerTestTimeoutMs,
  extraWebServers: [
    {
      command: "APP_ENV=test python run_worker.py",
      cwd: "../backend",
      timeout: 60000,
      reuseExistingServer: false,
      wait: { stdout: /TaskWorker started/ },
    },
  ],
})
