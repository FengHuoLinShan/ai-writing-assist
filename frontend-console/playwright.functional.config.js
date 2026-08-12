import { createE2EConfig } from "./playwright.base.config.js"

export default createE2EConfig({
  profile: "test:e2e:functional",
  testIgnore: [
    "visual-*.spec.js",
    "deep-import-real.spec.js",
    "outline-real-llm.spec.js",
    "writing-conflict-real-llm.spec.js",
    "deep-import-worker.spec.js",
  ],
})
