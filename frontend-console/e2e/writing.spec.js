import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"
import {
  API_BASE,
  waitForBackend,
  createAutosavedDraft, createDraft, createScene, deleteDraft, getLatestDraft,
} from "./helpers/api-client.js"

async function confirmPublishIfPrompted(page) {
  const continueButton = page.locator("#modal-footer").getByRole("button", { name: "继续设为正式正文" })
  try {
    await expect(continueButton).toBeVisible({ timeout: 3000 })
    await continueButton.click()
  } catch {}
}

function writingChapter(page, chapter) {
  return page.getByRole("button", { name: new RegExp(`^打开第 ${Number(chapter)} 章`) })
}

async function selectWritingChapter(page, chapter) {
  const rail = page.locator(".writing-tree-rail")
  if (await rail.count() && await rail.evaluate((element) => element.classList.contains("is-collapsed"))) {
    await page.getByLabel("展开章节").click()
  }
  await writingChapter(page, chapter).click()
}

async function createFirstChapter(page) {
  await page.getByRole("button", { name: "创建第一章", exact: true }).click()
  await waitWritingReady(page, { editor: true })
}

async function openWritingToolMenu(page, selector) {
  const tool = page.locator(selector)
  const menu = page.locator("details.writing-tools-menu").filter({ has: tool })
  if (await menu.getAttribute("open") === null) {
    await menu.locator(":scope > summary").click()
  }
}

async function clickWritingTool(page, selector) {
  await openWritingToolMenu(page, selector)
  await page.locator(selector).click()
}

test.describe("写作台模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({
      title: "写作测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectWorkbench(project, "writing")
    await waitWritingReady(page)
  })

  // ============================================================
  // 基础功能
  // ============================================================

  test("空状态显示新建章节按钮", async ({ page }) => {
    const emptyTree = page.locator("#writing-tree-container .empty-state")
    await expect(emptyTree).toBeVisible()
    await expect(emptyTree).toContainText("尚无章节")
    await expect(page.getByRole("button", { name: "新建章节" })).toBeVisible()
  })

  test("新建章节并显示在章节树", async ({ page }) => {
    await createFirstChapter(page)

    await expect(page.locator("#workspace-content")).toContainText("第 1 章")
    await expect(page.locator("#writing-editor")).toBeVisible()
  })

  test("编辑章节内容并暂存", async ({ page }) => {
    await createFirstChapter(page)

    await page.locator("#writing-editor").fill("初始发布内容。")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })

    await page.locator("#writing-title-input").fill("第一章 测试")
    await page.locator("#writing-editor").fill("这是测试内容。")

    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 10000 })
  })

  test("发布章节", async ({ page }) => {
    await createFirstChapter(page)

    await page.locator("#writing-title-input").fill("第一章 发布测试")
    await page.locator("#writing-editor").fill("这是发布测试的内容。")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })
  })

  // ============================================================
  // Scene 切换不丢失内容
  // ============================================================

  test("Scene 切换不丢失内容", async ({ page }) => {
    // 创建后端草稿
    const d1 = await createDraft(testProjectId, 1, "第一章", "第一章的正文内容ABC")
    const d2 = await createDraft(testProjectId, 2, "第二章", "第二章的正文内容XYZ")

    const d1Content = d1.draft.content
    const d2Content = d2.draft.content
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)

    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })

    // 切换到第 2 章
    await selectWritingChapter(page, 2)
    await expect(page.locator("#writing-editor")).toHaveValue(d2Content, { timeout: 5000 })

    // 编辑第 2 章后切换回第 1 章
    await page.locator("#writing-editor").fill("修改后的第二章内容")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 10000 })

    // 恢复第 1 章内容
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })
  })

  // ============================================================
  // 版本历史查看与恢复
  // ============================================================

  test("版本历史查看与恢复", async ({ page }) => {
    // 创建 v1 和 v2
    const v1 = await createDraft(testProjectId, 1, "第一版", "版本一的正文内容")
    const v2 = await createDraft(testProjectId, 1, "第二版", "版本二的正文内容")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue(v2.draft.content)

    // 打开版本历史弹窗
    await page.getByRole("button", { name: "历史", exact: true }).click()
    const versionDialog = page.getByRole("dialog", { name: "版本历史" })
    await expect(versionDialog).toBeVisible({ timeout: 5000 })
    await expect(versionDialog).toContainText("v2")
    await expect(versionDialog).toContainText("v1")
    const writingOverlay = versionDialog.locator("xpath=..")

    // 预览 v1（最后一个预览按钮对应 v1）
    await versionDialog.getByRole("button", { name: "预览" }).last().click()
    await expect(page.locator("#writing-editor")).toHaveValue("版本一的正文内容", { timeout: 5000 })
    // v1 非最新版本 → 只读模式，显示"基于此版本创建"
    const v1Row = versionDialog.locator(".writing-version-history-item", { hasText: "v1" })
    await expect(v1Row.getByRole("button", { name: "基于此版本创建" })).toBeVisible()

    // 点击"基于此版本创建"
    await v1Row.getByRole("button", { name: "基于此版本创建" }).click()
    const globalConfirmation = page.locator("#modal-overlay")
    await expect(globalConfirmation).toBeVisible()
    await expect(writingOverlay).toHaveAttribute("inert", "")
    await expect(globalConfirmation).not.toHaveAttribute("inert")
    await expect(page.locator("#modal-content")).toContainText("恢复至 v1")
    await expect(page.locator("#modal-footer").getByRole("button", { name: "确认恢复" })).toBeFocused()
    await page.locator("#modal-footer").getByRole("button", { name: "取消" }).click()
    await expect(globalConfirmation).toBeHidden()
    await expect(versionDialog).toBeVisible()
    await expect(v1Row.getByRole("button", { name: "基于此版本创建" })).toBeFocused()

    await v1Row.getByRole("button", { name: "基于此版本创建" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "确认恢复" }).click()
    await expect(page.locator("#btn-autosave")).toHaveText("保存为新工作稿")

    // 编辑后保存 — 由于 restore 模式，autosave 走发布流程
    await page.locator("#writing-editor").fill("基于 v1 的新内容")
    await clickWritingTool(page, "#btn-autosave")
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })
  })

  test("实质变化留版、强制 checkpoint 和发布前撤销", async ({ page }) => {
    const v1 = await createDraft(testProjectId, 1, "第一章", "甲\n乙")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("甲\n乙")

    // 纯空白修改只留本地，用户可显式强制留版。
    await page.locator("#writing-editor").fill(" 　甲\t\n\n乙 ")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("排版修改已保留在本地")
    await clickWritingTool(page, "#btn-checkpoint-version")
    await expect(page.locator("#modal-overlay")).toContainText("正文没有实质变化")
    await page.locator("#modal-footer").getByRole("button", { name: "保存新版本" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    await expect(page.locator("#version-selector")).toContainText("v2")

    // 手动版本需显式确认放弃，回到 v1。
    await page.getByRole("button", { name: "放弃未设为正式正文的更改" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "放弃更改" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已回到上一版")
    await expect(page.locator("#writing-editor")).toHaveValue(v1.draft.content)

    // 实质修改自动创建工作版，撤销回基线时自动回到 v1。
    await page.locator("#writing-editor").fill("甲乙丙")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await page.locator("#writing-editor").fill("甲\n乙")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText("v1")

    // 再次修改后发布，当前工作版原位提升，不多加一版。
    await page.locator("#writing-editor").fill("甲乙丁")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).not.toContainText("v1")
    const workingVersion = await page.locator("#version-selector option").first().getAttribute("data-version")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(String(history.versions[0].version_number)).toBe(workingVersion)
    expect(history.versions[0].status).toBe("published")
  })

  test("自动保存响应不会覆盖请求期间的新输入", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "原文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)

    let autosaveRequests = 0
    let releaseFirstAutosave
    const firstAutosaveGate = new Promise((resolve) => { releaseFirstAutosave = resolve })
    await page.route("**/api/writing/drafts/**", async (route) => {
      if (route.request().method() !== "PUT") {
        await route.continue()
        return
      }
      autosaveRequests += 1
      if (autosaveRequests === 1) {
        await firstAutosaveGate
      }
      await route.continue()
    })

    await page.locator("#writing-editor").fill("第一次修改")
    await clickWritingTool(page, "#btn-autosave")
    await expect.poll(() => autosaveRequests).toBe(1)
    await page.locator("#writing-editor").fill("第二次修改")
    releaseFirstAutosave()
    await expect(page.locator("#btn-autosave")).toBeEnabled({ timeout: 15000 })
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 15000 })

    await expect(page.locator("#writing-editor")).toHaveValue("第二次修改")
    await expect.poll(async () => {
      const historyResponse = await page.request.get(
        `${API_BASE}/writing/chapters/1/versions?novel_id=${testProjectId}`,
      )
      const history = await historyResponse.json()
      const latestId = history.versions?.[0]?.id
      if (!latestId) return null
      const draftResponse = await page.request.get(
        `${API_BASE}/writing/drafts/${latestId}?novel_id=${testProjectId}`,
      )
      return (await draftResponse.json()).content
    }).toBe("第二次修改")
    await page.unrouteAll({ behavior: "wait" })
  })

  test("auto 回退到手动基线时原位发布手动版本", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "v1")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await page.locator("#writing-editor").fill("v2")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText("v2")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await clickWritingTool(page, "#btn-checkpoint-version")
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    const manualVersion = await page.locator("#version-selector option").first().getAttribute("data-version")

    await page.locator("#writing-editor").fill("v3")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText(
      `v${Number(manualVersion) + 1}`,
    )
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await page.locator("#writing-editor").fill("v2")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    const latestActive = history.versions.find((item) => item.display_state === "active")
    expect(String(latestActive.version_number)).toBe(manualVersion)
    expect(latestActive.status).toBe("published")
    const discardedAuto = history.versions.find(
      (item) => item.version_number === Number(manualVersion) + 1,
    )
    expect(discardedAuto).toMatchObject({
      display_state: "archived",
      status: "deprecated",
    })
  })

  test("历史恢复在最新版本变化后返回并发冲突", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "v1")
    await createDraft(testProjectId, 1, "第一章", "v2")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await page.getByRole("button", { name: "历史", exact: true }).click()
    await page.locator(".writing-version-history-item", { hasText: "v1" })
      .getByRole("button", { name: "基于此版本创建" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "确认恢复" }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("v1")

    const newest = await createDraft(testProjectId, 1, "第一章", "v3")
    await page.locator("#writing-editor").fill("基于 v1 恢复")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("其他会话更新")

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(history.versions[0].id).toBe(newest.draft.id)
  })

  // ============================================================
  // 光标位置联动右侧 Scene 卡面板
  // ============================================================

  test("光标位置联动右侧 Scene 卡面板", async ({ page }) => {
    // 创建一个 10 字符的章节，并用 scene_chunks 分成两个 Scene
    await createDraft(testProjectId, 1, "ch1", "ABCDEFGHIJ")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "Scene A",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 5 }],
    })
    await createScene(testProjectId, {
      scene_index: 1,
      title: "Scene B",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 5, end_pos: 10 }],
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)

    // 展开 Scene 节点并选中第 1 章
    await page.locator(".scene-tree-label").first().click()
    await expect(page.locator("#writing-editor")).toHaveValue("ABCDEFGHIJ", { timeout: 5000 })

    // 光标落在第一个 chunk → 显示 Scene A
    await page.locator("#writing-editor").focus()
    await page.evaluate(() => {
      const editor = document.getElementById("writing-editor")
      editor.setSelectionRange(2, 2)
      document.dispatchEvent(new Event("selectionchange"))
    })
    await expect(page.locator("#writing-panel-container")).toContainText("Scene A")

    // 光标落在第二个 chunk → 显示 Scene B
    await page.evaluate(() => {
      const editor = document.getElementById("writing-editor")
      editor.setSelectionRange(7, 7)
      document.dispatchEvent(new Event("selectionchange"))
    })
    await expect(page.locator("#writing-panel-container")).toContainText("Scene B")
  })

  test("写作副驾驶默认展示 Scene 执行信息且不被工作区裁切", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 东门交锋", "东门交锋正文")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "东门交锋",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 8 }],
      goal: "拿到令牌后安全离开",
      must_happen: "主角与守卫正面对质",
      must_not_happen: "主角身份提前暴露",
      core_conflict: "通行时限与身份隐藏之间的冲突",
      emotional_beat: "从紧张试探到果断突围",
    })

    await page.setViewportSize({ width: 1280, height: 768 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.locator(".scene-tree-label").first().click()

    await expect(page.getByRole("tab", { name: "设定" })).toHaveClass(/active/)
    await expect(page.locator('.cockpit-panel[data-panel="lore"]')).toContainText("拿到令牌后安全离开")

    const geometry = await page.evaluate(() => {
      const cockpit = document.querySelector(".scene-cockpit")
      const workspace = document.querySelector("#workspace-content")
      if (!cockpit || !workspace) return null
      const cockpitBox = cockpit.getBoundingClientRect()
      const workspaceBox = workspace.getBoundingClientRect()
      return {
        cockpitBottom: cockpitBox.bottom,
        workspaceBottom: workspaceBox.bottom,
      }
    })
    expect(geometry).not.toBeNull()
    expect(geometry.cockpitBottom).toBeLessThanOrEqual(geometry.workspaceBottom + 2)

    await page.getByRole("tab", { name: "地图" }).click()
    await expect(page.getByRole("tab", { name: "地图" })).toHaveClass(/active/)
  })

  test("专注模式隐藏两侧面板后保持桌面阅读宽度", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 专注写作", "用于验证专注模式宽度的正文。")
    await page.setViewportSize({ width: 1280, height: 800 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await selectWritingChapter(page, 1)
    await openWritingToolMenu(page, "#btn-conflict-check")
    await page.getByRole("button", { name: "专注模式" }).click()

    await expect(page.locator("body")).toHaveClass(/focus-mode-active/)
    await expect(page.locator("#writing-tree-container")).toBeHidden()
    await expect(page.locator("#writing-panel-container")).toBeHidden()

    const geometry = await page.evaluate(() => {
      const workspace = document.querySelector("#workspace-content")
      const layout = document.querySelector(".writing-workspace-layout")
      const editorContainer = document.querySelector("#writing-editor-container")
      const editor = document.querySelector("#writing-editor")
      if (!workspace || !layout || !editorContainer || !editor) return null
      const workspaceBox = workspace.getBoundingClientRect()
      const layoutBox = layout.getBoundingClientRect()
      const containerBox = editorContainer.getBoundingClientRect()
      const editorBox = editor.getBoundingClientRect()
      return {
        workspaceWidth: workspaceBox.width,
        layoutWidth: layoutBox.width,
        containerWidth: containerBox.width,
        editorWidth: editorBox.width,
        editorCenterOffset: Math.abs(
          (editorBox.left + editorBox.width / 2) -
          (workspaceBox.left + workspaceBox.width / 2),
        ),
      }
    })

    expect(geometry).not.toBeNull()
    expect(geometry.containerWidth).toBeGreaterThan(geometry.workspaceWidth * 0.8)
    expect(geometry.editorWidth).toBeGreaterThanOrEqual(700)
    expect(geometry.editorCenterOffset).toBeLessThanOrEqual(2)
  })

  test("桌面内容优先布局让正文占主要宽度且辅助栏可独立收起", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 内容优先", "用于验证工作台分栏比例的正文。")
    await page.setViewportSize({ width: 1280, height: 800 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await writingChapter(page, 1).click()

    const before = await page.evaluate(() => {
      const layout = document.querySelector(".writing-workspace-layout")
      const editor = document.querySelector("#writing-editor-container")
      const left = document.querySelector(".writing-tree-rail")
      const right = document.querySelector(".writing-panel-rail")
      if (!layout || !editor || !left || !right) return null
      const contentWidth = editor.getBoundingClientRect().width
        + left.getBoundingClientRect().width
        + right.getBoundingClientRect().width
      return {
        editorWidth: editor.getBoundingClientRect().width,
        contentWidth,
      }
    })

    expect(before).not.toBeNull()
    expect(before.editorWidth / before.contentWidth).toBeGreaterThanOrEqual(0.62)

    await page.getByLabel("收起写作副驾驶").click()
    await expect(page.locator(".writing-panel-rail")).toHaveClass(/is-collapsed/)
    const collapsedWidth = await page.locator("#writing-editor-container").evaluate((node) => node.getBoundingClientRect().width)
    expect(collapsedWidth).toBeGreaterThan(before.editorWidth)
  })

  test("剧情设定冲突检查流程、状态更新和发布快照归档", async ({ page }) => {
    await createAutosavedDraft(testProjectId, 1, "第一章", "旧稿")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "宫门对峙",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 20 }],
      must_happen: "王后签字",
      must_not_happen: "主角死亡",
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.locator(".scene-tree-label").first().click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })

    await page.locator("#writing-title-input").fill("第一章 冲突检查")
    await page.locator("#writing-editor").fill("主角死亡。城门仍未开启。")
    await clickWritingTool(page, "#btn-conflict-check")

    const conflictOptions = page.getByRole("dialog", { name: "剧情设定冲突检查选项" })
    await expect(conflictOptions).toContainText("剧情设定冲突检查", { timeout: 10000 })
    await conflictOptions.getByRole("button", { name: "开始检查" }).click()
    const conflictDialog = page.getByRole("dialog", { name: "剧情设定冲突检查", exact: true })
    await expect(page.locator(".writing-conflict-item", { hasText: "禁止项出现在正文" })).toBeVisible()
    await expect(page.locator(".writing-conflict-item", { hasText: "必须发生项缺失" })).toBeVisible()
    const forbiddenPresent = conflictDialog.locator(".writing-conflict-item", { hasText: "禁止项出现在正文" })
    await expect(forbiddenPresent.getByRole("button", { name: "定位正文" })).toBeEnabled()
    await expect(forbiddenPresent.getByRole("button", { name: "打开来源" })).toBeEnabled()
    const requiredMissing = conflictDialog.locator(".writing-conflict-item", { hasText: "必须发生项缺失" })
    await expect(requiredMissing.getByRole("button", { name: "无正文定位" })).toBeDisabled()
    await expect(requiredMissing.getByRole("button", { name: "打开来源" })).toBeEnabled()

    let aiReviewDone = false
    const mockedAiCheck = {
      id: "mock-check-ai",
      novel_id: testProjectId,
      chapter_index: 1,
      scene_id: null,
      draft_id: null,
      version_number: 1,
      scope: {},
      include_candidates: false,
      status: "completed",
      summary_json: {
        total: 3,
        open_high_count: 1,
        ai_review: { status: "done", item_count: 1, discarded_count: 0 },
      },
      ai_review_enabled: true,
      ai_review_status: "done",
      ai_review_confirmation_id: "00000000-0000-0000-0000-0000000000a1",
      ai_review_model: "mock",
      ai_review_error: null,
      items: [
        {
          id: "mock-high",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "forbidden_present",
          severity: "high",
          source_module: "outline",
          evidence_summary: "正文出现 Scene 禁止发生项：主角死亡",
          is_ai_judgment: false,
          needs_review: false,
          status: "open",
          suggestion_status: "not_requested",
        },
        {
          id: "mock-required",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "required_missing",
          severity: "medium",
          source_module: "outline",
          evidence_summary: "正文尚未覆盖 Scene 必须发生项：王后签字",
          is_ai_judgment: false,
          needs_review: false,
          status: "open",
          suggestion_status: "not_requested",
        },
        {
          id: "mock-ai-item",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "motivation_gap",
          severity: "medium",
          source_module: "ai",
          evidence_summary: "主角突然接受守卫条件",
          is_ai_judgment: true,
          needs_review: false,
          status: "open",
          confidence: 0.72,
          llm_rationale: "前文没有建立信任动机",
          suggestion_status: "not_requested",
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    await page.route("**/api/context/confirm", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-0000000000a1",
          novel_id: testProjectId,
          action: "writing.conflict_check.ai_review",
          selected_asset_ids: {},
          warnings: [],
        }),
      })
    })
    await page.route("**/api/writing/conflict-checks/*/ai-review", async (route) => {
      aiReviewDone = true
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedAiCheck),
      })
    })
    await page.route("**/api/writing/conflict-checks/*/ai-review-task", async (route) => {
      aiReviewDone = true
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "mock-ai-review-task",
          status: "pending",
          check: {
            ...mockedAiCheck,
            ai_review_status: "running",
            items: mockedAiCheck.items.slice(0, 2),
          },
        }),
      })
    })
    await page.route("**/api/tasks/**", async (route) => {
      const url = new URL(route.request().url())
      if (!url.pathname.endsWith("/api/tasks/mock-ai-review-task")) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "mock-ai-review-task",
          task_type: "writing_conflict_ai_review",
          status: "done",
          progress: 1,
          result: { check_id: mockedAiCheck.id, ai_review_status: "done" },
        }),
      })
    })
    await page.route("**/api/writing/conflict-checks/mock-check-ai?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedAiCheck),
      })
    })
    await page.route("**/api/writing/conflict-checks?**", async (route) => {
      if (!aiReviewDone) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [mockedAiCheck], total: 1 }),
      })
    })
    await page.route("**/api/writing/conflict-check-items/*/ai-suggestion", async (route) => {
      const updatedAiItem = {
        ...mockedAiCheck.items[2],
        suggestion_status: "done",
        ai_suggestion: JSON.stringify({
          strategy: "补动机过渡",
          suggested_text: "他想起旧约，才勉强点头。",
          rationale: "让接受条件有心理来源。",
          constraints: ["不能提前揭示守卫真相"],
          risk_notes: ["保持守卫仍不可信"],
        }),
      }
      mockedAiCheck.items = mockedAiCheck.items.map((item) => (
        item.id === updatedAiItem.id ? updatedAiItem : item
      ))
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updatedAiItem),
      })
    })
    await page.route("**/api/writing/conflict-check-items/mock-required?**", async (route) => {
      const updatedRequiredItem = {
        ...mockedAiCheck.items[1],
        status: "later",
      }
      mockedAiCheck.items = mockedAiCheck.items.map((item) => (
        item.id === updatedRequiredItem.id ? updatedRequiredItem : item
      ))
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updatedRequiredItem),
      })
    })

    await page.getByRole("button", { name: "补充 AI 软冲突判断" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    const conflictOverlay = conflictDialog.locator("xpath=..")
    await expect(conflictOverlay).toHaveAttribute("inert", "")
    await page.keyboard.press("Escape")
    await expect(page.locator("#modal-overlay")).toBeHidden()
    await expect(conflictOverlay).not.toHaveAttribute("inert")
    await expect(page.getByRole("button", { name: "补充 AI 软冲突判断" })).toBeEnabled()
    await expect(conflictDialog.locator(":focus")).toHaveCount(1)
    await expect(page.locator(SEL.toastContainer)).not.toContainText("已取消 AI 参考资料确认")

    await page.getByRole("button", { name: "补充 AI 软冲突判断" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(conflictDialog).toContainText("AI 判断", { timeout: 10000 })
    await expect(conflictDialog).toContainText("主角突然接受守卫条件")

    const unavailableAi = conflictDialog.locator(".writing-conflict-item", { hasText: "主角突然接受守卫条件" })
    await expect(unavailableAi.getByRole("button", { name: "无正文定位" })).toBeDisabled()
    await expect(unavailableAi.getByRole("button", { name: "无可打开来源" })).toBeDisabled()

    await page
      .locator(".writing-conflict-item", { hasText: "主角突然接受守卫条件" })
      .getByRole("button", { name: "生成 AI 修复建议" })
      .click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(conflictDialog).toContainText("补动机过渡", { timeout: 10000 })

    await page
      .locator(".writing-conflict-item", { hasText: "必须发生项缺失" })
      .getByRole("button", { name: "稍后" })
      .click()
    await expect(page.locator(SEL.toastContainer)).toContainText("状态已更新", { timeout: 10000 })
    await conflictDialog.locator(".modal-footer").getByRole("button", { name: "关闭" }).click()

    await page.locator("#btn-publish").click()
    await expect(page.locator("#modal-overlay")).toContainText("未处理的重要问题", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "继续设为正式正文" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已设为正式正文", { timeout: 15000 })

    const latestDraft = await getLatestDraft(testProjectId, 1)
    expect(latestDraft.novel_id).toBe(testProjectId)
    expect(latestDraft.status).toBe("published")
    expect(latestDraft.title).toBe("第一章 冲突检查")
    expect(latestDraft.content).toBe("主角死亡。城门仍未开启。")
    expect(latestDraft.conflict_check_snapshot_json?.items?.length).toBeGreaterThanOrEqual(2)
    expect(latestDraft.conflict_check_snapshot_json.items.some((item) => item.kind === "forbidden_present")).toBe(true)
  })

  test("章节树嵌套章节行有尺寸并可直接点击", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "第一章正文")
    await createDraft(testProjectId, 3, "第三章 归潮尽头", "第三章正文")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "回声仓",
      narrative_tag: "draft",
      chapter_ids: ["1", "3"],
      scene_chunks: [
        { chapter_index: 1, start_pos: 0, end_pos: 5 },
        { chapter_index: 3, start_pos: 0, end_pos: 5 },
      ],
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await expect(page.locator("#writing-tree-container")).toContainText("回声仓")

    const row = page.getByRole("button", { name: /打开第 3 章/ })
    await expect(row).toBeVisible({ timeout: 5000 })
    const box = await row.boundingBox()
    expect(box?.width).toBeGreaterThan(0)
    expect(box?.height).toBeGreaterThan(0)

    await row.click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第三章正文", { timeout: 5000 })
    await expect(page.locator("#btn-autosave")).toBeEnabled()
    await expect(page.locator("#btn-publish")).toBeEnabled()
    await expect(page.locator("#btn-conflict-check")).toBeEnabled()

    const previousChapter = page.getByRole("button", { name: "上一章", exact: true })
    const nextChapter = page.getByRole("button", { name: "下一章", exact: true })
    await expect(previousChapter).toBeEnabled()
    await expect(nextChapter).toBeDisabled()
    await previousChapter.click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第一章", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第一章正文", { timeout: 5000 })
    await expect(nextChapter).toBeEnabled()
    await nextChapter.click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第三章正文", { timeout: 5000 })
  })

  test("重复发布无实质变化的正文不制造版本或任务", async ({ page }) => {
    const initial = await createDraft(testProjectId, 3, "第三章 归潮尽头", "第三章正文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 3 })
    await selectWritingChapter(page, 3)
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })

    const polledTaskUrls = []
    await page.route("**/api/tasks/**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback()
        return
      }
      const url = new URL(route.request().url())
      polledTaskUrls.push(url.toString())
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: url.pathname.split("/").at(-1),
          task_type: "publish_chapter",
          status: "done",
          progress: null,
          meta: { novel_id: testProjectId, chapter_index: 3 },
          result: { message: "发布完成" },
          error_message: null,
          created_at: null,
          started_at: null,
          finished_at: null,
        }),
      })
    })

    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("无实质变化")
    expect(polledTaskUrls).toEqual([])

    const afterFirstPublish = await getLatestDraft(testProjectId, 3)
    expect(afterFirstPublish.version_number).toBe(initial.draft.version_number)
    expect(afterFirstPublish.status).toBe("published")

    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("无实质变化")

    const afterSecondPublish = await getLatestDraft(testProjectId, 3)
    expect(afterSecondPublish.version_number).toBe(afterFirstPublish.version_number)
    expect(afterSecondPublish.id).toBe(afterFirstPublish.id)
  })

  test("写作台响应式宽度不出现页面级横向溢出", async ({ page }) => {
    await createDraft(testProjectId, 1, "响应式章节", "响应式正文")

    for (const width of [1280, 900, 760, 600, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await reloadWorkbench(page, "writing")
      await waitWritingReady(page)
      await selectWritingChapter(page, 1)
      if (width <= 760) {
        await expect(page.locator("#mobile-note-editor")).toBeVisible({ timeout: 5000 })
        await expect(page.locator(".mobile-quick-note")).toContainText("完整编辑器")
      } else {
        await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })
        await openWritingToolMenu(page, "#btn-conflict-check")
        await expect(page.locator("#btn-conflict-check")).toBeVisible()
      }

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return Math.ceil(doc.scrollWidth - window.innerWidth)
      })
      expect(overflow).toBeLessThanOrEqual(2)
    }
  })

  test("390px 下短文本可保存为工作稿并在刷新后恢复", async ({ page }) => {
    await createDraft(testProjectId, 1, "移动速记", "原始移动正文")
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByLabel("展开章节").click()
    await page.getByRole("button", { name: /打开第 1 章/ }).click()

    const editor = page.getByLabel("移动端速记正文")
    await expect(editor).toBeVisible()
    await expect(editor).toHaveValue("原始移动正文")
    await editor.fill("390px 下保存的短文本。")
    const saveButton = page.getByRole("button", { name: "保存工作稿", exact: true })
    const saveBox = await saveButton.boundingBox()
    expect(saveBox).not.toBeNull()
    expect(saveBox.height).toBeGreaterThanOrEqual(44)
    await saveButton.click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存到工作稿", {
      timeout: 10000,
    })
    await expect.poll(async () => (
      (await getLatestDraft(testProjectId, 1)).content
    )).toBe("390px 下保存的短文本。")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    const chapterRail = page.locator(".writing-tree-rail")
    if (await chapterRail.evaluate((element) => element.classList.contains("is-collapsed"))) {
      await page.getByLabel("展开章节").click()
    }
    await page.getByRole("button", { name: /打开第 1 章/ }).click()
    await expect(page.getByLabel("移动端速记正文")).toHaveValue("390px 下保存的短文本。")
    const overflow = await page.evaluate(() => (
      Math.ceil(document.documentElement.scrollWidth - window.innerWidth)
    ))
    expect(overflow).toBeLessThanOrEqual(2)
  })

  test("390px 速记切换完整编辑器时保留未保存正文", async ({ page }) => {
    await createDraft(testProjectId, 1, "移动切换", "切换前正文")
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    const chapterRailToggle = page.getByLabel("展开章节")
    const railBox = await chapterRailToggle.boundingBox()
    expect(railBox).not.toBeNull()
    expect(railBox.height).toBeGreaterThanOrEqual(40)
    await chapterRailToggle.click()
    await page.getByRole("button", { name: /打开第 1 章/ }).click()
    const editor = page.getByLabel("移动端速记正文")
    await expect(editor).toHaveValue("切换前正文")
    await editor.fill("尚未保存但必须保留的正文")

    await page.getByRole("button", { name: "完整编辑器" }).click()

    await expect(page.locator("#writing-editor")).toBeVisible()
    await expect(page.locator("#writing-editor")).toHaveValue("尚未保存但必须保留的正文")
  })

  // ============================================================
  // 场景自动整理
  // ============================================================

  test("场景自动整理保留唯一 imports 入口", async ({ page }) => {
    await createDraft(testProjectId, 1, "ch1", "测试正文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })

    await page.locator('[data-action="writing-ai-menu"]').click()
    const sceneExtraction = page.getByRole("button", { name: "整理场景" })
    await expect(sceneExtraction).toBeVisible()
    await expect(sceneExtraction).toHaveCount(1)

    await sceneExtraction.click()
    const extractionDialog = page.getByRole("dialog", { name: "自动提取" })
    await expect(extractionDialog).toBeVisible()
    await expect(extractionDialog).toContainText("从正文整理场景")
    await expect(extractionDialog).toContainText("起始章节")
    await expect(extractionDialog).toContainText("结束章节")

    await extractionDialog.getByRole("button", { name: "关闭" }).click()
    await expect(extractionDialog).not.toBeVisible()
  })

  // ============================================================
  // 多 Tab 冲突检测
  // ============================================================

  test("多 Tab 冲突检测 — 草稿被其他会话删除", async ({ page }) => {
    // 先加载 v1，再由另一会话创建 v2 并删除当前编辑的 v1。
    const d1 = await createDraft(testProjectId, 1, "v1", "原始内容")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("原始内容", { timeout: 5000 })

    // 模拟另一个会话删除（软废弃）了当前编辑的 v1 版本
    await createDraft(testProjectId, 1, "v2", "另一个版本")
    await deleteDraft(testProjectId, d1.draft.id)

    // 尝试暂存 — v1 已不是最新工作版本，应返回 409 并给出可操作的冲突文案
    await page.locator("#writing-editor").fill("冲突内容")
    await clickWritingTool(page, "#btn-autosave")

    await expect(page.locator(SEL.toastContainer)).toContainText(
      "该章节已被其他会话更新，请刷新后重新编辑",
      { timeout: 10000 },
    )
  })
})
