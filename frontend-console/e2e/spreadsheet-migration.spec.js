/**
 * 表格迁移浏览器 e2e（ADR-0030）— 上传 → 映射 → 采用 → 徽标 → 撤销。
 * 需专用 PG 测试库（make spreadsheet-e2e 通道，PW_REUSE_EXISTING_SERVER=0）；
 * 上传真实 xlsx 夹具 backend/tests/fixtures/spreadsheets/sample_characters_relations_outline.xlsx
 * （openpyxl 生成，含 人物/关系/细纲 三表，test_real_xlsx_multi_sheet_parses_and_classifies 验收）。
 */
import { expect, test } from "./fixtures.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { openProjectView } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"

import { readFileSync } from "fs"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FIXTURE_XLSX = path.join(
  __dirname, "..", "..", "backend", "tests", "fixtures", "spreadsheets",
  "sample_characters_relations_outline.xlsx",
)

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

async function openImportSpreadsheetsTab(page) {
  // 导入区展开状态跨路由保留（session.importSectionOpen），仅收起时才点开
  const tab = page.locator('[data-action="import-tab-spreadsheets"]')
  const alreadyOpen = await tab
    .waitFor({ state: "visible", timeout: 3000 })
    .then(() => true)
    .catch(() => false)
  if (!alreadyOpen) {
    await page.locator('[data-action="toggle-import"]').click()
  }
  await tab.click()
  await expect(page.getByTestId("sm-panel")).toBeVisible()
}

test.describe("表格迁移", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({ title: "表格迁移 e2e", language: "zh" })
    testProjectId = project.id
    await openProjectView(page, project)
    await openImportSpreadsheetsTab(page)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("上传 xlsx 后完成映射、采用、出现表格迁移徽标并可撤销", async ({ page }) => {
    // 2. 上传真实夹具
    await page.setInputFiles('[data-testid="sm-file-input"]', [
      { name: "人物表.xlsx", mimeType: XLSX_MIME, buffer: readFileSync(FIXTURE_XLSX) },
    ])
    await page.getByRole("button", { name: "上传并识别表格" }).click()

    // 3. 核对映射（识别建议直接采用）
    await expect(page.getByTestId("sm-mapping")).toBeVisible()
    await page.getByRole("button", { name: "保存映射并生成预览" }).click()

    // 4. 跳过 AI → 预览确认
    await page.getByRole("button", { name: "跳过 AI，直接用规则导入" }).click()
    await page.locator('[data-action="sm-apply-confirm"]').check()
    await page.getByRole("button", { name: "确认采用" }).click()
    await expect(page.getByTestId("sm-done")).toBeVisible()
    await expect(page.getByTestId("sm-done")).toContainText("导入完成")

    // 5. 世界库出现「表格迁移」来源徽标
    await page.locator('[data-action="sm-goto-world"]').click()
    await expect(page.getByText("表格迁移").first()).toBeVisible({ timeout: 15000 })

    // 6. 回到项目页撤销本次迁移
    await page.evaluate(() => window.router.navigate("project"))
    await expect(page.locator('[data-action="toggle-import"]')).toBeVisible({ timeout: 10000 })
    await openImportSpreadsheetsTab(page)
    await page.locator('[data-action="sm-records-rollback"]').first().click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已撤销", { timeout: 15000 })
  })
})
