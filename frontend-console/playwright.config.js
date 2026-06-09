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
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000",
      url: "http://localhost:8000/api/health",
      timeout: 60000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "python3 -m http.server 8080",
      url: "http://localhost:8080",
      timeout: 15000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
