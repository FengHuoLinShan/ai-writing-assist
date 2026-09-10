import { readFile } from 'node:fs/promises'
import { test, expect } from './fixtures.js'
import { API_BASE, createProject, cleanupProject } from './helpers/api-client.js'
import { openWorkbench } from './helpers/workbench.js'
import { expectNoPageOverflow } from './helpers/responsive.js'

async function api(path, body) {
  const response = await fetch(`${API_BASE}${path}`, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, ...(body ? { body: JSON.stringify(body) } : {}) })
  const value = await response.json()
  expect(response.ok, JSON.stringify(value)).toBe(true)
  return value
}

async function seed(project) {
  const checkpoint = JSON.parse(await readFile(new URL('./data/world-design-checkpoint.json', import.meta.url), 'utf8'))
  checkpoint.world_state.project.id = project.id
  const saved = await api('/world/design-checkpoints', { novel_id: project.id, checkpoint })
  const session = await api('/world/cocreation-sessions', { novel_id: project.id, title: '持续潮门设计', source: { kind: 'project' }, workflow_preset: 'world_core', target_kind: 'core_entity' })
  await api(`/world/cocreation-sessions/${session.id}/checkpoint`, { novel_id: project.id, checkpoint_suggestion_id: saved.id, expected_checkpoint_id: null, round_no: 3, depth: 'seed' })
  return { saved, session }
}

async function openSession(page, project, session) {
  await openWorkbench(page, project, 'generate')
  await page.evaluate(({ projectId, sessionId }) => { location.hash = `#workbench/${projectId}/generate?preset=world_core&session_id=${sessionId}` }, { projectId: project.id, sessionId: session.id })
  await expect(page.getByRole('region', { name: '持续世界推演' })).toBeVisible()
}

for (const width of [390, 768, 1440]) {
  test(`世界模型局部编辑与父版本保护 ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 })
    const project = await createProject({ title: `模型续写验收 ${width}` })
    try {
      const { saved, session } = await seed(project)
      await openSession(page, project, session)
      const drawer = page.locator('[data-owner-ai-drawer]')
      for (const control of [
        drawer.getByRole('tab', { name: '设定共创', exact: true }),
        drawer.getByRole('button', { name: '收回 AI 工具', exact: true }),
      ]) {
        await expect.poll(() => control.evaluate(element => {
          const box = element.getBoundingClientRect()
          return [2, box.width / 2, box.width - 2].every(offset =>
            element.contains(document.elementFromPoint(box.left + offset, box.top + box.height / 2)))
        }), { message: 'AI 工具的标签和收回按钮不能被导航遮挡' }).toBe(true)
      }
      if (width === 768) {
        const screenshot = testInfo.outputPath('world-drawer-768.png')
        await page.screenshot({ path: screenshot })
        await testInfo.attach('world-drawer', { path: screenshot, contentType: 'image/png' })
      }
      const panel = page.getByRole('region', { name: '持续世界推演' })
      await panel.locator('summary').filter({ hasText: /^已保存的决定与世界资料$/ }).click()
      const rules = panel.locator('summary').filter({ hasText: /^规则与代价$/ })
      await rules.click()
      await rules.locator('..').getByRole('button', { name: '局部修改', exact: true }).click()
      await panel.getByLabel('本轮说明', { exact: true }).fill('明确每次耗盐三袋')
      await panel.getByLabel('代价（每行一项）', { exact: true }).fill('每次耗盐三袋')
      await panel.getByRole('button', { name: '保存本轮阶段成果', exact: true }).click()
      await expect(panel.getByRole('heading', { name: '本轮改变' })).toHaveCount(0)
      const detail = await api(`/world/cocreation-sessions/${session.id}?novel_id=${project.id}`)
      expect(detail.session.current_checkpoint_id).not.toBe(saved.id)
      const child = await api(`/world/adoption-packages/${detail.session.current_checkpoint_id}?novel_id=${project.id}`)
      const parent = await api(`/world/adoption-packages/${saved.id}?novel_id=${project.id}`)
      expect(child.payload_json.world_state.rules[0].costs).toEqual(['每次耗盐三袋'])
      expect(parent.payload_json.world_state.rules[0].costs).toEqual(['每次耗盐'])
      expect(child.payload_json.world_state.pressure_tests[0].status).toBe('not-run')
      expect(child.payload_json.decisions[0].disposition).toBe('rejected')
      await page.reload()
      await expect(panel).toContainText('不得复活死者')
      await expectNoPageOverflow(page)
      await panel.locator('summary').filter({ hasText: /^已保存的决定与世界资料$/ }).click()
      await panel.evaluate(element => element.scrollIntoView({ block: 'start', behavior: 'instant' }))
      const screenshot = testInfo.outputPath(`world-model-${width}.png`)
      await page.screenshot({ path: screenshot })
      await testInfo.attach('world-model', { path: screenshot, contentType: 'image/png' })
    } finally { await cleanupProject(project.id) }
  })
}

test('一千条历史可定位并明确选入参考', async ({ page }) => {
  test.setTimeout(180000)
  const project = await createProject({ title: '长历史验收' })
  try {
    const { session } = await seed(project)
    let firstId
    for (let index = 0; index < 1000; index++) {
      const item = await api(`/world/cocreation-sessions/${session.id}/messages`, { novel_id: project.id, content: `历史索引${String(index).padStart(4, '0')}：保留潮门维护成本` })
      if (index === 0) firstId = item.id
    }
    await openSession(page, project, session)
    await page.getByRole('button', { name: '历史会话', exact: true }).click()
    const history = page.getByRole('dialog', { name: '历史与决定' })
    await history.getByRole('button', { name: '当前会话的完整历史', exact: true }).click()
    await history.getByLabel('搜索历史内容', { exact: true }).fill('历史索引0000')
    await history.getByRole('button', { name: '搜索', exact: true }).click()
    await expect(history).toContainText('历史索引0000')
    await history.getByLabel('本轮参考', { exact: true }).check()
    await history.getByRole('button', { name: '查看前后文', exact: true }).click()
    await expect(history).toContainText('历史索引0001')
    const stored = await page.evaluate(sessionId => {
      const key = Object.keys(localStorage).find(key => key.startsWith('generate_world_workspace_state_v2_') && key.includes(sessionId))
      return key ? JSON.parse(localStorage.getItem(key)).selectedHistoryIds : []
    }, session.id)
    expect(stored).toContain(firstId)
  } finally { await cleanupProject(project.id) }
})
