import { test, expect } from './fixtures.js'
import { cleanupProjectStrict, createProject, waitForBackend } from './helpers/api-client.js'
import { openWorkbench } from './helpers/workbench.js'

test.describe('地图项目类型', () => {
  let project
  test.beforeAll(() => waitForBackend(60000))
  test.beforeEach(async () => { project = await createProject({ title: '空间类型合成验收', genre: 'fantasy', language: 'zh' }) })
  test.afterEach(async () => { if (project?.id) await cleanupProjectStrict(project.id); project = null })

  test('390px创建、修改、归档与恢复，操作通过真实项目API落库', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openWorkbench(page, project, 'map')
    const panel = page.locator('.vocabulary')
    await panel.locator(':scope > summary').click()
    await expect(panel).toContainText('还没有项目类型')
    await panel.getByRole('button', { name: '新增类型', exact: true }).click()
    await panel.getByLabel('名称', { exact: true }).fill('灵脉锚点')
    await panel.getByLabel('含义说明').fill('本作品连接独立空间的稳定入口')
    await panel.getByRole('button', { name: '保存类型', exact: true }).click()
    await expect(panel.getByRole('status').filter({ hasText: '类型已保存' })).toBeVisible()
    await expect(panel.locator('.vocabulary-list')).toContainText('灵脉锚点')
    await panel.getByLabel('名称', { exact: true }).fill('星港锚点')
    await panel.getByRole('button', { name: '保存类型', exact: true }).click()
    await expect(panel.locator('.vocabulary-list')).toContainText('星港锚点')
    await panel.getByRole('button', { name: '归档类型', exact: true }).click()
    await page.getByRole('button', { name: '确认归档', exact: true }).click()
    await expect(panel).toContainText('类型已归档，可以恢复')
    await panel.getByRole('button', { name: '恢复类型', exact: true }).click()
    await expect(panel).toContainText('类型已恢复')
    await expect(panel.getByLabel('名称', { exact: true })).toBeEnabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('vocabulary-390.png'), fullPage: true })
  })

  test('桌面混搭题材预设，新增类型与编辑状态可见', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openWorkbench(page, project, 'map')
    const panel = page.locator('.vocabulary')
    await panel.locator(':scope > summary').click()
    await panel.getByLabel('修仙', { exact: true }).check()
    await panel.getByLabel('都市', { exact: true }).check()
    await panel.getByRole('button', { name: '添加预设', exact: true }).click()
    await expect(panel.getByRole('status').filter({ hasText: '预设已处理' })).toBeVisible()
    await expect(panel.locator('.vocabulary-list button').first()).toBeVisible()
    await panel.locator('.vocabulary-list button').first().click()
    await expect(panel.getByLabel('名称', { exact: true })).not.toHaveValue('')
    await page.screenshot({ path: testInfo.outputPath('vocabulary-desktop.png'), fullPage: true })
  })
})
