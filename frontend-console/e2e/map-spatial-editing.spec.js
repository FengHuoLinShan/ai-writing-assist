import { test, expect } from './fixtures.js'
import { API_BASE, createScene } from './helpers/api-client.js'
import { openWorkbench, reloadWorkbench } from './helpers/workbench.js'

const headers = { 'X-Requested-With': 'XMLHttpRequest' }
async function checked(response) { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }

test('独立空间分别展示，类型与Scene范围通过真实API保存，移动端无横向溢出', async ({ page, request, projectFactory, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: '多空间元数据 · 合成验收' })
  const scene = await createScene(project.id, { scene_index: 0, title: '抵达星港', chapter_ids: ['1'] })
  const term = await checked(await request.post(`${API_BASE}/world/project-vocabulary/${project.id}/terms`, { headers, data: { kind: 'feature', name: '星门', description: '星际交通入口', traits: { geometry: ['point'] } } }))
  const node = await checked(await request.post(`${API_BASE}/world/map-atlas/${project.id}/nodes`, { headers, data: { title: '星港与梦境', level: 'region' } }))
  const doc = { schema_version: 2, layout_version: 1, spaces: [{ id: 'main', label: '星港' }, { id: 'dream', label: '梦境' }], features: [
    { id: 'port', kind: 'location', label: '星港入口', space_id: 'main', points: [{ x: 150, y: 150 }], reader_from_chapter: 1 },
    { id: 'dream-port', kind: 'location', label: '梦中站台', space_id: 'dream', points: [{ x: 150, y: 150 }], reader_from_chapter: 1 },
  ], constraints: [], journeys: [], images: [], annotation_bindings: [] }
  await checked(await request.post(`${API_BASE}/world/map-atlas/${project.id}/nodes/${node.id}/revisions`, { headers, data: { base_revision_id: node.current_revision_id, document: doc } }))
  await page.setViewportSize({ width: 1280, height: 900 })
  await openWorkbench(page, project, 'map')
  await expect(page.locator('.map-feature')).toHaveCount(1)
  await page.getByLabel('当前地图空间', { exact: true }).selectOption('dream')
  await expect(page.locator('.map-feature')).toHaveCount(1)
  await expect(page.locator('.map-canvas')).toContainText('梦中站台')
  await expect(page.locator('.map-canvas')).not.toContainText('星港入口')
  await page.getByLabel('当前地图空间', { exact: true }).selectOption('main')
  const panel = page.locator('.spatial-metadata')
  await panel.locator(':scope > summary').click()
  await expect(panel.getByRole('status')).toHaveCount(0)
  await panel.getByRole('combobox', { name: '编辑对象', exact: true }).selectOption('features/port')
  await panel.getByRole('combobox', { name: '图元类型', exact: true }).selectOption(`${term.id}@${term.revision_id}`)
  await panel.getByLabel('从哪个场景开始生效').selectOption(scene.id)
  await panel.getByLabel('这条内容的性质').selectOption('hypothesis')
  await expect(panel).toContainText('不参与客观空间计算')
  await page.getByRole('button', { name: '保存地图', exact: true }).click()
  await expect(page.locator('.map-save-status')).toHaveText('已保存到服务端')
  const saved = await checked(await request.get(`${API_BASE}/world/map-atlas/${project.id}/nodes/${node.id}/map`))
  expect(saved.revision.document.features[0]).toMatchObject({ type_ref: term.id, type_revision_id: term.revision_id, modality: 'hypothesis', effective: { start: { kind: 'scene', id: scene.id } } })
  await page.screenshot({ path: testInfo.outputPath('spatial-editing-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('spatial-editing-mobile.png'), fullPage: true })
  await reloadWorkbench(page, 'map')
  await expect(page.locator('.map-feature')).toHaveCount(1)
  expect(browserErrors).toEqual([])
})
