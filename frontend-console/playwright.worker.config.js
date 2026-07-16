import { createE2EConfig } from "./playwright.base.config.js"

if (process.env.RUN_WORKER_E2E !== "1") {
  throw new Error("test:e2e:worker requires RUN_WORKER_E2E=1 and a running test worker")
}

export default createE2EConfig({
  profile: "test:e2e:worker",
  testMatch: "deep-import-worker.spec.js",
})
