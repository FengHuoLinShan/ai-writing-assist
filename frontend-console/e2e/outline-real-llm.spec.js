import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createProject,
  createStoryOutlineRevision,
  waitForBackend,
} from "./helpers/api-client.js"

/**
 * P20 真实 LLM 验收占位。默认跳过；全部 Prompt 优化完成后统一启用并扩展三类 target：
 *   ENABLE_REAL_LLM=1 npx playwright test outline-real-llm.spec.js
 */

const ENABLED = process.env.ENABLE_REAL_LLM === "1"

test.describe("Outline P20 — 真实 LLM 当前层创作", () => {
  let project = null

  test.beforeAll(async () => {
    if (!ENABLED) test.skip(true, "真实 LLM 验收留待全部 Prompt 优化完成后统一执行")
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    project = await createProject({
      title: "群岛退潮纪",
      genre: "海洋奇幻",
      language: "zh",
    })
    await createStoryOutlineRevision(project.id, {
      base_revision_id: null,
      idempotency_key: `p20-real-${project.id}`,
      source: "manual",
      provenance: { actor: "author" },
      title: "群岛共同体",
      creative_core: {
        premise: "孤立群岛必须共同面对退潮遗迹。",
        tone_and_reader_promise: "克制的海洋奇幻与渐进真相。",
        story_engine: "每次退潮都带来资源、真相与新的共同代价。",
        ending_direction: "分权联盟取代单一王座。",
      },
      outline_markdown: "# 总体方向\n\n故事围绕共同承担秩序推进。",
      major_storylines: [],
      macro_movements: [],
      open_decisions: [],
    })
    await openWorkbench(page, project, "outline", "threads")
  })

  test.afterEach(async () => {
    if (project?.id) {
      try { await cleanupProject(project.id) } catch {}
      project = null
    }
  })

  test("创作 PlotThread preview 并明确采用", async ({ page }) => {
    await page.locator('[data-action="ai-create-plot-thread"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 创作剧情线")
    await page.locator("#outline-layer-instruction").fill(
      "基于当前总纲设计最必要的长期主线；已有方向足够时说明复用，不要为了输出而凑线程。",
    )
    await page.locator(SEL.modalFooter).getByRole("button", { name: "生成建议" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 参考资料")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认使用" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线建议生成任务已提交")
    await expect(page.locator(SEL.toastContainer)).toContainText(
      "剧情线建议已生成",
      { timeout: 240000 },
    )

    await page.locator('[data-action="view-outline-generate-preview"]').click()
    await expect(page.getByRole("heading", { name: "检查剧情线建议" })).toBeVisible()
    await expect(page.locator("#outline-layer-preview-json")).toHaveCount(0)
    await page.locator('[data-action="apply-outline-generate-preview"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线已采用")
    await expect(page.locator(SEL.dataTable).locator("tbody tr").first()).toBeVisible()
  })
})
