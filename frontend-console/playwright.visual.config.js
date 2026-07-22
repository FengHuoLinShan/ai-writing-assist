import { createE2EConfig } from "./playwright.base.config.js"

const VISUAL_DIFF_RATIO = 0.005

export default createE2EConfig({
  profile: "test:e2e:visual",
  testMatch: "visual-*.spec.js",
  preserveOutput: "failures-only",
  outputDir: "test-results/visual",
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report/visual", open: "never" }],
  ],
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: VISUAL_DIFF_RATIO,
    },
  },
  use: {
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
  },
})
