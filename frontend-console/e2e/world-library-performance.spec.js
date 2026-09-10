import os from 'node:os'
import { execFileSync } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { test, expect } from './fixtures.js'
import { createProject, cleanupProject, createWorldBiblePage, createWorldBibleDraft, createEntity } from './helpers/api-client.js'
import { openWorkbench } from './helpers/workbench.js'

const percentile = (values, p = 0.95) => [...values].sort((a, b) => a - b)[Math.ceil(values.length * p) - 1]

for (const count of [100, 1000]) {
  test(`长资料库性能 ${count} 份`, async ({ page }, testInfo) => {
    test.skip(process.env.RUN_WORLD_LIBRARY_PERF !== '1', 'Run explicitly on an isolated database')
    test.setTimeout(600000)
    const project = await createProject({ title: `长资料性能 ${count}` })
    const text = '潮门维持城市日常运输，维护者按时补充盐料并记录故障。'.repeat(600)
    let firstDraft
    try {
      for (let index = 0; index < count; index++) {
        const title = `规模资料${String(index).padStart(4, '0')}`
        if (index % 5 === 0) await createWorldBiblePage(project.id, { title, page_key: `perf-${index}`, page_type: 'background', status: 'canonical', free_text: text })
        else if (index % 5 === 4) await createEntity(project.id, { name: title, entity_type: 'location', status: 'canonical', summary: '城市中的长期创作地点' })
        else {
          const draft = await createWorldBibleDraft(project.id, { title, page_type: 'background', free_text: text })
          firstDraft ||= draft
        }
      }
      await openWorkbench(page, project, 'world', 'bible')
      const cdp = await page.context().newCDPSession(page)
      const cold = [], warm = [], search = [], input = [], bytes = [], requestCounts = []
      let pendingResponses = []
      const record = response => {
        if (!response.url().includes('/api/') || !response.ok()) return
        pendingResponses.push(response.body().then(body => ({ url: response.url(), size: body.byteLength, fullText: body.includes(Buffer.from(text)) })))
      }
      page.on('response', record)
      for (const [cacheDisabled, samples] of [[true, cold], [false, warm]]) {
        await cdp.send('Network.setCacheDisabled', { cacheDisabled })
        for (let round = 0; round < 20; round++) {
          pendingResponses = []
          const started = performance.now()
          await page.reload({ waitUntil: 'domcontentloaded' })
          await expect(page.locator('.world-library-home')).toBeVisible()
          samples.push(performance.now() - started)
          const responses = await Promise.all(pendingResponses)
          expect(responses.some(response => response.fullText)).toBe(false)
          expect(responses.some(response => /\/bible\/(pages|drafts)\?/.test(response.url))).toBe(false)
          bytes.push(responses.reduce((sum, response) => sum + response.size, 0))
          requestCounts.push(responses.length)
        }
      }
      page.off('response', record)
      for (let round = 0; round < 20; round++) {
        const needle = `规模资料${String(round).padStart(4, '0')}`
        const started = performance.now()
        await page.getByPlaceholder('名称、别名或内容').fill(needle)
        await page.getByPlaceholder('名称、别名或内容').press('Enter')
        await expect(page.locator('.world-library-list__copy strong, .world-bible-page-card__title h3').filter({ hasText: new RegExp(`^${needle}$`) })).toBeVisible()
        search.push(performance.now() - started)
      }
      await page.evaluate(({ projectId, draftId }) => { location.hash = `#workbench/${projectId}/world/bible?draft_id=${draftId}` }, { projectId: project.id, draftId: firstDraft.id })
      const editor = page.locator('#bible-free-text')
      await expect(editor).toBeVisible()
      await editor.focus()
      await editor.press('ControlOrMeta+End')
      for (let round = 0; round < 20; round++) {
        const started = await page.evaluate(() => performance.now())
        await page.keyboard.type('字')
        const painted = await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now())))))
        input.push(painted - started)
      }
      const report = { count, longDocumentCharacters: text.length, composition: { pages: count / 5, drafts: count * 3 / 5, entities: count / 5 },
        commit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), workingTree: true,
        host: { platform: os.platform(), arch: os.arch(), cpu: os.cpus()[0].model, memoryGB: Math.round(os.totalmem() / 1024 ** 3) }, browser: page.context().browser().version(),
        cold, warm, search, input, responseBytes: bytes, requestCounts,
        p95: { cold: percentile(cold), warm: percentile(warm), search: percentile(search), input: percentile(input) } }
      const metricsPath = testInfo.outputPath(`world-library-${count}-metrics.json`)
      await writeFile(metricsPath, JSON.stringify(report, null, 2))
      await testInfo.attach(`world-library-${count}-metrics`, { path: metricsPath, contentType: 'application/json' })
      console.log(`WORLD_LIBRARY_PERFORMANCE ${JSON.stringify({ count, p95: report.p95, maximumBytes: Math.max(...bytes), maximumRequests: Math.max(...requestCounts) })}`)
      expect(report.p95.cold).toBeLessThanOrEqual(2500)
      expect(report.p95.warm).toBeLessThanOrEqual(2500)
      expect(report.p95.search).toBeLessThanOrEqual(1000)
      expect(report.p95.input).toBeLessThanOrEqual(100)
    } finally { await cleanupProject(project.id) }
  })
}
