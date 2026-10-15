import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from './fixtures.js'
import { API_BASE } from './helpers/api-client.js'
import { openWorkbench, reloadWorkbench } from './helpers/workbench.js'

// Domain progress is synthetic; map placement/review uses the real disposable DB.
// No worker/provider is started. A lost authorization response must never resend.
const json = value => ({ status: 200, contentType: 'application/json', body: JSON.stringify(value) })
test('地图引导冻结授权，丢回执刷新只核对，再审核真实草图并完成', async ({ page, request, projectFactory }, testInfo) => {
  const project = await projectFactory({ title: `E2E map auto draft cold start ${Date.now()}` })
  const backend = fileURLToPath(new URL('../../backend', import.meta.url))
  execFileSync(resolve(backend, '.venv/bin/python'), ['-m', 'tests.support.map_auto_draft_browser_fixture', project.id], { cwd: backend, env: { ...process.env, APP_ENV: 'test', AUTH_MODE: 'local' }, encoding: 'utf8' })
  let phase = null, frozen = null, starts = 0, completed = false
  const choices = []
  const flow = () => ({ run_id: 'synthetic-map-flow', flow_id: 'map_cold_start', title: '建立可用地图', status: completed ? 'completed' : 'waiting_approval', steps: ['scope', 'authorization', 'monitor', 'review', 'locations', 'usable'].map(step_id => ({ step_id, title: ({ scope: '确认范围', authorization: '确认费用', monitor: '空间发现', review: '审核草图', locations: '可选采用地点', usable: '地图可用' })[step_id], state: completed ? 'done' : step_id === phase ? 'active' : 'pending' })), stop: completed ? null : { step_id: phase, kind: 'author_choice', reason: phase === 'monitor' ? '原请求结果未知，请核对回执，不能重发。' : '合成引导停点', actions: [] }, panel: { ...(frozen || {}), ...(phase === 'monitor' ? { progress: { status: 'needs_reconciliation' } } : {}), ...(['review', 'locations', 'usable'].includes(phase) ? { batch_limit: 20, drafts: { candidate_count: phase === 'review' ? 1 : 0, saved_node_count: phase === 'review' ? 0 : 1, truncated: false } } : {}) } })
  await page.route('**/api/evolution/reading?*', route => {
    if (route.request().method() === 'GET') return route.fulfill(json({ engine: { engine: 'evolution' }, default_budget_mode: 'confirmed_scope', run: null }))
    starts++
    const body = route.request().postDataJSON()
    expect(body).toEqual({ ...frozen.arguments, expected_fingerprint: 'f'.repeat(64), authorization_confirmed: true })
    return route.abort('failed')
  })
  await page.route('**/api/assistant/flows/latest*', route => route.fulfill(json(phase ? flow() : null)))
  await page.route('**/api/assistant/flows', route => { phase = 'scope'; expect(route.request().postDataJSON().flow_id).toBe('map_cold_start'); return route.fulfill(json(flow())) })
  await page.route('**/api/assistant/flows/*/advance', async route => {
    const choice = route.request().postDataJSON().choice
    choices.push(choice)
    if (choice.action === 'prepare_preview') {
      frozen = { capability: choice.capability, arguments: choice.arguments, preview: { authorization_preview: { fingerprint: 'f'.repeat(64), model: '合成验证模型', budget_mode: 'confirmed_scope', optional_steps: { spatial: { request_range: { minimum: 2, maximum: 4 }, quota: 4 } } } } }
      phase = 'authorization'
    } else if (choice.action === 'bind_authorized_run') {
      expect(choice.run_key).toBe('reading-' + frozen.arguments.operation_id); phase = 'monitor'
    } else if (choice.action === 'refresh') phase = phase === 'monitor' ? 'review' : 'locations'
    else if (choice.action === 'finish') { phase = 'usable'; completed = true }
    return route.fulfill(json(flow()))
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'map')
  let guide = page.locator('.map-cold-start')
  await guide.locator(':scope > summary').click()
  await guide.getByRole('button', { name: '开始地图引导', exact: true }).click()
  await guide.getByRole('button', { name: '预览空间范围与费用', exact: true }).click()
  await expect(guide.getByLabel('演化范围与费用确认')).toContainText('2—4 次调用')
  expect(starts).toBe(0)
  await guide.getByRole('button', { name: '确认此范围与费用并启动演化', exact: true }).click()
  await expect(guide).toContainText('授权结果尚待核对')
  await guide.getByRole('button', { name: '核对原授权结果', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('map-cold-start-unknown-390.png'), fullPage: true })
  await reloadWorkbench(page, 'map')
  guide = page.locator('.map-cold-start')
  await guide.locator(':scope > summary').click()
  await expect(guide.getByRole('button', { name: '确认此范围与费用并启动演化', exact: true })).toHaveCount(0)
  await guide.getByRole('button', { name: '核对原授权结果', exact: true }).click()
  await expect(guide).toContainText('原请求结果未知')
  await guide.getByRole('button', { name: '刷新地图引导进度', exact: true }).click()
  await guide.getByRole('button', { name: '前往草图审核', exact: true }).click()
  const tray = page.locator('.auto-drafts')
  await expect(tray).toHaveAttribute('open', '')
  await tray.getByText(/^待放置托盘/).first().click()
  await tray.getByRole('button', { name: '在草图上选择位置', exact: true }).first().click()
  const placement = tray.getByRole('region', { name: '待放置地点定位' })
  const canvas = placement.getByRole('group', { name: '待放置位置，点击或按 Enter 选点、方向键微调' })
  await canvas.focus(); await canvas.press('Enter')
  await placement.getByRole('button', { name: '预览放置影响', exact: true }).click()
  await placement.getByRole('button', { name: '确认放入草图候选', exact: true }).click()
  await page.getByRole('button', { name: '确认放置', exact: true }).click()
  await expect(tray).toContainText('已放入新的草图候选')
  await tray.locator('.draft-item').filter({ hasText: '1 个图元' }).getByRole('button', { name: '打开地图逐项审核', exact: true }).click()
  await page.getByRole('button', { name: /^核对所选/ }).click()
  await page.getByRole('button', { name: /^确认采用共/ }).click()
  await expect(page.locator('.atlas-tree button')).toHaveCount(1)
  const atlas = await (await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`)).json()
  expect(atlas.nodes).toHaveLength(1)
  await guide.getByRole('button', { name: '刷新地图引导进度', exact: true }).click()
  await guide.getByRole('button', { name: '完成地图引导', exact: true }).click()
  await expect(guide).toContainText('已完成')
  expect(starts).toBe(1)
  expect(choices.map(item => item.action)).toEqual(['prepare_preview', 'bind_authorized_run', 'refresh', 'refresh', 'finish'])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await guide.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('map-cold-start-usable-390.png'), fullPage: true })
})

test('合成正文经真实HTTP准备冻结预览、独立授权与绑定刷新', async ({ page, request, projectFactory, browserErrors }, testInfo) => {
  test.skip(process.env.MAP_COLD_START_HTTP !== '1', 'Requires the no-worker map_cold_start_browser_app fixture')
  const project = await projectFactory({ title: `E2E map cold start HTTP ${Date.now()}` })
  const backend = fileURLToPath(new URL('../../backend', import.meta.url))
  execFileSync(resolve(backend, '.venv/bin/python'), ['-m', 'tests.support.map_cold_start_browser_fixture', project.id], { cwd: backend, env: { ...process.env, APP_ENV: 'test', AUTH_MODE: 'local' }, encoding: 'utf8' })
  const capabilities = await (await request.get(`${API_BASE}/assistant/capabilities?novel_id=${project.id}`)).json()
  expect(capabilities.guided_flows.available).toBe(true)
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'map')
  const guide = page.locator('.map-cold-start')
  await guide.locator(':scope > summary').click()
  const started = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/assistant/flows'))
  await guide.getByRole('button', { name: '开始地图引导', exact: true }).click()
  const flow = await (await started).json()
  expect(flow).toMatchObject({ flow_id: 'map_cold_start', stop: { step_id: 'scope' } })
  const prepared = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/advance'))
  await guide.getByRole('button', { name: '预览空间范围与费用', exact: true }).click()
  const previewResponse = await prepared
  expect(previewResponse.ok(), await previewResponse.text()).toBe(true)
  const authorization = await previewResponse.json()
  expect(authorization).toMatchObject({ stop: { step_id: 'authorization' }, panel: { authorization_required: true, capability: 'evolution.prepare_spatial_reading' } })
  const frozen = authorization.panel
  await expect(guide.getByLabel('演化范围与费用确认')).toContainText('synthetic-no-network')
  const authorized = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/evolution/reading?'))
  const bound = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/advance'))
  await guide.getByRole('button', { name: '确认此范围与费用并启动演化', exact: true }).click()
  const evolutionResponse = await authorized
  expect(evolutionResponse.ok(), await evolutionResponse.text()).toBe(true)
  expect(evolutionResponse.request().postDataJSON()).toEqual({ ...frozen.arguments, expected_fingerprint: frozen.preview.authorization_preview.fingerprint, authorization_confirmed: true })
  const boundResponse = await bound
  expect(boundResponse.ok(), await boundResponse.text()).toBe(true)
  expect(await boundResponse.json()).toMatchObject({ stop: { step_id: 'monitor' }, panel: { progress: { status: 'pending', operation_id: frozen.arguments.operation_id, run_key: 'reading-' + frozen.arguments.operation_id } } })
  const refreshed = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/advance'))
  await guide.getByRole('button', { name: '刷新地图引导进度', exact: true }).click()
  expect((await refreshed).ok()).toBe(true)
  await expect(guide).toContainText('等待演化执行')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await guide.getByRole('button', { name: '刷新地图引导进度', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('map-cold-start-real-http-390.png'), fullPage: true })
  expect(browserErrors).toEqual([])
})

for (const stale of [false, true]) test(stale ? '候选地点确认期间内容变化时原World采用拒绝409，地图不继续' : '普通草图采用可先勾选绑定候选地点，World成功后重新预览再确认地图', async ({ page, request, projectFactory, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: `E2E map auto draft candidate locations ${Date.now()}` })
  const backend = fileURLToPath(new URL('../../backend', import.meta.url))
  execFileSync(resolve(backend, '.venv/bin/python'), ['-m', 'tests.support.map_auto_draft_browser_fixture', project.id, 'candidate-locations'], { cwd: backend, env: { ...process.env, APP_ENV: 'test', AUTH_MODE: 'local' }, encoding: 'utf8' })
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'map')
  const tray = page.locator('.auto-drafts')
  await tray.locator(':scope > summary').click()
  await tray.getByText(/^待放置托盘/).first().click()
  await tray.getByRole('button', { name: '在草图上选择位置', exact: true }).first().click()
  const placement = tray.getByRole('region', { name: '待放置地点定位' })
  const canvas = placement.getByRole('group', { name: '待放置位置，点击或按 Enter 选点、方向键微调' })
  await canvas.focus(); await canvas.press('Enter')
  await placement.getByRole('button', { name: '预览放置影响', exact: true }).click()
  await placement.getByRole('button', { name: '确认放入草图候选', exact: true }).click()
  await page.getByRole('button', { name: '确认放置', exact: true }).click()
  await expect(tray).toContainText('已放入新的草图候选')
  await tray.locator('.draft-item').filter({ hasText: '1 个图元' }).getByRole('button', { name: '打开地图逐项审核', exact: true }).click()
  const preview = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/review-preview'))
  await page.getByRole('button', { name: /^核对所选/ }).click()
  const payload = await (await preview).json()
  expect(payload.candidate_locations).toHaveLength(1)
  expect(payload.candidate_locations[0]).toMatchObject({ status: 'candidate', can_adopt: true })
  const location = payload.candidate_locations[0]
  const optional = page.getByLabel('可选同时采用候选地点')
  await expect(optional.getByRole('checkbox')).not.toBeChecked()
  const saveMap = page.getByRole('button', { name: /^确认采用共/ })
  await expect(saveMap).toBeEnabled()
  await optional.getByRole('checkbox').check()
  await expect(saveMap).toBeDisabled()
  await optional.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('map-candidate-location-choice-390.png'), fullPage: true })
  await optional.getByRole('button', { name: /^先确认采用所选/ }).click()
  if (stale) execFileSync(resolve(backend, '.venv/bin/python'), ['-m', 'tests.support.map_auto_draft_browser_fixture', project.id, 'mutate-entity', location.entity_id], { cwd: backend, env: { ...process.env, APP_ENV: 'test', AUTH_MODE: 'local' }, encoding: 'utf8' })
  const promoted = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes(`/entities/${location.entity_id}/promote`))
  const reprepared = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/review-preview'))
  await page.getByRole('button', { name: '确认采用地点', exact: true }).click()
  const promotion = await promoted
  expect(promotion.request().postDataJSON()).toEqual({ expected_source_hash: location.source_hash })
  if (stale) {
    expect(promotion.status()).toBe(409)
    await reprepared
    await expect(page.getByRole('alert').filter({ hasText: '已成功的地点保留' })).toBeVisible()
    await page.getByRole('alert').filter({ hasText: '已成功的地点保留' }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('map-candidate-location-stale-390.png'), fullPage: true })
    expect((await (await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`)).json()).nodes).toHaveLength(0)
    expect((await (await request.get(`${API_BASE}/world/entities/${location.entity_id}?novel_id=${project.id}`)).json()).status).toBe('candidate')
    return
  }
  expect(promotion.ok()).toBe(true)
  expect((await reprepared).ok()).toBe(true)
  await expect(saveMap).toBeEnabled()
  const atlasUrl = `${API_BASE}/world/map-atlas/${project.id}/atlas`
  expect((await (await request.get(atlasUrl)).json()).nodes).toHaveLength(0)
  const entity = await (await request.get(`${API_BASE}/world/entities/${location.entity_id}?novel_id=${project.id}`)).json()
  expect(entity.status).toBe('canonical')
  await saveMap.click()
  await expect(page.locator('.atlas-tree button')).toHaveCount(1)
  expect((await (await request.get(atlasUrl)).json()).nodes).toHaveLength(1)
  expect(browserErrors).toEqual([])
})
