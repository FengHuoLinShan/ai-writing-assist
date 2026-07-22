import { defineConfig } from "@playwright/test"
import { validateE2EDatabaseEnvironment } from "./e2e/helpers/database-guard.js"

export function createE2EConfig({
  profile,
  testMatch,
  testIgnore,
  preserveOutput,
  outputDir,
  reporter = "list",
  expect,
  timeout,
  use = {},
  extraWebServers = [],
}) {
  validateE2EDatabaseEnvironment(profile)

  const backendPort = process.env.BACKEND_PORT || "8000"
  const frontendPort = process.env.FRONTEND_PORT || "8080"
  const rawApiHost = process.env.API_HOST || `http://localhost:${backendPort}`
  const apiBase = rawApiHost.endsWith("/api") ? rawApiHost : `${rawApiHost}/api`
  const frontendBase = `http://localhost:${frontendPort}`

  return defineConfig({
    testDir: "./e2e",
    testMatch,
    testIgnore,
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: 0,
    workers: 1,
    reporter,
    preserveOutput,
    ...(timeout ? { timeout } : {}),
    ...(outputDir ? { outputDir } : {}),
    ...(expect ? { expect } : {}),
    use: {
      baseURL: frontendBase,
      trace: "retain-on-failure",
      screenshot: "only-on-failure",
      video: "retain-on-failure",
      ...use,
    },
    webServer: [
      {
        command: `cd ../backend && APP_ENV=test python -m alembic upgrade head && APP_ENV=test python -m uvicorn app.main:app --host 0.0.0.0 --port ${backendPort}`,
        url: `${apiBase}/health`,
        timeout: 60000,
        reuseExistingServer: false,
      },
      {
        command: `FRONTEND_PORT=${frontendPort} npm run dev`,
        url: frontendBase,
        timeout: 60000,
        reuseExistingServer: false,
      },
      ...extraWebServers,
    ],
  })
}
