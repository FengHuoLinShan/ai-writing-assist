import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  waitForBackend,
  createDraft,
  createScene,
  createEntity,
  getLatestDraft,
  listConflictChecks,
} from "./helpers/api-client.js"

/**
 * 真实 LLM 验收：写作冲突检查完整链路。
 *
 * 默认跳过，避免 CI 或普通本地测试调用真实 LLM：
 *   ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
 */

const ENABLED = process.env.ENABLE_REAL_LLM === "1"
const TEST_CONTENT = [
  "雨夜里，主角在旧约门前拦住守门人。",
  "守门人提到银色通行符，却还没来得及交出它，主角杀死守门人。",
  "他转身就相信了一封没有署名的敌方祭司来信。",
  "他没有向旧盟友解释自己为什么违背昨日立下的誓约，只说这条路一定正确。",
].join("")

async function confirmPublishIfPrompted(page) {
  const continueButton = page.locator("#modal-footer").getByRole("button", { name: "继续设为正式正文" })
  try {
    await expect(continueButton).toBeVisible({ timeout: 5000 })
    await continueButton.click()
  } catch {}
}

test.describe("Writing Conflict Check — 真实 LLM 全流程", () => {
  let testProjectId = null
  let testSceneId = null

  test.beforeAll(async () => {
    if (!ENABLED) {
      test.skip(true, "未设置 ENABLE_REAL_LLM=1，跳过真实 LLM 写作冲突验收")
    }
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "真实 LLM 写作冲突验收",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await createDraft(testProjectId, 1, "第一章 旧约门", "旧稿")
    const character = await createEntity(testProjectId, {
      name: "沈砚",
      entity_type: "character",
      status: "canonical",
    })
    const scene = await createScene(testProjectId, {
      scene_index: 1,
      title: "旧约门交涉",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 1000 }],
      goal: "主角必须不杀守门人，并取得进入禁区的合法通行方式。",
      core_conflict: "守门人怀疑主角背弃旧盟友，拒绝放行。",
      must_happen: "守门人交出银色通行符；主角向旧盟友解释违背誓约的原因",
      must_not_happen: "主角杀死守门人",
      pov_character_id: character.id,
    })
    testSceneId = scene.id

    await openWorkbench(page, project, "writing")
    await waitWritingReady(page)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
      testSceneId = null
    }
  })

  test("规则检查、AI 软冲突、AI 建议、状态更新与发布快照归档", async ({ page }) => {
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 10000 })

    await page.locator("#writing-title-input").fill("第一章 旧约门")
    await page.locator("#writing-editor").fill(TEST_CONTENT)
    await page.locator('[data-action="writing-more-menu"]').click()
    await page.locator("#btn-conflict-check").click()
    const conflictOptions = page.getByRole("dialog", { name: "剧情设定冲突检查选项" })
    await expect(conflictOptions).toContainText("剧情设定冲突检查")
    await conflictOptions.getByRole("checkbox", { name: "包含待处理内容" }).check()
    await conflictOptions.getByRole("button", { name: "开始检查" }).click()

    let conflictDialog = page.getByRole("dialog", { name: "剧情设定冲突检查", exact: true })
    await expect(conflictDialog).toBeVisible({ timeout: 15000 })
    await expect(page.locator(".writing-conflict-item", { hasText: "禁止项出现在正文" })).toBeVisible()
    await expect(page.locator(".writing-conflict-item", { hasText: "必须发生项缺失" }).first()).toBeVisible()

    await page.getByRole("button", { name: "补充 AI 软冲突判断" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 参考资料", { timeout: 10000 })
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认使用" }).click()

    await expect.poll(async () => {
      const history = await listConflictChecks(testProjectId, {
        chapter_index: 1,
        scene_id: testSceneId,
        limit: 1,
      })
      return history.items?.[0]?.ai_review_status || "not_requested"
    }, { timeout: 240000 }).toMatch(/^(done|partial)$/)
    const reviewedHistory = await listConflictChecks(testProjectId, {
      chapter_index: 1,
      scene_id: testSceneId,
      limit: 1,
    })
    const reviewedCheck = reviewedHistory.items[0]
    expect(reviewedCheck.items.some((item) => item.is_ai_judgment)).toBe(true)

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()

    await page.getByRole("button", { name: "查看最近校验" }).click()
    conflictDialog = page.getByRole("dialog", { name: "剧情设定冲突检查", exact: true })
    await expect(conflictDialog).toBeVisible({ timeout: 10000 })
    const aiItems = page.locator(".writing-conflict-group--ai .writing-conflict-item")
    await expect(aiItems.first()).toBeVisible({ timeout: 240000 })
    const aiReviewText = await conflictDialog.textContent()
    expect(aiReviewText).not.toContain("AI 软冲突判断失败")
    expect(aiReviewText).not.toContain("状态：失败")

    await aiItems.first().getByRole("button", { name: "生成 AI 修复建议" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 参考资料", { timeout: 10000 })
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认使用" }).click()

    await expect.poll(async () => {
      const history = await listConflictChecks(testProjectId, {
        chapter_index: 1,
        scene_id: testSceneId,
        limit: 1,
      })
      const latest = history.items?.[0]
      const suggested = latest?.items?.find((item) => (
        item.is_ai_judgment &&
        item.suggestion_status === "done" &&
        item.ai_suggestion
      ))
      return suggested ? "done" : "pending"
    }, { timeout: 240000 }).toBe("done")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await page.getByRole("button", { name: "查看最近校验" }).click()

    const suggestion = page.locator(".writing-conflict-group--ai .writing-conflict-suggestion").first()
    await expect(suggestion).toBeVisible({ timeout: 240000 })
    const suggestionHtml = await suggestion.innerHTML()
    expect(suggestionHtml).not.toContain("<script")
    expect(suggestionHtml).not.toContain("onerror=")

    const suggestedAiItem = page.locator(".writing-conflict-group--ai .writing-conflict-item", {
      has: page.locator(".writing-conflict-suggestion"),
    }).first()
    await suggestedAiItem.getByRole("button", { name: "稍后" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("状态已更新", { timeout: 10000 })
    conflictDialog = page.getByRole("dialog", { name: "剧情设定冲突检查", exact: true })
    await conflictDialog.locator(".modal-footer").getByRole("button", { name: "关闭" }).click()

    await page.locator("#btn-publish").click()
    await expect(page.locator(SEL.modalOverlay)).toContainText("未处理的重要问题", { timeout: 10000 })
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 30000 })

    const latestDraft = await getLatestDraft(testProjectId, 1)
    const snapshot = latestDraft.conflict_check_snapshot_json
    expect(snapshot?.ai_review_status).toMatch(/^(done|partial)$/)
    expect(snapshot?.ai_judgment_count).toBeGreaterThan(0)
    expect(snapshot?.suggestion_count).toBeGreaterThan(0)
    expect(snapshot?.items.some((item) => (
      !item.is_ai_judgment && item.kind === "forbidden_present"
    ))).toBe(true)
    expect(snapshot?.items.some((item) => item.is_ai_judgment)).toBe(true)
    expect(snapshot?.items.some((item) => item.has_ai_suggestion)).toBe(true)

    console.log(
      `[REAL-LLM-WRITING-CONFLICT] check=${snapshot.check_id}, ` +
      `ai_items=${snapshot.ai_judgment_count}, suggestions=${snapshot.suggestion_count}`,
    )
  })
})
