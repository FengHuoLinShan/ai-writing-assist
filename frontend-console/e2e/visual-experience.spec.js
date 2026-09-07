import { fileURLToPath } from 'node:url'
import { test, expect } from './fixtures.js'
import { openWorkbench } from './helpers/workbench.js'
test.beforeEach(() => test.skip(process.platform !== 'darwin' && !process.env.VISUAL_BASELINE, '视觉基线按平台显式维护'))
const journeyId = '11111111-1111-4111-8111-111111111111'
const story = {
  id: journeyId, title: '雾港钟楼', title_source: 'user', opening_text: '我是一名刚到雾港的修表师。', status: 'active', see_sea_enabled: false,
  action_options_enabled: true, selection_epoch: 1, overview_epoch: 0, selected_leaf_node_id: 'a1', setup_messages: [],
  messages: [{ id: 'a1', parent_node_id: null, role: 'assistant', message_kind: 'story', content: '钟楼的铜门在海风里缓缓打开。\n\n你点亮提灯，看见齿轮间夹着一封旧信。信纸上的墨迹正在重新浮现。', completion_state: 'complete', end_reason: 'stop', action_suggestions: [], story_ended: false, created_at: '2026-09-01T00:00:00Z' }],
  has_older_messages: false, active_attempt: null,
}
async function mockStory(page) {
    await page.route('**/api/account/settings/llm-connections', route => route.fulfill({ json: { active_provider_id: 'deepseek', providers: [{ provider_id: 'deepseek', label: 'DeepSeek', model: 'test', connected: true, active: true }] } }))
    await page.route('**/api/interactions/preferences', route => route.fulfill({ json: { see_sea_notice_acknowledged: true } }))
    await page.route('**/api/interactions/journeys?*', route => route.fulfill({ json: { items: [ { ...story, opening_excerpt: story.opening_text, current_excerpt: '钟楼的铜门缓缓打开。', latest_activity_at: '2026-09-01T00:00:00Z' } ], total: 1 } }))
    await page.route(`**/api/interactions/journeys/${journeyId}/path-index`, route => route.fulfill({ json: { selection_epoch: 1, items: [{ id: 'a1', ordinal: 1, total: 1, excerpt: '钟楼的铜门缓缓打开。' }] } }))
    await page.route(`**/api/interactions/journeys/${journeyId}/nodes/*/branches`, route => route.fulfill({ json: { parent_node_id: null, variants: [] } }))
    await page.route(`**/api/interactions/journeys/${journeyId}`, route => route.fulfill({ json: story }))
}
async function screenshot(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page.locator('#toast-container > *')).toHaveCount(0)
  await expect(page).toHaveScreenshot(name, { animations: 'disabled', caret: 'hide' })
}
for (const mode of ['light', 'dark']) {
  test(`公共入口、认证与外观 ${mode}`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('nc-theme', value), mode)
    await page.route('**/api/auth/config', route => route.fulfill({ json: { auth_mode: 'public', wechat_enabled: false, terms_url: '/terms', privacy_url: '/privacy' } }))
    await page.route('**/api/auth/me', route => route.fulfill({ status: 401, json: { detail: 'not signed in' } }))
    await page.goto('/')
    await expect(page.locator('.entry-choice')).toBeVisible()
    await screenshot(page, `entry-${mode}.png`)
    await page.getByRole('button', { name: /我是作家/ }).click()
    await expect(page.getByRole('heading', { name: '登录或注册' })).toBeVisible()
    await screenshot(page, `auth-${mode}.png`)
    await page.setViewportSize({ width: 390, height: 844 })
    await screenshot(page, `auth-mobile-${mode}.png`)
    await page.unroute('**/api/auth/config')
    await page.unroute('**/api/auth/me')
    await page.goto('/#settings?section=appearance')
    await page.reload()
    await page.getByRole('button', { name: '账户菜单', exact: true }).click()
    await page.getByRole('button', { name: /^外观/ }).click()
    await expect(page.getByRole('heading', { name: '让创作空间适合你' })).toBeVisible()
    await screenshot(page, `appearance-mobile-${mode}.png`)
  })
  test(`互动故事与手机阅读 ${mode}`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('nc-theme', value), mode)
    await mockStory(page)
    await page.goto('/#journeys')
    await expect(page.locator('.rp-list-page')).toBeVisible()
    await screenshot(page, `journeys-${mode}.png`)
    await page.goto(`/#interaction/${journeyId}`)
    await expect(page.locator('.rp-story-page')).toContainText('钟楼的铜门')
    await screenshot(page, `story-${mode}.png`)
    await page.setViewportSize({ width: 390, height: 844 })
    await screenshot(page, `story-mobile-${mode}.png`)
  })
  test(`地图首次进入与手机浏览 ${mode}`, async ({ page, projectFactory }) => {
    const project = await projectFactory({ title: '三河地图册', genre: 'fantasy', language: 'zh' })
    await page.addInitScript(value => localStorage.setItem('nc-theme', value), mode)
    await openWorkbench(page, project, 'map')
    await expect(page.locator('.atlas-workspace')).toBeVisible()
    await screenshot(page, `map-empty-${mode}.png`)
    await page.setViewportSize({ width: 390, height: 844 })
    await screenshot(page, `map-empty-mobile-${mode}.png`)
  })
}

test('互动故事使用资源包中的正文字体', async ({ page }) => {
  const sample = fileURLToPath(new URL('../themes/quiet-library.nctheme.zip', import.meta.url))
  await page.goto('/#settings?section=appearance')
  await page.getByLabel('导入主题包', { exact: true }).setInputFiles(sample)
  await page.getByRole('button', { name: '导入并应用' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await mockStory(page)
  await page.goto(`/#interaction/${journeyId}`)
  await expect(page.locator('.rp-message__text').first()).toHaveCSS('font-family', /nc-quiet-library/)
  await screenshot(page, 'story-resource-theme.png')
  await page.setViewportSize({ width: 390, height: 844 })
  await screenshot(page, 'story-resource-theme-mobile.png')
})
