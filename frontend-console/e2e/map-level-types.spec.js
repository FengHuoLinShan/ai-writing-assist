import { test, expect } from './fixtures.js'
import { API_BASE } from './helpers/api-client.js'
import { openWorkbench, reloadWorkbench } from './helpers/workbench.js'

const headers = { 'X-Requested-With': 'XMLHttpRequest' }
async function checked(response) { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }

test('节点显示固定层级名称，类型改名归档保留旧修订，作者可选择新类型并保存', async ({ page, request, projectFactory, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: '地图层级 · 合成验收' })
  const vocab = `${API_BASE}/world/project-vocabulary/${project.id}`
  const atlas = `${API_BASE}/world/map-atlas/${project.id}`
  const original = await checked(await request.post(`${vocab}/terms`, { headers, data: { kind: 'level', name: '浮空群岛', description: '由漂浮岛群组成的空间层级' } }))
  const node = await checked(await request.post(`${atlas}/nodes`, { headers, data: { title: '天穹群岛', level: 'region', level_type_ref: original.id, level_type_revision_id: original.revision_id } }))
  const renamed = await checked(await request.patch(`${vocab}/terms/${original.id}`, { headers, data: { expected_revision_id: original.revision_id, name: '浮空领域', description: '新修订说明' } }))
  await checked(await request.post(`${vocab}/terms/${original.id}/archive`, { headers, data: { expected_revision_id: renamed.revision_id, confirmed: true } }))
  const selectable = await checked(await request.post(`${vocab}/terms`, { headers, data: { kind: 'level', name: '星域', description: '彼此相连的星港群' } }))
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'map')
  const title = page.locator('.atlas-page-header')
  await expect(title).toContainText('浮空群岛')
  await expect(title).toContainText('由漂浮岛群组成的空间层级')
  await expect(title).toContainText('已归档')
  await expect(title).not.toContainText('浮空领域')
  const form = page.locator('.atlas-edit')
  await form.locator(':scope > summary').click()
  const choice = form.getByLabel('项目层级类型', { exact: true })
  await expect(choice).toBeEnabled()
  await expect(choice).toHaveValue(`${original.id}@${original.revision_id}`)
  await choice.selectOption(`${selectable.id}@${selectable.revision_id}`)
  await expect(form).toContainText('彼此相连的星港群')
  await expect(page.getByRole('button', { name: '从本作品开始 RP', exact: true })).toBeDisabled()
  await choice.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('map-level-type-390.png'), fullPage: true })
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith(`/nodes/${node.id}`))
  await form.getByRole('button', { name: '保存调整', exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expect(title).toContainText('星域')
  const persisted = (await checked(await request.get(`${atlas}/atlas`))).nodes[0]
  expect(persisted).toMatchObject({ level: 'region', parent_id: null, level_type_ref: selectable.id, level_type_revision_id: selectable.revision_id, level_type: { name: '星域', description: '彼此相连的星港群', status: 'active' } })
  await reloadWorkbench(page, 'map')
  await expect(title).toContainText('星域')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(browserErrors).toEqual([])
})
