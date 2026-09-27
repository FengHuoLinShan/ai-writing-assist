import { createE2EConfig } from "./playwright.base.config.js"

const config = createE2EConfig({ profile: "editorial integration", testMatch: "editorial.spec.js", outputDir: "test-results/editorial", timeout: 60000 })
Object.assign(config.webServer[0].env, {
  ASSISTANT_ENABLED: "1",
  ASSISTANT_EDITORIAL_ENABLED: "1",
  ASSISTANT_EDITORIAL_AUTOMATIC_ENABLED: "1",
  LLM_SETTINGS_ENCRYPTION_KEY: Buffer.alloc(32).toString("base64"),
  RAG_PREWARM_ON_STARTUP: "0",
})
export default config
