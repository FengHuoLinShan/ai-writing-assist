import { devices } from '@playwright/test'
import { createE2EConfig } from './playwright.base.config.js'

const config = createE2EConfig({
  profile: 'test:e2e:webkit',
  testMatch: ['responsive-core.spec.js', 'interaction.spec.js'],
  outputDir: 'test-results/webkit',
  timeout: 60000,
  use: { ...devices['iPhone 13'], browserName: 'webkit' },
})
config.grep = /移动核心流程|流式重复与缺口/
export default config
