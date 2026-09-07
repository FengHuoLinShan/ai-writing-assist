import { fileURLToPath } from 'node:url'
import { zipSync, strToU8 } from 'fflate'
import { test, expect } from './fixtures.js'
import { API_BASE, createDraft } from './helpers/api-client.js'
import { openWorkbench, waitWritingReady } from './helpers/workbench.js'

const sample = fileURLToPath(new URL('../themes/quiet-library.nctheme.zip', import.meta.url))
const good = { schemaVersion: 1, id: 'test-theme', name: '测试外观', version: '1', variants: { light: {} } }
function archive(manifest, extras = {}) {
  return { name: 'test.nctheme.zip', mimeType: 'application/zip', buffer: Buffer.from(zipSync({ 'theme.json': strToU8(JSON.stringify(manifest)), ...extras })) }
}

test('主题完整资源在预览、应用、刷新、导出和删除后保持一致', async ({ page, browserErrors }, info) => {
  await page.goto('/#settings?section=appearance')
  await expect(page.getByRole('heading', { name: '让创作空间适合你' })).toBeVisible()
  const initial = await page.locator('html').getAttribute('data-theme-package')
  await page.getByLabel('导入主题包', { exact: true }).setInputFiles(sample)
  const preview = page.getByRole('dialog', { name: '预览「静阅 · 资源包示例」' })
  await expect(preview).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', initial)
  await preview.getByRole('button', { name: '深色', exact: true }).click()
  await expect(preview.getByRole('button', { name: '继续写作', exact: true })).toHaveCSS('background-color', 'rgb(237, 237, 242)')
  await expect(preview.getByRole('button', { name: '查看资料', exact: true })).toHaveCSS('background-color', 'rgb(30, 30, 34)')
  await page.screenshot({ path: info.outputPath('theme-resource-preview.png') })
  await page.keyboard.press('Escape')
  await expect(preview).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', initial)
  await page.getByLabel('导入主题包', { exact: true }).setInputFiles(sample)
  await expect(preview).toBeVisible()
  await preview.getByRole('button', { name: '导入并应用' }).click()
  await expect(preview).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await expect.poll(() => page.evaluate(() => [...document.fonts].some(font => font.family.includes('quiet-library') && font.status === 'loaded'))).toBe(true)
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--theme-texture'))).toContain('blob:')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await page.getByRole('radio', { name: '深色', exact: true }).check()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.screenshot({ path: info.outputPath('appearance-dark.png') })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('quiet-library.nctheme.zip')
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '删除主题 静阅 · 资源包示例' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'modern')
  expect(browserErrors).toEqual([])
})

test('拒绝不安全主题和解压超限包且不改变当前外观', async ({ page, browserErrors }) => {
  await page.goto('/#settings?section=appearance')
  const input = page.getByLabel('导入主题包', { exact: true })
  const cases = [
    archive({ ...good, css: 'body{display:none}' }),
    archive({ ...good, schemaVersion: 999 }),
    archive({ ...good, variants: { light: { colors: { text: '#FFFFFF' } } } }),
    archive(good, { 'assets/../../evil.js': strToU8('alert(1)') }),
    archive({ ...good, assets: { huge: { kind: 'font', path: 'assets/huge.woff2' } } }, { 'assets/huge.woff2': new Uint8Array(25 * 1024 ** 2) }),
  ]
  for (const file of cases) {
    await input.setInputFiles(file)
    await expect(page.locator('.appearance-settings [role=alert]')).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'modern')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  expect(browserErrors).toEqual([])
})

test('预览缺省资源使用内置外观，不继承现用主题的字体与图片', async ({ page }) => {
  await page.goto('/#settings?section=appearance')
  const input = page.getByLabel('导入主题包', { exact: true })
  await input.setInputFiles(sample)
  await page.getByRole('button', { name: '导入并应用' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await input.setInputFiles(archive(good))
  const preview = page.locator('.theme-preview')
  await expect(preview).toBeVisible()
  await expect(preview).toHaveCSS('background-image', 'none')
  await expect(preview.locator('main')).toHaveCSS('background-image', 'none')
  await expect(preview.locator('.theme-preview__empty')).toHaveCSS('background-image', 'none')
  await expect(preview.locator('.theme-preview__prose')).not.toHaveCSS('font-family', /nc-quiet-library/)
  await page.keyboard.press('Escape')
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--theme-texture'))).toContain('blob:')
})

test('手机资料抽屉和主题切换不重建正文；写作内容可保存恢复', async ({ page, projectFactory, browserErrors }, info) => {
  const project = await projectFactory({ title: '现代写作验收' })
  await createDraft(project.id, 1, '第一章 潮门', '风从海边吹来，新的故事即将开始。')
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, 'writing')
  await waitWritingReady(page)
  await page.getByRole('button', { name: '章节', exact: true }).click()
  await page.getByRole('button', { name: /^打开第 1 章/ }).click()
  await waitWritingReady(page, { editor: true })
  const editor = page.getByLabel('章节正文', { exact: true })
  await editor.fill('写到一半的内容必须保留。')
  const identity = await editor.elementHandle()
  await page.getByRole('button', { name: '本章资料', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '本章资料' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '本章资料', exact: true })).toBeFocused()
  await page.getByRole('radio', { name: '切换到深色', exact: true }).click()
  expect(await identity.evaluate(node => node === document.querySelector('#writing-editor'))).toBe(true)
  await expect(editor).toHaveValue('写到一半的内容必须保留。')
  await page.locator('[aria-controls=writing-save-tools]').click()
  await page.getByRole('button', { name: '保存工作稿', exact: true }).click()
  await expect(page.locator('#writing-save-status')).toHaveText('已保存到工作稿')
  await page.screenshot({ path: info.outputPath('writing-mobile-dark.png') })
  await page.reload()
  await expect(editor).toHaveValue('写到一半的内容必须保留。')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(browserErrors).toEqual([])
})

test('本地存储失败不会声称主题已保存，预览与现用外观仍保留', async ({ page }) => {
  await page.goto('/#settings?section=appearance')
  await page.getByLabel('导入主题包', { exact: true }).setInputFiles(sample)
  const preview = page.getByRole('dialog', { name: '预览「静阅 · 资源包示例」' })
  await expect(preview).toBeVisible()
  await page.evaluate(() => {
    IDBObjectStore.prototype.put = () => { throw new DOMException('quota', 'QuotaExceededError') }
  })
  await preview.getByRole('button', { name: '导入并应用' }).click()
  await expect(preview.getByRole('alert')).toContainText('主题未能保存到此浏览器')
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'modern')
  await expect(page.locator('#toast-container')).not.toContainText('已导入')
  await page.keyboard.press('Escape')
  await expect(preview).toHaveCount(0)
})

test('无法持久化外观选择时明确提示本次会话有效', async ({ page }) => {
  await page.goto('/#settings?section=appearance')
  await expect(page.getByRole('heading', { name: '让创作空间适合你' })).toBeVisible()
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith('nc-theme')) throw new DOMException('quota', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  await page.getByRole('radio', { name: '深色', exact: true }).check()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('#toast-container')).toContainText('本次会话有效')
})

test('导入字体用于默认正文，作者显式字体选择优先', async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: '主题字体验收' })
  const preferences = await page.request.put(`${API_BASE}/projects/${project.id}/author-preferences`, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, data: { editor_font: 'system' } })
  expect(preferences.ok()).toBe(true)
  await createDraft(project.id, 1, '第一章', '故事从这里继续。')
  await page.goto('/#settings?section=appearance')
  await page.getByLabel('导入主题包', { exact: true }).setInputFiles(sample)
  await page.getByRole('button', { name: '导入并应用' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'quiet-library')
  await openWorkbench(page, project, 'writing')
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole('button', { name: /^打开第 1 章/ }).click()
  await expect(page.locator('#writing-editor')).toHaveCSS('font-family', /nc-quiet-library/)
  await page.getByLabel('切换正文字体').click()
  await expect(page.locator('#writing-editor')).toHaveCSS('font-family', /Georgia/)
})

test('启动时主题资源缺失会明确提示回退', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('nc-theme-package', 'missing-theme'))
  await page.goto('/')
  await expect(page.locator('.entry-choice')).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme-package', 'modern')
  await expect(page.locator('#toast-container')).toContainText('已恢复现代简约')
})
