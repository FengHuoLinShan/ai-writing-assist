import { test, expect } from './fixtures.js'
import { createProject, cleanupProject, createDraft, createEntity, createWorldBiblePage, createScene, createThread, waitForBackend } from './helpers/api-client.js'
import { openWorkbench, openWorkspaceTools } from './helpers/workbench.js'
import { runResponsiveMatrix, expectResponsiveLayout, expectActionReachable, WORKSPACE_VIEWPORTS } from './helpers/responsive.js'
import { mockRpApis, journeyId } from './helpers/rp-fixture.js'

let project, scene
test.beforeAll(async () => {
  await waitForBackend(60000)
  project = await createProject({ title: '一部标题很长且包含WorldbuildingReference的持续创作作品', language: 'zh' })
  await createDraft(project.id, 1, '雾港章节：在狭窄窗口保持完整创作能力', '潮声穿过窗沿。\n'.repeat(100))
  await createWorldBiblePage(project.id, { title: '长中文资料标题与 Worldbuilding Reference', page_type: 'background', free_text: 'https://example.test/' + 'long_source_reference_'.repeat(30) })
  for (let index = 0; index < 12; index++) await createEntity(project.id, { name: `沉钟港长期资料 ${index}`, entity_type: 'location', status: 'canonical', summary: '长期资料摘要'.repeat(12) })
  scene = await createScene(project.id, { title: '港口场景', scene_index: 0, status: 'draft', chapter_ids: ['1'] })
  await createThread(project.id, { name: '雾港主线', thread_type: 'main', summary: '城市的长期秘密' })
})
test.afterAll(async () => { if (project) await cleanupProject(project.id) })

const routes = [
  ['project', null], ['writing', null], ['world', 'bible'], ['world', 'objects'],
  ['world', 'review'], ['world', 'relations'], ['world', 'aliases'],
  ['outline', 'story-outline'], ['outline', 'arcs'], ['outline', 'threads'], ['outline', 'scenes'],
  ['rag', 'search'], ['rag', 'status'], ['map', null], ['generate', null], ['settings', null], ['project-settings', null],
]
for (const [view, subview] of routes) {
  test(`${view}/${subview || 'main'} 在全站屏幕矩阵中保留必要内容和操作`, async ({ page, browserErrors }, testInfo) => {
    await openWorkbench(page, project, view, subview)
    if (view === 'writing') {
      await page.evaluate(() => window.router.navigate('writing', null, true, new URLSearchParams({ chapter_index: '1' })))
      await expect(page.getByRole('textbox', { name: '章节正文', exact: true })).toBeVisible()
    }
    const extended = ['writing', 'map'].includes(view) || (view === 'world' && subview === 'review')
    await runResponsiveMatrix(page, async viewport => {
      await expectResponsiveLayout(page)
      if (view === 'writing') await expectActionReachable(page.getByRole('button', { name: '保存工作稿', exact: true }))
      if (view === 'project') await expectActionReachable(page.getByRole('button', { name: '新建空白作品', exact: true }))
      if (view === 'map') {
        await openWorkspaceTools(page)
        await expectActionReachable(page.getByRole('button', { name: '新建地图', exact: true }).first())
        const close = page.getByRole('button', { name: '关闭地图工具', exact: true })
        if (await close.isVisible()) await close.click()
      }
      if (viewport.width === 768 && ['writing', 'world', 'map'].includes(view)) await page.screenshot({ path: testInfo.outputPath(`tablet-${view}.png`) })
    }, extended ? WORKSPACE_VIEWPORTS : undefined)
    expect(browserErrors).toEqual([])
  })
}

test('写作首页、场景详情及计划面板在窄屏和矮窗口可达', async ({ page }) => {
  await openWorkbench(page, project, 'writing')
  await page.evaluate(() => window.router.navigate('writing', null, true, new URLSearchParams({ home: '1' })))
  await runResponsiveMatrix(page, () => expectResponsiveLayout(page))
  await page.evaluate(() => window.router.navigate('writing', null, true, new URLSearchParams({ home: '1', panel: 'tasks', create: '1' })))
  const title = page.locator('#author-task-title')
  await expect(title).toBeVisible()
  await title.fill('跨窗口保留的计划草稿')
  await runResponsiveMatrix(page, async () => {
    await expect(title).toHaveValue('跨窗口保留的计划草稿')
    await expectActionReachable(page.getByRole('button', { name: '保存任务', exact: true }))
    await expectResponsiveLayout(page)
  })
  await page.getByRole('button', { name: '保存任务', exact: true }).click()
  await expect(page.getByText('跨窗口保留的计划草稿', { exact: true })).toBeVisible()
  await page.evaluate(id => window.router.navigate('scene', id, true), scene.id)
  await runResponsiveMatrix(page, () => expectResponsiveLayout(page))
})

test('首页、旅程准备和故事阅读在屏幕矩阵中可用', async ({ page }) => {
  await mockRpApis(page)
  for (const path of ['/', '/#journeys', `/#interaction/${journeyId}`]) {
    await page.goto(path)
    await expect(page.locator('.entry-choice, .rp-list-page, .rp-story-page').first()).toBeVisible()
    await runResponsiveMatrix(page, () => expectResponsiveLayout(page), path.includes('interaction') ? WORKSPACE_VIEWPORTS : undefined)
  }
})

test('作品长标题、列表末项和资料详情在窄屏与矮窗口可操作', async ({ page }) => {
  await openWorkbench(page, project, 'world', 'bible')
  await page.setViewportSize({ width: 320, height: 740 })
  await page.getByRole('searchbox', { name: '搜索资料' }).fill('沉钟港')
  await page.getByRole('search').getByRole('button', { name: '查找' }).click()
  const last = page.locator('.world-library-list__row').last().locator('[data-action="open-world-card"]')
  await expectActionReachable(last)
  await last.click()
  await expectResponsiveLayout(page)
  await page.setViewportSize({ width: 1000, height: 500 })
  await expectResponsiveLayout(page)
})
