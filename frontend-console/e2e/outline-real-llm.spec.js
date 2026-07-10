import { test, expect } from "@playwright/test"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createDraft, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

/**
 * 真实 LLM 验收：使用《诡秘之主 第一部》第 1-3 章真实正文生成剧情结构。
 *
 * 该测试默认跳过，避免在 CI 中调用真实 LLM；本地验收时通过环境变量启用：
 *   ENABLE_REAL_LLM=1 npx playwright test outline-real-llm.spec.js
 */

const ENABLED = process.env.ENABLE_REAL_LLM === "1"

test.describe("Outline View — 真实 LLM 生成（诡秘之主 1-3 章）", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    if (!ENABLED) {
      test.skip(true, "未设置 ENABLE_REAL_LLM=1，跳过真实 LLM 验收")
    }
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "诡秘之主 第一部",
      genre: "西方奇幻",
      language: "zh",
    })
    testProjectId = project.id

    // 读取第 1-3 章样本并创建 writing_drafts
    const samplePath = join(process.cwd(), "..", "backend", "tests", "e2e", "samples", "lotm_chapters_1_2_3.txt")
    const raw = readFileSync(samplePath, "utf-8")
    const chapters = raw.split("\n\n---\n\n").map((c) => c.trim()).filter(Boolean)

    for (let i = 0; i < chapters.length; i++) {
      const content = chapters[i]
      const lines = content.split("\n")
      const title = lines[0].trim()
      await createDraft(testProjectId, i + 1, title, content)
    }

    await openWorkbench(page, project, "outline", "scenes")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("AI 生成结构使用第 1-3 章正文，检查建议后采用到剧情线/篇章纲列表", async ({ page }) => {
    // Given: Scene 子标签为空态
    await expect(page.locator(SEL.emptyState)).toContainText("暂无 Scene")

    // When: 点击 AI 生成结构（按钮在 Scene 子标签）
    await page.locator('[data-action="generate-structure"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 生成剧情结构")

    // 设置范围 1-3
    await page.locator("#generate-structure-start").fill("1")
    await page.locator("#generate-structure-end").fill("3")

    // 提交生成（真实 LLM，设置较长超时）
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情结构建议已生成", { timeout: 200000 })
    await page.locator('[data-action="view-outline-generate-preview"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("剧情结构建议预览")
    await page.getByRole("button", { name: "采用到工作结构" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情结构已采用", { timeout: 15000 })

    // Then: 切换到剧情线子标签，列表出现条目
    await page.locator('[data-action="nav-threads"]').click()
    const threadRows = page.locator('.data-table tbody tr')
    await expect(threadRows.first()).toBeVisible({ timeout: 10000 })
    const threadCount = await threadRows.count()
    expect(threadCount).toBeGreaterThan(0)

    // 切换到篇章纲子标签，确认有数据
    await page.locator('[data-action="nav-arcs"]').click()
    const arcRows = page.locator('.data-table tbody tr')
    await expect(arcRows.first()).toBeVisible({ timeout: 10000 })
    const arcCount = await arcRows.count()
    expect(arcCount).toBeGreaterThan(0)

    // 刷新页面后数据仍 persisted
    await page.reload()
    await page.waitForLoadState("networkidle")
    await expect(page.locator('.data-table tbody tr').first()).toBeVisible({ timeout: 10000 })

    // 记录验收数量到控制台（供人工核对）
    const finalThreads = await page.locator('.data-table tbody tr').count()
    console.log(`[REAL-LLM-ACCEPTANCE] threads=${finalThreads}, arcs=${arcCount}`)
  })
})
