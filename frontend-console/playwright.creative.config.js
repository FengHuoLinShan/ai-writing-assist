import config from "./playwright.assistant.config.js"

config.testMatch = ["creative-forecast.spec.js", "creative-rebase.spec.js"]
config.outputDir = "test-results/creative"
config.timeout = 90000
Object.assign(config.webServer[0].env, {
  COLLABORATION_V2_ENABLED: "1",
  ASSISTANT_FORECAST_ENABLED: "1",
  ASSISTANT_FORECAST_SEMANTIC_ENABLED: "1",
  INTERACTION_FORECAST_ENABLED: "1",
  STORY_REHEARSAL_ENABLED: "1",
})
export default config
