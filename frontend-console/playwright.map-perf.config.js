import { createE2EConfig } from "./playwright.base.config.js"

export default createE2EConfig({
  profile: "test:e2e:map-performance",
  testMatch: "map-performance.spec.js",
  preserveOutput: "always",
  use: {
    viewport: { width: 1280, height: 720 },
    hasTouch: true,
  },
})
