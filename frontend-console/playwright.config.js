import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",
  use: {
    baseURL: "http://localhost:8000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "cd ../backend && python -m app.main",
    port: 8000,
    timeout: 15000,
    reuseExistingServer: !process.env.CI,
  },
})
