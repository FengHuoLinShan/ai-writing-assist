import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from './fixtures.js'
import { API_BASE } from './helpers/api-client.js'
import { openWorkbench } from './helpers/workbench.js'

// Assistant preparation uses the real domain operation in the guarded fixture.
// Navigation and all placement requests hit real HTTP; no model/worker runs.
test('助手托盘成果带入精确目标，真人选点后原HTTP拒绝过期预览并允许重新核对', async ({ page, request, projectFactory }, testInfo) => {
  const project = await projectFactory({ title: `E2E map auto draft tray navigation ${Date.now()}` })
  const backend = fileURLToPath(new URL('../../backend', import.meta.url))
  const result = JSON.parse(execFileSync(resolve(backend, '.venv/bin/python'), ['-m', 'tests.support.map_auto_draft_browser_fixture', project.id, 'tray-navigation'], { cwd: backend, env: { ...process.env, APP_ENV: 'test', AUTH_MODE: 'local' }, encoding: 'utf8' }))
  expect(result.type).toBe('map_tray_placement')
  expect(result).not.toHaveProperty('point')
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'writing')
  await page.evaluate(async receipt => {
    const { locateAssistantSource } = await import('/vue/shared/assistantNavigation.js')
    await locateAssistantSource(receipt)
  }, result)
  const tray = page.locator('.auto-drafts')
  await expect(tray).toHaveAttribute('open', '')
  await expect(tray.locator('.draft-tray li')).toHaveCount(1)
  await expect(tray).toContainText(result.items[0].label)
  expect(new URLSearchParams(await page.evaluate(() => window.router.getCurrentQuery().toString())).get('revision_id')).toBe(result.revision_id)
  await tray.getByRole('button', { name: '在草图上选择位置', exact: true }).click()
  const region = tray.getByRole('region', { name: '待放置地点定位' })
  await expect(region.getByRole('button', { name: '预览放置影响' })).toBeDisabled()
  const canvas = region.getByRole('group')
  await canvas.click({ position: { x: 100, y: 80 } })
  await expect(region).toContainText('位置已选')
  // The server, rather than a mocked response, rejects changed source identity.
  let badPreview = true, badPlacement = true
  await page.route('**/tray/*/preview', async route => {
    const payload = route.request().postDataJSON()
    if (badPreview) { badPreview = false; payload.expected_fingerprint = '0'.repeat(64) }
    await route.continue({ postData: JSON.stringify(payload) })
  })
  const previewFailure = page.waitForResponse(response => response.url().includes('/tray/') && response.url().endsWith('/preview'))
  await region.getByRole('button', { name: '预览放置影响' }).click()
  expect((await previewFailure).status()).toBe(409)
  await expect(tray.getByRole('alert')).toBeVisible()
  await expect(region.getByRole('button', { name: '确认放入草图候选' })).toHaveCount(0)
  await region.getByRole('button', { name: '预览放置影响' }).click()
  await expect(region.getByRole('button', { name: '确认放入草图候选' })).toBeVisible()
  await page.route('**/tray/*/place', async route => {
    const payload = route.request().postDataJSON()
    if (badPlacement) { badPlacement = false; payload.preview_fingerprint = '0'.repeat(64) }
    await route.continue({ postData: JSON.stringify(payload) })
  })
  const placeFailure = page.waitForResponse(response => response.url().includes('/tray/') && response.url().endsWith('/place'))
  await region.getByRole('button', { name: '确认放入草图候选' }).click()
  await page.getByRole('button', { name: '确认放置', exact: true }).click()
  expect((await placeFailure).status()).toBe(409)
  await expect(tray).toContainText('地图、来源或托盘已变化')
  await expect(region).toContainText('位置已选')
  await region.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('tray-navigation-stale-390.png'), fullPage: true })
  await region.getByRole('button', { name: '预览放置影响' }).click()
  const placed = page.waitForResponse(response => response.url().includes('/tray/') && response.url().endsWith('/place'))
  await region.getByRole('button', { name: '确认放入草图候选' }).click()
  await page.getByRole('button', { name: '确认放置', exact: true }).click()
  expect((await placed).ok()).toBe(true)
  await expect(tray).toContainText('已放入新的草图候选')
  // The original candidate is now superseded. Reload cannot silently retarget it.
  await expect(tray).toContainText('请重新准备放置入口')
  await page.reload()
  await page.waitForFunction(() => !state.loading)
  await expect(tray).toContainText('请重新准备放置入口')
  await expect(tray.locator('.draft-item')).toHaveCount(0)
  const atlas = await (await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`)).json()
  expect(atlas.nodes).toHaveLength(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await tray.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('tray-navigation-expired-390.png'), fullPage: true })
})
