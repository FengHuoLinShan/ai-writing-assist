import { test, expect } from './fixtures.js'
import { API_BASE } from './helpers/api-client.js'
import { openWorkbench } from './helpers/workbench.js'

const headers = { 'X-Requested-With': 'XMLHttpRequest' }
async function checked(response) { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
async function seed(request, projectId, title, key) {
  const base = `${API_BASE}/world/map-atlas/${projectId}/nodes`
  const node = await checked(await request.post(base, { headers, data: { title, level: 'region' } }))
  await checked(await request.post(`${base}/${node.id}/revisions`, { headers, data: { base_revision_id: node.current_revision_id, document: { schema_version: 2, author_decision: { origin: 'manual' }, spaces: [{ id: 'main', label: title }], features: [{ id: key, kind: 'location', label: `${title}地点`, points: [{ x: 100, y: 150 }] }] } } }))
  return node
}
for (const width of [1280, 390]) {
  test(`节点合并真实预览、409、旧链接和追加式撤回 · ${width}px`, async ({ page, request, projectFactory, browserErrors }, testInfo) => {
    const project = await projectFactory({ title: `地图合并 · ${width} · 合成验收` })
    const source = await seed(request, project.id, '旧港区', 'old-port')
    const target = await seed(request, project.id, '港区总图', 'port')
    const base = `${API_BASE}/world/map-atlas/${project.id}/nodes`
    await page.setViewportSize({ width, height: 900 })
    await openWorkbench(page, project, 'map')
    if (await page.locator('.atlas-mobile-picker select').isVisible()) await page.locator('.atlas-mobile-picker select').selectOption(source.id)
    else await page.getByRole('complementary', { name: '地图层级' }).getByRole('button').filter({ hasText: '旧港区' }).click()
    const panel = page.locator('.map-node-merge')
    await panel.locator('summary').click()
    await panel.getByLabel('合并到哪张地图').selectOption(target.id)
    await panel.getByRole('button', { name: '预览地图合并', exact: true }).click()
    await expect(panel.getByRole('region', { name: '地图合并预览' })).toContainText('来源地图')
    await expect(panel).toContainText('保留的目标地图')
    await expect(panel).toContainText('来源从正式目录移出')
    await expect(panel.getByRole('button', { name: '确认合并地图', exact: true })).toBeDisabled()
    // A real competing author edit, with the correct old timestamp, invalidates the preview.
    const atlas = await checked(await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`))
    const currentTarget = atlas.nodes.find(item => item.id === target.id)
    await checked(await request.patch(`${base}/${target.id}`, { headers, data: { title: '港区总图（已更新）', expected_updated_at: currentTarget.updated_at } }))
    await panel.getByRole('checkbox').check()
    const stale = page.waitForResponse(response => response.url() === `${base}/merge`)
    await panel.getByRole('button', { name: '确认合并地图', exact: true }).click()
    await page.getByRole('button', { name: '确认合并', exact: true }).click()
    expect((await stale).status()).toBe(409)
    await expect(panel.getByRole('alert')).toContainText('选择仍保留')
    await expect(panel.getByLabel('合并到哪张地图')).toHaveValue(target.id)
    await panel.getByRole('button', { name: '预览地图合并', exact: true }).click()
    await expect(panel).toContainText('港区总图（已更新）')
    await expect(panel.getByRole('checkbox')).not.toBeChecked()
    await panel.getByRole('checkbox').check()
    await panel.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`merge-preview-${width}.png`), fullPage: true })
    const merged = page.waitForResponse(response => response.url() === `${base}/merge`)
    await panel.getByRole('button', { name: '确认合并地图', exact: true }).click()
    await page.getByRole('button', { name: '确认合并', exact: true }).click()
    const mergeResponse = await merged
    expect(mergeResponse.status()).toBe(201)
    const mergeReceipt = await mergeResponse.json()
    await expect(page.locator('.atlas-page-header h2')).toHaveText('港区总图（已更新）')
    await expect(panel.getByRole('region', { name: '合并记录' })).toContainText('旧港区')
    const after = await checked(await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`))
    expect(after.nodes.map(item => item.id)).toEqual([target.id])
    const head = await checked(await request.get(`${base}/${target.id}/map`))
    expect(head.revision.document.features).toHaveLength(2)
    expect(head.revision.document.features.every(feature => feature.points[0].x === 100 && feature.points[0].y === 150)).toBe(true)
    // Reopening the old identity must show a prompt and preserve the old URL.
    await page.evaluate(async ({ projectId, sourceId }) => window.router.navigate('map', null, true, new URLSearchParams({ novel_id: projectId, node_id: sourceId })), { projectId: project.id, sourceId: source.id })
    await page.reload(); await page.waitForFunction(() => !state.loading)
    await expect(page.locator('.atlas-merged-link')).toContainText('只读历史')
    await expect(page.locator('.map-canvas')).toHaveCount(0)
    expect(new URLSearchParams(await page.evaluate(() => window.router.getCurrentQuery().toString())).get('node_id')).toBe(source.id)
    await page.locator('.atlas-merged-link').getByRole('button', { name: '打开目标地图' }).click()
    await expect(page.locator('.atlas-page-header h2')).toHaveText('港区总图（已更新）')
    if (!await panel.evaluate(element => element.open)) await panel.locator('summary').click()
    await panel.getByRole('button', { name: '预览撤回合并', exact: true }).click()
    await expect(panel.getByRole('region', { name: '撤回合并预览' })).toContainText('追加合并前内容的恢复版本')
    await panel.scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(`merge-undo-${width}.png`), fullPage: true })
    const undone = page.waitForResponse(response => response.url() === `${base}/merge-undo`)
    await panel.getByRole('button', { name: '确认撤回合并', exact: true }).click()
    await page.getByRole('button', { name: '确认撤回', exact: true }).click()
    const undoResponse = await undone
    expect(undoResponse.ok()).toBe(true)
    const undoReceipt = await undoResponse.json()
    await expect(panel.getByRole('region', { name: '合并记录' })).toHaveCount(0)
    const restored = await checked(await request.get(`${API_BASE}/world/map-atlas/${project.id}/atlas`))
    expect(restored.nodes).toHaveLength(2)
    const history = await checked(await request.get(`${base}/${target.id}/revisions`))
    expect(history.some(item => item.id === mergeReceipt.merged_revision_id)).toBe(true)
    expect(history.some(item => item.id === undoReceipt.restored_revision_id)).toBe(true)
    expect(history).toHaveLength(4)
    expect(browserErrors.filter(item => item.kind !== 'console' || !item.text.includes('409'))).toEqual([])
  })
}
