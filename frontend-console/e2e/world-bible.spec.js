import { spawn } from "node:child_process"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { test, expect } from "./fixtures.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createProject,
  listWorldBibleDrafts,
  waitForBackend,
} from "./helpers/api-client.js"
import { SEL } from "./helpers/selectors.js"
import { expectNoPageOverflow, expectWithinViewportWidth } from "./helpers/responsive.js"

function isExpectedProjectionConflict(response) {
  return response.status() === 409
    && response.url().includes("/api/world/bible/pages/")
    && response.url().includes("/refresh-projection")
    && response.url().includes("force=false")
}

function isExpectedProjectionConflictConsole(text) {
  return text.includes("Failed to load resource")
    && text.includes("409")
    && text.includes("Conflict")
}

async function startWorker() {
  const here = dirname(fileURLToPath(import.meta.url))
  const backendDir = resolve(here, "../../backend")
  const worker = spawn("python", ["run_worker.py"], {
    cwd: backendDir,
    env: { ...process.env, APP_ENV: "test" },
    stdio: ["ignore", "pipe", "pipe"],
  })
  let output = ""
  worker.stdout.on("data", (chunk) => { output += chunk.toString() })
  worker.stderr.on("data", (chunk) => { output += chunk.toString() })
  await new Promise((resolve) => setTimeout(resolve, 1000))
  if (worker.exitCode !== null) {
    throw new Error(`Worker exited early:\n${output}`)
  }
  return { worker, getOutput: () => output }
}

async function expectProjectionDone(page, workerHandle) {
  try {
    await expect(page.locator(".world-bible-workspace")).toContainText("状态：done", { timeout: 15000 })
  } catch (err) {
    const workerOutput = workerHandle?.getOutput?.() || ""
    throw new Error(`${err.message}\n\nWorker output:\n${workerOutput || "(empty)"}`)
  }
}

async function expectNoAppErrors(page, label) {
  const appErrors = await page.evaluate(() => window.errorLog?.getAll?.() || [])
  expect(appErrors, `${label} 应用错误日志: ${JSON.stringify(appErrors)}`).toHaveLength(0)
}

async function stopWorker(worker) {
  if (!worker || worker.exitCode !== null) return
  worker.kill("SIGINT")
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 3000)
    worker.once("exit", () => {
      clearTimeout(timer)
      resolve()
    })
  })
  if (worker.exitCode === null) worker.kill("SIGKILL")
}

test.describe("世界书工作台", () => {
  let testProject = null
  let workerHandle = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
    workerHandle = await startWorker()
  })

  test.afterAll(async () => {
    await stopWorker(workerHandle?.worker)
  })

  test.beforeEach(async ({ page }) => {
    testProject = await createProject({
      title: "世界书 E2E 测试项目",
      genre: "fantasy",
      language: "zh",
    })
    await openWorkbench(page, testProject, "world", "bible")
    await page.evaluate(() => window.errorLog?.clear?.())
  })

  test.afterEach(async () => {
    if (testProject?.id) {
      try { await cleanupProject(testProject.id) } catch {}
      testProject = null
    }
  })

  test("页面创建、正文保存、投影刷新、审核弹窗和子视图切换都可用", async ({ page }) => {
    const failedResponses = []
    const consoleErrors = []

    page.on("response", (response) => {
      if (response.status() >= 400 && !isExpectedProjectionConflict(response)) {
        failedResponses.push({ url: response.url(), status: response.status() })
      }
    })
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const text = msg.text()
        if (!isExpectedProjectionConflictConsole(text)) consoleErrors.push(text)
      }
    })
    page.on("pageerror", (err) => consoleErrors.push(err.message))

    await expect(page.locator(".world-bible-workspace")).toBeVisible()
    await expect(page.locator(SEL.emptyState)).toContainText("创建一个世界书页面")

    await page.locator("[data-action='bible-manage-page-templates']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("页面模板")
    await page.locator("#bible-template-key").fill("e2e_trade_guide")
    await page.locator("#bible-template-name").fill("E2E 贸易模板")
    await page.locator("#bible-template-section-title").fill("货币与交换")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("页面模板已创建", { timeout: 10000 })

    await page.locator("[data-action='bible-new-page']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建世界书页面")
    await page.locator("#bible-create-title").fill("E2E 世界基本背景")
    await page.locator("#bible-create-type").selectOption("background")
    await page.locator("#bible-create-template").selectOption("e2e_trade_guide")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator("#bible-free-text")).toBeVisible()
    await expect(page.locator(".world-bible-workspace")).toContainText("E2E 世界基本背景")
    await expect(page.locator(".world-bible-section-editor")).toHaveCount(1)
    await expect(page.locator("[data-section-field='title']").first()).toHaveValue("货币与交换")

    const freeText = "E2E 世界书正文：种族、势力、历史事件和重要物品。"
    await page.locator("#bible-free-text").fill(freeText)
    await page.locator("[data-section-field='body_markdown']").first().fill("北境使用银币进行贸易。")
    await page.locator("[data-action='bible-section-add']").click()
    await expect(page.locator(".world-bible-section-editor")).toHaveCount(2)
    await page.locator("[data-section-field='title']").nth(1).fill("冬季商路")
    await page.locator("[data-section-field='body_markdown']").nth(1).fill("冬季商路关闭。")
    await page.locator("[data-action='bible-save-page']").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })
    await expect(page.locator("[data-action='bible-publish-page']")).toBeVisible()
    await page.locator("[data-action='bible-publish-page']").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 10000 })
    await expect(page.locator(".world-bible-editor-panel > .world-bible-panel__header .world-bible-page-meta")).toContainText("已采用")

    await page.locator("[data-action='bible-activation-new']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建 AI 参考规则")
    await page.locator("#bible-profile-key").fill("writing.e2e_trade")
    await page.locator("#bible-profile-name").fill("E2E 贸易规则")
    await page.locator("#bible-rule-positive").fill("北境")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("规则工作稿已保存", { timeout: 10000 })
    await page.locator("#bible-activation-task").fill("描写北境商队支付银币")
    await page.locator("[data-action='bible-activation-dry-run']").click()
    await expect(page.locator(".world-bible-activation-trace")).toContainText("命中")
    await expect(page.locator(".world-bible-activation-trace")).toContainText("E2E 世界基本背景")
    await page.locator("[data-action='bible-activation-publish']").click()
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("AI 参考规则已发布", { timeout: 10000 })
    await expect(page.locator(".world-bible-profile-summary")).toContainText("published")

    const displayModes = page.getByRole("group", { name: "世界书展示模式", exact: true })
    const editorMode = displayModes.locator("[data-mode='editor']")
    const galleryMode = displayModes.locator("[data-mode='gallery']")
    const filterMode = displayModes.locator("[data-mode='filter']")
    await expect(editorMode).toHaveAttribute("aria-pressed", "true")
    await expect(galleryMode).toHaveAttribute("aria-pressed", "false")
    await expect(filterMode).toHaveAttribute("aria-pressed", "false")
    await galleryMode.click()
    await expect(editorMode).toHaveAttribute("aria-pressed", "false")
    await expect(galleryMode).toHaveAttribute("aria-pressed", "true")
    await expect(filterMode).toHaveAttribute("aria-pressed", "false")
    await expect(page.locator(".world-bible-gallery")).toContainText("世界书图鉴")
    await page.locator("[data-action='bible-gallery-open'][data-category='background']").click()
    await expect(page.locator(".world-bible-page-card")).toContainText("E2E 世界基本背景")
    await page.locator(".world-bible-page-card", { hasText: "E2E 世界基本背景" })
      .locator("[data-action='bible-open-page-card']")
      .click()
    await expect(page.locator("#bible-free-text")).toHaveValue(freeText)

    await filterMode.click()
    await expect(editorMode).toHaveAttribute("aria-pressed", "false")
    await expect(galleryMode).toHaveAttribute("aria-pressed", "false")
    await expect(filterMode).toHaveAttribute("aria-pressed", "true")
    await expect(page.locator(".world-bible-filter")).toContainText("页面分类")
    const categoryGroup = page.getByRole("group", { name: "世界书页面分类", exact: true })
    const allCategory = categoryGroup.locator("[data-category='all']")
    const backgroundCategory = categoryGroup.locator("[data-category='background']")
    await expect(allCategory).toHaveAttribute("aria-pressed", "true")
    await expect(backgroundCategory).toHaveAttribute("aria-pressed", "false")
    await backgroundCategory.click()
    await expect(allCategory).toHaveAttribute("aria-pressed", "false")
    await expect(backgroundCategory).toHaveAttribute("aria-pressed", "true")
    await expect(page.locator(".world-bible-page-card")).toContainText("E2E 世界基本背景")
    await page.locator(".world-bible-page-card", { hasText: "E2E 世界基本背景" })
      .locator("[data-action='bible-open-page-card']")
      .click()
    await expect(page.locator("#bible-free-text")).toHaveValue(freeText)
    await expectNoAppErrors(page, "展示模式切换后")

    await page.locator("[data-action='bible-refresh-projection']").click()
    await expectProjectionDone(page, workerHandle)
    await expect(page.locator(".world-bible-workspace")).toContainText("进度 100%")
    await expectNoAppErrors(page, "首次刷新后")

    await page.locator("[data-action='bible-refresh-projection']").click()
    await expect(page.locator("[data-action='bible-force-refresh-projection']")).toBeVisible()
    await expectNoAppErrors(page, "409 恢复后")
    await page.locator("[data-action='bible-force-refresh-projection']").click()
    await expectProjectionDone(page, workerHandle)
    await expectNoAppErrors(page, "强制刷新后")

    await reloadWorkbench(page, "world", "bible")
    await expect(page.locator(".world-bible-workspace")).toContainText("E2E 世界基本背景")
    await expect(page.locator("#bible-free-text")).toHaveValue(freeText)
    await expect(page.locator("[data-section-field='body_markdown']").first()).toHaveValue("北境使用银币进行贸易。")
    await expect(page.locator("#bible-activation-profile option", { hasText: "E2E 贸易规则" })).toContainText("published")
    await expectNoAppErrors(page, "页面刷新恢复后")

    await page.locator("[data-action='bible-page-history']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("世界书页面版本")
    await expect(page.locator(SEL.modalBody)).toContainText("v1")
    await page.locator("[data-bible-page-restore='1']").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("恢复为工作稿")
    await expect(page.locator("[data-action='bible-publish-page']")).toBeVisible()
    await page.locator("[data-action='bible-discard-draft']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await expect(page.locator(SEL.modalBody)).toContainText("丢弃这个工作稿")
    await page.locator(SEL.modalFooter).locator(".btn-danger").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已丢弃")

    await page.locator("[data-action='bible-manage-categories']").click()
    await page.locator("#bible-category-key").fill("technology")
    await page.locator("#bible-category-name").fill("技术体系")
    await page.locator("#bible-category-icon").fill("技术")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("类别已创建")

    await page.locator("[data-action='bible-open-suggestions']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("创设建议")
    await expect(page.locator(SEL.modalBody)).toContainText("暂无待处理建议")
    await page.locator(SEL.modalClose).click()
    await expectNoAppErrors(page, "建议弹窗后")

    await page.locator("[data-action='bible-open-conflicts']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("冲突检查")
    await expect(page.locator(SEL.modalBody)).toContainText("暂无冲突检查项")
    await page.locator(SEL.modalClose).click()
    await expectNoAppErrors(page, "冲突弹窗后")

    await page.locator(SEL.subnavItem("objects")).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${testProject.id}/world/objects`))
    await expect(page.locator(".world-bible-workspace")).toHaveCount(0)
    await page.locator(SEL.subnavItem("bible")).click()
    await expect(page.locator(".world-bible-workspace")).toBeVisible()
    await expect(page.locator("#bible-free-text")).toHaveValue(freeText)
    await expectNoAppErrors(page, "子视图切换后")

    await expectNoAppErrors(page, "最终")
    expect(failedResponses, `失败请求: ${JSON.stringify(failedResponses)}`).toHaveLength(0)
    expect(consoleErrors, `控制台错误: ${JSON.stringify(consoleErrors)}`).toHaveLength(0)
  })

  test("390px 下世界书表单、操作区和 AI 转交入口保持可用", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "world", "bible")

    await page.locator("[data-action='bible-new-page']").click()
    await page.locator("#bible-create-title").fill("移动端世界书")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    const publishedPageResponse = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes("/api/world/bible/drafts/")
      && response.url().includes("/publish")
      && response.status() === 200
    ))
    await page.locator("[data-action='bible-publish-page']").click()
    const publishedPage = await (await publishedPageResponse).json()
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 10000 })
    const sourcePageId = publishedPage.id || null
    expect(sourcePageId).toBeTruthy()

    const header = page.locator(".world-bible-editor-panel > .world-bible-panel__header")
    const actions = header.locator(".world-bible-panel__actions")
    await header.scrollIntoViewIfNeeded()
    await expectWithinViewportWidth(header)
    await expect(page.getByLabel("页面概览")).toBeVisible()
    await page.locator("#bible-free-text").scrollIntoViewIfNeeded()
    await expectWithinViewportWidth(page.locator("#bible-free-text"))
    await expectNoPageOverflow(page)

    const responsiveStyles = await header.evaluate((element) => {
      const actionElement = element.querySelector(".world-bible-panel__actions")
      const button = actionElement?.querySelector("button")
      return {
        headerDirection: getComputedStyle(element).flexDirection,
        actionsDisplay: actionElement ? getComputedStyle(actionElement).display : "",
        actionColumns: actionElement ? getComputedStyle(actionElement).gridTemplateColumns.split(" ").length : 0,
        buttonMinHeight: button ? Number.parseFloat(getComputedStyle(button).minHeight) : 0,
      }
    })
    expect(responsiveStyles).toMatchObject({
      headerDirection: "column",
      actionsDisplay: "grid",
      actionColumns: 2,
    })
    expect(responsiveStyles.buttonMinHeight).toBeGreaterThanOrEqual(44)

    const aiHandoff = actions.locator("[data-action='bible-improve-with-ai']")
    await expect(aiHandoff).toBeVisible()
    await expect(aiHandoff).toHaveText("用 AI 完善此页")
    await page.locator("#bible-free-text").fill("移动端保存后转交的页面概览")
    await aiHandoff.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("保存后进入生成中心")
    await page.getByRole("button", { name: "保存并继续" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("工作稿已保存", { timeout: 10000 })
    await expect(page).toHaveURL(/\/generate\?/)
    await expect(page.locator("#generate-chat-input")).toBeVisible()
    const query = new URLSearchParams(page.url().split("?")[1] || "")
    expect(query.get("target")).toBe("world_bible_page")
    expect(query.get("source_page_id")).toBe(sourcePageId)
    const drafts = await listWorldBibleDrafts(testProject.id)
    expect(drafts.items).toEqual(expect.arrayContaining([
      expect.objectContaining({
        page_id: sourcePageId,
        free_text: "移动端保存后转交的页面概览",
      }),
    ]))
  })
})
