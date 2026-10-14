import { createE2EConfig } from "/Users/tywww/Desktop/项目/ai-writing-assist/.worktrees/audit-g8-atlas-invalidation/frontend-console/playwright.base.config.js"
const config = createE2EConfig({ profile: "g8-atlas-invalidation", testMatch: "writing-map-invalidation.spec.js", outputDir: "/tmp/g8-playwright-results" })
config.testDir = "/Users/tywww/Desktop/项目/ai-writing-assist/.worktrees/audit-g8-atlas-invalidation/frontend-console/e2e"
config.webServer[0].cwd = "/Users/tywww/Desktop/项目/ai-writing-assist/.worktrees/audit-g8-atlas-invalidation/frontend-console"
config.webServer[0].command = "cd ../backend && APP_ENV=test /Users/tywww/.codex/worktrees/codex-luna-runtime/ai-writing-assist/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18122"
config.webServer[1].cwd = "/Users/tywww/Desktop/项目/ai-writing-assist/.worktrees/audit-g8-atlas-invalidation/frontend-console"
export default config
