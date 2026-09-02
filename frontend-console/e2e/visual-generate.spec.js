import { test, expect } from "./fixtures.js"
import { createDraft, createEntity, createScene, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench, openWritingAiDrawer } from "./helpers/workbench.js"

const THEMES = ["sticky", "night", "ink"]

async function applyTheme(page, theme) {
  await page.locator(`.theme-dot[data-theme-value="${theme}"]`).evaluate((element) => element.click())
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  const announcement = page.locator("#toast-container .toast")
  await expect(announcement).toBeVisible()
  await expect(announcement).toHaveCount(0, { timeout: 3000 })
}

async function screenshotPage(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
  await expect(page).toHaveScreenshot(name, {
    animations: "disabled",
    caret: "hide",
  })
}

async function openPovWorkbench(page, project) {
  await openWorkbench(page, project, "writing")
  await openWritingAiDrawer(page)
  await page.locator('[data-action="owner-writing-pov-workbench"]').click()
  await expect(page.locator("#generate-mode-panel-pov_prose")).toBeVisible({ timeout: 10000 })
}

test.describe("生成工具视觉基线", () => {
  test.skip(
    process.platform !== "darwin" && !process.env.VISUAL_BASELINE,
    "视觉基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线",
  )

  test.use({ viewport: { width: 1440, height: 900 } })

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.clear()
      sessionStorage.clear()
    })
    await page.goto("/")
  })

  test("任务上下文 × 三主题与手机", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线生成任务", genre: "fantasy", language: "zh" })
    await openWorkbench(page, project, "generate")
    await page.locator('[data-action="owner-task-context"]').click()
    await expect(page.locator("#gen-task")).toBeVisible({ timeout: 10000 })
    await page.locator("#gen-task").fill("核对第一幕的人物动机与世界规则是否冲突")

    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `generate-task-${theme}.png`)
    }

    await page.setViewportSize({ width: 375, height: 812 })
    await applyTheme(page, "night")
    await screenshotPage(page, "generate-task-mobile-night.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("AI 参考资料审阅 × 桌面与手机", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线参考资料", genre: "fantasy", language: "zh" })
    await page.route("**/api/evidence/compilation/compile", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          novel_id: body.novel_id,
          task: body.task,
          scope: body.scope,
          reveal_mode: body.reveal_mode,
          total_tokens: 3680,
          budget_tokens: 4000,
          sections: [
            { key: "writing_objective", tier: 0, token_count: 80, title: "本次任务", preview: body.task, status: "system", activation_reason: "你刚刚填写的创作目标", sources: [{ type: "task", id: "writing_objective", label: "本次任务", status: "system" }], can_exclude: false },
            { key: "scene_blueprint", tier: 0, token_count: 420, title: "当前场景", preview: "退潮后的石门：林舟需要判断是否把发现告诉同行者。", status: "canonical", activation_reason: "当前场景和章节范围", sources: [{ type: "scene", id: "scene-1", label: "退潮后的石门", status: "canonical" }], can_exclude: false },
            { key: "world_bible_synopsis", tier: 1, token_count: 860, title: "世界观简介", preview: "潮汐城市依靠潮门维持交通，维护配额决定各街区的通行时间。", status: "canonical", activation_reason: "本次任务启用了世界观简介", sources: [{ type: "world_bible_synopsis", id: "synopsis-1", label: "世界观简介", status: "canonical" }], can_exclude: true },
            { key: "retrieval_evidence_packs", tier: 2, token_count: 2320, title: "正文与导入资料", preview: "第一章与第二章中关于潮门刻痕、巡港人职责和夜间通行的相关片段。", status: "mixed", activation_reason: "与任务和当前场景相关", sources: [{ type: "chapter", id: "chapter-1", label: "第一章 潮门初启", status: "canonical" }, { type: "chapter", id: "chapter-2", label: "第二章 夜航", status: "working" }], can_exclude: true, truncated: true, truncated_reason: "超过本次资料长度后按条目裁剪" },
          ],
          evicted: ["style_assets"],
          truncated: ["retrieval_evidence_packs"],
          budget_events: [
            { section_key: "style_assets", event_type: "evicted", reason: "超过资料长度后先移除低优先级内容", before_tokens: 480, after_tokens: 0, tier: 3 },
            { section_key: "retrieval_evidence_packs", event_type: "truncated", reason: "超过资料长度后按条目裁剪", before_tokens: 2800, after_tokens: 2320, tier: 2 },
          ],
          warnings: ["部分早期正文未纳入本次整理。"],
        }),
      })
    })

    await openWorkbench(page, project, "generate")
    await page.locator('[data-action="owner-task-context"]').click()
    await page.locator("#gen-task").fill("核对第一幕的人物动机与潮门规则是否冲突")
    await page.getByRole("button", { name: "整理参考资料" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已准备 4 类参考资料", { timeout: 10000 })
    await page.locator(".generate-task-result").scrollIntoViewIfNeeded()
    await screenshotPage(page, "generate-context-review-desktop-sticky.png")

    await page.setViewportSize({ width: 390, height: 844 })
    await applyTheme(page, "night")
    await page.locator(".generate-task-result").scrollIntoViewIfNeeded()
    await screenshotPage(page, "generate-context-review-mobile-night.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("世界设定参考资料栏 × 桌面与手机", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线参考资料", genre: "fantasy", language: "zh" })
    await openWorkbench(page, project, "generate")
    const rail = page.locator(".generate-side-rail")
    await expect(rail).toHaveAttribute("open", "")
    await expect(rail).toContainText("本轮参考资料")
    await expect(page.locator("#generate-result")).toHaveCount(0)
    await screenshotPage(page, "generate-world-reference-desktop-sticky.png")

    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto("/")
    await page.evaluate((projectId) => sessionStorage.removeItem(`workspace-rail:${projectId}:generate:assistant`), project.id)
    await openWorkbench(page, project, "generate")
    await expect(rail).not.toHaveAttribute("open", "")
    await expect(rail.locator(":scope > summary")).toContainText("世界观简介 · 常规复核")
    await applyTheme(page, "night")
    await screenshotPage(page, "generate-world-reference-mobile-night.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("世界建议使用主栏审阅", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线建议审阅", genre: "fantasy", language: "zh" })
    let taskId = ""
    await page.route("**/api/world/generation-center/suggestions/task", async (route) => {
      taskId = route.request().postDataJSON().operation_id
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ task_id: taskId, status: "pending" }) })
    })
    await page.route("**/api/tasks/**", async (route) => {
      if (!taskId || route.request().method() !== "GET") return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "world_generation_suggestion",
          status: "done",
          progress: 1,
          result: {
            result: {
              kind: "core_entity",
              suggestion: {
                id: "visual-suggestion",
                target_type: "core_entity_draft",
                status: "pending",
                payload_json: { name: "夜潮通行制", entity_type: "rule", summary: "城民按潮窗轮换通行；配额失效时，普通人先承担绕行与断供代价。" },
              },
            },
          },
        }),
      })
    })

    await openWorkbench(page, project, "generate")
    await page.locator("#generate-chat-input").fill("把夜间交通规则收束成一条待审建议")
    await page.getByRole("button", { name: "生成世界对象建议" }).click()
    const result = page.locator("#generate-result")
    await expect(result).toContainText("夜潮通行制", { timeout: 10000 })
    await expect(result.locator(".generate-result-meta")).toHaveText("规则设定 · 待处理")
    await expect(page.locator(".generate-side-rail #generate-result")).toHaveCount(0)
    const resultBox = await result.boundingBox()
    const railBox = await page.locator(".generate-side-rail").boundingBox()
    expect(resultBox.width).toBeGreaterThan(railBox.width * 2)
    await screenshotPage(page, "generate-world-result-desktop-sticky.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("世界设定共创输入区 × 桌面、手机与矮窗口", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线世界共创", genre: "fantasy", language: "zh" })
    await openWorkbench(page, project, "generate")
    const composer = page.locator("#generate-chat-input")
    await expect(composer).toBeVisible({ timeout: 10000 })
    await composer.fill("推敲这座潮汐城市的夜间交通规则，以及规则失效时普通居民会付出的代价。")
    await composer.evaluate((element) => { element.style.height = "144px" })
    const send = page.locator('[data-action="send-chat-message"]')
    await send.evaluate((element) => element.scrollIntoView({ block: "center" }))
    await screenshotPage(page, "generate-world-composer-desktop-sticky.png")

    await page.setViewportSize({ width: 390, height: 844 })
    await applyTheme(page, "night")
    await send.evaluate((element) => element.scrollIntoView({ block: "center" }))
    await screenshotPage(page, "generate-world-composer-mobile-night.png")

    await page.setViewportSize({ width: 812, height: 375 })
    await applyTheme(page, "sticky")
    await send.evaluate((element) => element.scrollIntoView({ block: "center" }))
    await screenshotPage(page, "generate-world-composer-landscape-sticky.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("角色视角正文表单 × 桌面与手机", async ({ page, projectFactory, browserErrors }) => {
    const project = await projectFactory({ title: "视觉基线角色视角", genre: "fantasy", language: "zh" })
    const character = await createEntity(project.id, { name: "林舟", entity_type: "character", status: "canonical", summary: "谨慎的巡港人" })
    await createDraft(project.id, 1, "第一章 潮门初启", "潮声退到石阶之外，露出一道从未被记载的门。")
    await createScene(project.id, {
      scene_index: 0,
      title: "退潮后的石门",
      narrative_tag: "opening",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 24 }],
      goal: "判断是否公开石门",
      core_conflict: "保护同行者，还是抢先留下证据",
    })

    await openPovWorkbench(page, project)
    await page.locator("#generate-pov-chapter").selectOption("1")
    await expect(page.locator("#generate-pov-scene option")).toHaveCount(2)
    await page.locator("#generate-pov-scene").selectOption({ label: "退潮后的石门" })
    await page.locator("#generate-pov-character").selectOption(character.id)
    await page.locator("#generate-pov-instruction").fill("保持克制，让林舟先观察刻痕，再决定是否告诉同行者。")
    await screenshotPage(page, "generate-pov-form-desktop-sticky.png")

    await page.setViewportSize({ width: 390, height: 844 })
    await applyTheme(page, "night")
    await page.locator("#generate-pov-instruction").scrollIntoViewIfNeeded()
    await screenshotPage(page, "generate-pov-form-mobile-night.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })
})
