import { createE2EConfig } from "./playwright.base.config.js"

const config = createE2EConfig({ profile: "assistant integration", testMatch: "assistant.spec.js", outputDir: "test-results/assistant", timeout: 60000 })
const port = process.env.BACKEND_PORT || "8028"
config.webServer[0].command = `cd ../backend && .venv/bin/python -m alembic upgrade head && .venv/bin/python -m uvicorn tests.support.assistant_browser_app:app --host 127.0.0.1 --port ${port}`
Object.assign(config.webServer[0].env, { APP_ENV: "test", AUTH_MODE: "local", ASSISTANT_ENABLED: "1", ASSISTANT_BROWSER_HARNESS: "1", LLM_SETTINGS_ENCRYPTION_KEY: Buffer.alloc(32).toString("base64"), RAG_PREWARM_ON_STARTUP: "0" })
export default config
