import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createProject,
  createWorldBiblePage,
  listWorldBibleDrafts,
  waitForBackend,
} from "./helpers/api-client.js"

const AUTOSAVE_STATUS = "#bible-autosave-status"

async function openPageInReader(page, projectId, pageId) {
  await page.evaluate(({ projectId: pid, pageId: ppid }) => {
    window.location.hash = `#workbench/${pid}/world/bible?page_id=${ppid}`
  }, { projectId, pageId })
  await expect(page.locator(".world-page-reader")).toBeVisible({ timeout: 10000 })
}

async function enterEditor(page) {
  await page.locator("[data-action='world-reader-edit']").click()
  await expect(page.locator("#bible-free-text")).toBeVisible()
}

async function waitForAutosave(page, status, timeout = 15000) {
  await expect(page.locator(AUTOSAVE_STATUS)).toHaveAttribute("data-autosave-status", status, { timeout })
}

async function draftForPage(projectId, pageId) {
  const drafts = await listWorldBibleDrafts(projectId)
  return (drafts.items || []).find((item) => item.page_id === pageId) || null
}

async function searchAndOpenRow(page, title) {
  await page.getByRole("search").getByRole("searchbox").fill(title)
  // 查找触发服务端统一列表请求；等响应渲染稳定后再点行，避免点击落在被替换的旧行上
  const listLoaded = page.waitForResponse((response) => (
    response.url().includes("/api/world/library") && response.status() === 200
  ))
  await page.getByRole("search").getByRole("button", { name: "查找", exact: true }).click()
  await listLoaded
  const row = page.locator(".world-library-list__row", { hasText: title })
  await expect(row).toHaveCount(1)
  await row.locator("[data-action='open-world-card']").click()
  await expect(page.locator(".world-page-reader")).toBeVisible({ timeout: 10000 })
}

test.describe("世界书可靠保存", () => {
  let testProject = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async () => {
    testProject = await createProject({
      title: "世界书可靠性 E2E 项目",
      genre: "fantasy",
      language: "zh",
    })
  })

  /** 先建资料再打开工作台：深链解析依赖已加载的 pages 列表。 */
  async function openBibleWorkbench(page) {
    await openWorkbench(page, testProject, "world", "bible")
    await page.evaluate(() => window.errorLog?.clear?.())
  }

  test.afterEach(async () => {
    if (testProject?.id) {
      try { await cleanupProject(testProject.id) } catch {}
      testProject = null
    }
  })

  test("双标签页编辑同一页：后保存方看到服务器变化并可选择采用", async ({ page }) => {
    test.setTimeout(90_000)
    const projectId = testProject.id
    const sourcePage = await createWorldBiblePage(projectId, {
      title: "沉钟港税则",
      page_type: "background",
      free_text: "原始税则正文。",
    })
    await openBibleWorkbench(page)

    // 标签页一：进入编辑并等待首次自动保存建立工作稿
    await searchAndOpenRow(page, "沉钟港税则")
    await enterEditor(page)
    await page.locator("#bible-free-text").fill("标签页一的第一段修改。")
    await waitForAutosave(page, "idle")
    expect((await draftForPage(projectId, sourcePage.id)).free_text).toBe("标签页一的第一段修改。")

    // 标签页二：同一上下文中的第二个标签页，基于同一工作稿继续编辑
    const tab2 = await page.context().newPage()
    await openWorkbench(tab2, testProject, "world", "bible")
    await openPageInReader(tab2, projectId, sourcePage.id)
    await enterEditor(tab2)
    await expect(tab2.locator("#bible-free-text")).toHaveValue("标签页一的第一段修改。")
    await tab2.locator("#bible-free-text").fill("标签页二的新版本。")
    await waitForAutosave(tab2, "idle")

    // 标签页一继续输入：基线已过期，自动保存返回 409 并弹出对照
    await page.locator("#bible-free-text").fill("标签页一冲突后的输入。")
    await expect(page.locator("#modal-title")).toHaveText("工作稿保存冲突", { timeout: 15000 })
    const dialog = page.locator("#modal-overlay")
    await expect(dialog.locator(".world-draft-conflict")).toContainText("标签页二的新版本。")
    await expect(dialog.locator(".world-draft-conflict")).toContainText("标签页一冲突后的输入。")
    await waitForAutosave(page, "conflict")

    // 采用服务器版本：表单回到服务器内容，基线重置后可继续自动保存
    await page.getByRole("button", { name: "采用服务器版本" }).click()
    await expect(page.locator("#modal-overlay")).toBeHidden()
    await expect(page.locator("#bible-free-text")).toHaveValue("标签页二的新版本。")
    await page.locator("#bible-free-text").fill("采用服务器版本后的继续编辑。")
    await waitForAutosave(page, "idle")
    expect((await draftForPage(projectId, sourcePage.id)).free_text).toBe("采用服务器版本后的继续编辑。")
    await tab2.close()
  })

  test("断网期间输入先落本机备份，恢复网络后刷新可还原并保存", async ({ page }) => {
    test.setTimeout(90_000)
    const projectId = testProject.id
    const sourcePage = await createWorldBiblePage(projectId, {
      title: "离线编辑页",
      page_type: "background",
      free_text: "在线时的正文。",
    })
    await openBibleWorkbench(page)

    await searchAndOpenRow(page, "离线编辑页")
    await enterEditor(page)

    // 模拟断网：拦截工作稿创建与更新
    const failedSaveAttempts = []
    page.on("requestfailed", (request) => {
      if (request.url().includes("/api/world/bible/drafts")) failedSaveAttempts.push(request.url())
    })
    await page.route(/\/api\/world\/bible\/drafts/, async (route) => {
      const method = route.request().method()
      if (method === "POST" || method === "PATCH") await route.abort("failed")
      else await route.continue()
    })
    await page.locator("#bible-free-text").fill("断网期间未保存的补充内容。")
    // 自动保存已尝试且失败（error 为瞬态，失败后 1 秒会重试）
    await expect.poll(() => failedSaveAttempts.length).toBeGreaterThan(0)
    const backupKey = `world_draft_backup_${projectId}_draft_${sourcePage.id}`
    await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), backupKey))
      .toContain("断网期间未保存的补充内容。")
    await expect(page.locator("#bible-free-text")).toHaveValue("断网期间未保存的补充内容。")

    // 恢复网络并刷新：深链默认阅读态，进入编辑时提供备份恢复
    await page.unroute(/\/api\/world\/bible\/drafts/)
    await page.reload()
    await openPageInReader(page, projectId, sourcePage.id)
    const restoreDialog = page.waitForEvent("dialog")
    await page.locator("[data-action='world-reader-edit']").click()
    const dialog = await restoreDialog
    expect(dialog.message()).toContain("未完成本机备份")
    await dialog.accept()
    await expect(page.locator("#bible-free-text")).toHaveValue("断网期间未保存的补充内容。")

    // 恢复的内容确认后自动保存到服务器工作稿
    await waitForAutosave(page, "idle")
    expect((await draftForPage(projectId, sourcePage.id)).free_text).toBe("断网期间未保存的补充内容。")
  })

  test("保存请求晚到时新输入不被覆盖，队列保存以最新内容为准", async ({ page }) => {
    test.setTimeout(90_000)
    const projectId = testProject.id
    const sourcePage = await createWorldBiblePage(projectId, {
      title: "晚到响应页",
      page_type: "background",
      free_text: "起点正文。",
    })
    await openBibleWorkbench(page)

    await searchAndOpenRow(page, "晚到响应页")
    await enterEditor(page)

    // 拖慢保存响应，模拟慢网络
    await page.route(/\/api\/world\/bible\/drafts\/.+/, async (route) => {
      if (route.request().method() !== "PATCH") return route.continue()
      await new Promise((resolve) => setTimeout(resolve, 2500))
      await route.continue()
    })

    await page.locator("#bible-free-text").fill("第一段输入，等待慢响应。")
    await waitForAutosave(page, "saving")
    // 响应未返回时继续输入：输入框立即呈现新内容，不被旧状态重置
    await page.locator("#bible-free-text").fill("第二段输入，覆盖第一段。")
    await expect(page.locator("#bible-free-text")).toHaveValue("第二段输入，覆盖第一段。")
    // 晚到响应不推进基线，排队保存携带最新内容
    await waitForAutosave(page, "idle", 20000)
    await expect(page.locator("#bible-free-text")).toHaveValue("第二段输入，覆盖第一段。")
    expect((await draftForPage(projectId, sourcePage.id)).free_text).toBe("第二段输入，覆盖第一段。")
  })

  test("中文输入跨越自动保存周期保持完整", async ({ page }) => {
    test.setTimeout(60_000)
    const projectId = testProject.id
    const sourcePage = await createWorldBiblePage(projectId, {
      title: "中文输入页",
      page_type: "background",
      free_text: "初始。",
    })
    await openBibleWorkbench(page)

    await searchAndOpenRow(page, "中文输入页")
    await enterEditor(page)

    const editor = page.locator("#bible-free-text")
    await editor.click()
    await editor.fill("")
    await editor.pressSequentially("北境的银币在冬季升值", { delay: 40 })
    await waitForAutosave(page, "idle")
    await expect(editor).toHaveValue("北境的银币在冬季升值")

    // 第二轮输入跨越自动保存触发点，中间不被重置
    await editor.pressSequentially("，商队改走海路。", { delay: 40 })
    await waitForAutosave(page, "idle")
    await expect(editor).toHaveValue("北境的银币在冬季升值，商队改走海路。")
    expect((await draftForPage(projectId, sourcePage.id)).free_text).toBe("北境的银币在冬季升值，商队改走海路。")
  })

  test("服务器保存与本机备份都失败时，离开保护仍然拦截", async ({ page }) => {
    test.setTimeout(60_000)
    await createWorldBiblePage(testProject.id, {
      title: "双失败保护页",
      page_type: "background",
      free_text: "初始正文。",
    })
    await openBibleWorkbench(page)

    await searchAndOpenRow(page, "双失败保护页")
    await enterEditor(page)

    // 保存请求失败 + 本机备份写入失败（如隐私模式 / 配额用尽）
    await page.route(/\/api\/world\/bible\/drafts/, async (route) => {
      const method = route.request().method()
      if (method === "POST" || method === "PATCH") await route.abort("failed")
      else await route.continue()
    })
    await page.evaluate(() => {
      localStorage.setItem = () => {
        throw new DOMException("QuotaExceededError", "QuotaExceededError")
      }
    })
    const failedSaveAttempts = []
    page.on("requestfailed", (request) => {
      if (request.url().includes("/api/world/bible/drafts")) failedSaveAttempts.push(request.url())
    })
    await page.locator("#bible-free-text").fill("双失败场景下的未保存输入。")
    await expect.poll(() => failedSaveAttempts.length).toBeGreaterThan(0)
    await expect(page.locator("#bible-free-text")).toHaveValue("双失败场景下的未保存输入。")

    // 离开当前页面前必须经过未保存确认；取消离开后输入仍在
    const leaveDialog = page.waitForEvent("dialog")
    const leaveClick = page.locator('.nav-item[data-view="today"]').click()
    const dialog = await leaveDialog
    expect(dialog.message()).toContain("未保存修改")
    await dialog.dismiss()
    await leaveClick
    await expect(page.locator("#bible-free-text")).toHaveValue("双失败场景下的未保存输入。")
    expect(page).toHaveURL(/world\/bible/)
  })

  test("同名资料从列表分别打开，各自渲染自己的内容", async ({ page }) => {
    test.setTimeout(60_000)
    const projectId = testProject.id
    await createWorldBiblePage(projectId, {
      title: "同名资料",
      page_type: "background",
      free_text: "第一份同名资料的内容。",
    })
    await createWorldBiblePage(projectId, {
      title: "同名资料",
      page_type: "species",
      free_text: "第二份同名资料的内容。",
    })
    await openBibleWorkbench(page)

    await page.getByRole("search").getByRole("searchbox").fill("同名资料")
    const listLoaded = page.waitForResponse((response) => (
      response.url().includes("/api/world/library") && response.status() === 200
    ))
    await page.getByRole("search").getByRole("button", { name: "查找", exact: true }).click()
    await listLoaded
    const rows = page.locator(".world-library-list__row", { hasText: "同名资料" })
    await expect(rows).toHaveCount(2)

    await rows.nth(0).locator("[data-action='open-world-card']").click()
    await expect(page.locator(".world-page-reader")).toBeVisible()
    const firstBody = await page.locator(".world-page-reader__markdown").first().textContent()
    expect(firstBody).toContain("同名资料的内容。")
    const firstIsPageOne = firstBody.includes("第一份")
    await page.locator("[data-action='world-reader-back']").click()

    await rows.nth(1).locator("[data-action='open-world-card']").click()
    await expect(page.locator(".world-page-reader")).toBeVisible()
    const otherText = firstIsPageOne ? "第二份同名资料的内容。" : "第一份同名资料的内容。"
    await expect(page.locator(".world-page-reader__markdown").first()).toContainText(otherText)
  })
})
