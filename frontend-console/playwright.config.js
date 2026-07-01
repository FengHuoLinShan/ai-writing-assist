import { defineConfig } from "@playwright/test"

const backendPort = process.env.BACKEND_PORT || "8000"
const frontendPort = process.env.FRONTEND_PORT || "8080"
const rawApiHost = process.env.API_HOST || `http://localhost:${backendPort}`
const apiBase = rawApiHost.endsWith("/api") ? rawApiHost : `${rawApiHost}/api`
const frontendBase = `http://localhost:${frontendPort}`

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: frontendBase,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: `cd ../backend && APP_ENV=test python -m alembic upgrade head && APP_ENV=test python -m uvicorn app.main:app --host 0.0.0.0 --port ${backendPort}`,
      url: `${apiBase}/health`,
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `python -m http.server ${frontendPort}`,
      url: frontendBase,
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
