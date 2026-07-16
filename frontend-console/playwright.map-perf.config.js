import { defineConfig } from "@playwright/test"
import baseConfig from "./playwright.config.js"

const databaseUrl = process.env.DATABASE_URL || ""
if (!databaseUrl) {
  throw new Error("test:e2e:map-perf requires an explicit dedicated PostgreSQL DATABASE_URL")
}
let databaseName = ""
try {
  const parsed = new URL(databaseUrl)
  if (!parsed.protocol.startsWith("postgresql")) throw new Error("not postgresql")
  databaseName = parsed.pathname.replace(/^\//, "")
} catch {
  throw new Error("test:e2e:map-perf requires a valid PostgreSQL DATABASE_URL")
}
if (!/(?:^|[_-])(?:audit|e2e|test)(?:$|[_-])/i.test(databaseName)) {
  throw new Error("test:e2e:map-perf requires a dedicated audit/e2e/test database")
}
if (process.env.PW_REUSE_EXISTING_SERVER !== "0") {
  throw new Error("test:e2e:map-perf requires PW_REUSE_EXISTING_SERVER=0")
}

export default defineConfig({
  ...baseConfig,
  testMatch: "map-performance.spec.js",
  preserveOutput: "always",
  retries: 0,
  workers: 1,
  use: {
    ...baseConfig.use,
    viewport: { width: 1280, height: 720 },
    hasTouch: true,
  },
})
