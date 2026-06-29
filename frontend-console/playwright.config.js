import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "cd ../backend && APP_ENV=test python -m alembic upgrade head && APP_ENV=test python -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
      url: "http://localhost:8000/api/health",
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "python -m http.server 8080",
      url: "http://localhost:8080",
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
