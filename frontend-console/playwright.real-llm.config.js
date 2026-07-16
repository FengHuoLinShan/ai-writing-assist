import { createE2EConfig } from "./playwright.base.config.js"

if (process.env.ENABLE_REAL_LLM !== "1") {
  throw new Error("test:e2e:real-llm requires ENABLE_REAL_LLM=1")
}

export default createE2EConfig({
  profile: "test:e2e:real-llm",
  testMatch: [
    "deep-import-real.spec.js",
    "outline-real-llm.spec.js",
    "writing-conflict-real-llm.spec.js",
  ],
})
