import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  API_BASE,
  createProject, cleanupProject, waitForBackend,
  createDraft, createScene, getLatestDraft,
} from "./helpers/api-client.js"

async function confirmPublishIfPrompted(page) {
  const continueButton = page.locator("#modal-footer").getByRole("button", { name: "继续发布" })
  try {
    await expect(continueButton).toBeVisible({ timeout: 3000 })
    await continueButton.click()
  } catch {}
}

test.describe("写作台模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "写作测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  // ============================================================
  // 基础功能
  // ============================================================

  test("空状态显示新建章节按钮", async ({ page }) => {
    await expect(page.locator(SEL.emptyState)).toBeVisible()
    await expect(page.locator(SEL.emptyState)).toContainText("开始创作")
    await expect(page.locator('[data-action="new-chapter"]')).toBeVisible()
  })

  test("新建章节并显示在章节树", async ({ page }) => {
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })

    await expect(page.locator("#workspace-content")).toContainText("第 1 章")
    await expect(page.locator("#writing-editor")).toBeVisible()
  })

  test("编辑章节内容并暂存", async ({ page }) => {
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })
    await expect(page.locator("#writing-editor")).toBeVisible()

    await page.locator("#writing-editor").fill("初始发布内容。")
    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })

    await page.locator("#writing-title-input").fill("第一章 测试")
    await page.locator("#writing-editor").fill("这是测试内容。")

    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已暂存", { timeout: 10000 })
  })

  test("发布章节", async ({ page }) => {
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })
    await expect(page.locator("#writing-editor")).toBeVisible()

    await page.locator("#writing-title-input").fill("第一章 发布测试")
    await page.locator("#writing-editor").fill("这是发布测试的内容。")
    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })
  })

  // ============================================================
  // Scene 切换不丢失内容
  // ============================================================

  test("Scene 切换不丢失内容", async ({ page }) => {
    // 创建后端草稿
    const d1 = await createDraft(testProjectId, 1, "第一章", "第一章的正文内容ABC")
    const d2 = await createDraft(testProjectId, 2, "第二章", "第二章的正文内容XYZ")

    // 提取需要注入的值
    const d1Id = d1.draft.id, d1Content = d1.draft.content, d1Title = d1.draft.title
    const d2Id = d2.draft.id, d2Content = d2.draft.content, d2Title = d2.draft.title

    // 注入第 1 章状态
    await page.evaluate(({ id, content, title }) => {
      writingView._currentChapter = 1
      writingView._currentDraftId = id
      writingView._currentVersionNumber = 1
      writingView._chapterList = [1, 2]
      writingView._chapters[1] = { title, draftCount: 1 }
      writingView._chapters[2] = { title: "第二章", draftCount: 1 }
      writingView._currentContent = content
      writingView._currentTitle = title
      writingView._isReadonly = false
      return writingView._rerender()
    }, { id: d1Id, content: d1Content, title: d1Title })

    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })

    // 切换到第 2 章
    await page.evaluate(({ id, content, title }) => {
      writingView._currentDraftId = id
      writingView._currentVersionNumber = 1
      writingView._currentContent = content
      writingView._currentTitle = title
      return writingView._rerender()
    }, { id: d2Id, content: d2Content, title: d2Title })
    await expect(page.locator("#writing-editor")).toHaveValue(d2Content, { timeout: 5000 })

    // 编辑第 2 章后切换回第 1 章
    await page.locator("#writing-editor").fill("修改后的第二章内容")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已暂存", { timeout: 10000 })

    // 恢复第 1 章内容
    await page.evaluate(({ id, content, title }) => {
      writingView._currentDraftId = id
      writingView._currentVersionNumber = 1
      writingView._currentContent = content
      writingView._currentTitle = title
      return writingView._rerender()
    }, { id: d1Id, content: d1Content, title: d1Title })
    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })
  })

  // ============================================================
  // 版本历史查看与恢复
  // ============================================================

  test("版本历史查看与恢复", async ({ page }) => {
    // 创建 v1 和 v2
    const v1 = await createDraft(testProjectId, 1, "第一版", "版本一的正文内容")
    const v2 = await createDraft(testProjectId, 1, "第二版", "版本二的正文内容")

    // 注入完整状态（当前为 v2 最新版本）
    await page.evaluate(({ v1, v2 }) => {
      writingView._versions = [
        { id: v2.draft.id, version_number: 2, title: v2.draft.title, word_count: 7, updated_at: v2.draft.updated_at },
        { id: v1.draft.id, version_number: 1, title: v1.draft.title, word_count: 7, updated_at: v1.draft.updated_at },
      ]
      writingView._currentChapter = 1
      writingView._currentDraftId = v2.draft.id
      writingView._currentVersionNumber = 2
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: "第二版", draftCount: 2 }
      writingView._currentContent = v2.draft.content
      writingView._currentTitle = v2.draft.title
      writingView._isReadonly = false
      return writingView._rerender()
    }, { v1, v2 })

    // 打开版本历史弹窗
    await page.locator('[data-action="version-history"]').click()
    await expect(page.locator("#modal-overlay")).toBeVisible({ timeout: 5000 })
    await expect(page.locator("#modal-overlay")).toContainText("v2")
    await expect(page.locator("#modal-overlay")).toContainText("v1")
    await expect(page.locator("#modal-overlay")).toContainText("最新")

    // 预览 v1（最后一个预览按钮对应 v1）
    await page.locator(".version-preview-btn").last().click()
    await expect(page.locator("#writing-editor")).toHaveValue("版本一的正文内容", { timeout: 5000 })
    // v1 非最新版本 → 只读模式，显示"基于此版本创建"
    await expect(page.locator('[data-action="restore-from-version"]')).toBeVisible()

    // 点击"基于此版本创建"
    await page.locator('[data-action="restore-from-version"]').click()
    const toastText = await page.locator(SEL.toastContainer).textContent()
    expect(toastText).toContain("创建新版本")

    // 编辑后保存 — 由于 restore 模式，autosave 走发布流程
    await page.locator("#writing-editor").fill("基于 v1 的新内容")
    await page.locator('[data-action="autosave"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })
  })

  test("实质变化留版、强制 checkpoint 和发布前撤销", async ({ page }) => {
    const v1 = await createDraft(testProjectId, 1, "第一章", "甲\n乙")
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await expect(page.locator("#writing-editor")).toHaveValue("甲\n乙")

    // 纯空白修改只留本地，用户可显式强制留版。
    await page.locator("#writing-editor").fill(" 　甲\t\n\n乙 ")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator("#writing-save-status")).toHaveText("仅本地修改")
    await page.locator('[data-action="checkpoint-version"]').click()
    await expect(page.locator("#modal-overlay")).toContainText("正文没有实质变化")
    await page.locator("#modal-footer").getByRole("button", { name: "保存新版本" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    await expect(page.locator("#version-selector")).toContainText("v2")

    // 手动版本需显式确认放弃，回到 v1。
    await page.locator('[data-action="discard-writing-changes"]').click()
    await page.locator("#modal-footer").getByRole("button", { name: "放弃更改" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已回到上一版")
    await expect(page.locator("#writing-editor")).toHaveValue(v1.draft.content)

    // 实质修改自动创建工作版，撤销回基线时自动回到 v1。
    await page.locator("#writing-editor").fill("甲乙丙")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已暂存")
    await page.locator("#writing-editor").fill("甲\n乙")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator("#version-selector option").first()).toContainText("v1")

    // 再次修改后发布，当前工作版原位提升，不多加一版。
    await page.locator("#writing-editor").fill("甲乙丁")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator("#version-selector option").first()).not.toContainText("v1")
    const workingVersion = await page.locator("#version-selector option").first().getAttribute("data-version")
    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })

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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()

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
    await page.evaluate(() => { void writingView._editor.autosave() })
    await expect.poll(() => autosaveRequests).toBe(1)
    await page.locator("#writing-editor").fill("第二次修改")
    await page.evaluate(() => { void writingView._editor.autosave() })
    releaseFirstAutosave()
    await page.waitForFunction(
      () => !writingView._editor._currentSavePromise && !writingView._editor._autoSaving,
      null,
      { timeout: 15000 },
    )

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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await page.locator("#writing-editor").fill("v2")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator("#version-selector option").first()).toContainText("v2")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存")
    await page.locator('[data-action="checkpoint-version"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    const manualVersion = await page.locator("#version-selector option").first().getAttribute("data-version")

    await page.locator("#writing-editor").fill("v3")
    await page.locator('[data-action="autosave"]').click()
    await expect(page.locator("#version-selector option").first()).toContainText(
      `v${Number(manualVersion) + 1}`,
    )
    await expect(page.locator("#writing-save-status")).toHaveText("已保存")
    await page.locator("#writing-editor").fill("v2")
    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(String(history.versions[0].version_number)).toBe(manualVersion)
    expect(history.versions[0].status).toBe("published")
    expect(history.versions.map((item) => item.version_number)).not.toContain(Number(manualVersion) + 1)
  })

  test("历史恢复在最新版本变化后返回并发冲突", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "v1")
    await createDraft(testProjectId, 1, "第一章", "v2")
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await page.locator('[data-action="version-history"]').click()
    await page.locator('.version-restore-btn[data-version="1"]').click()
    await page.locator("#modal-footer").getByRole("button", { name: "确认恢复" }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("v1")

    const newest = await createDraft(testProjectId, 1, "第一章", "v3")
    await page.locator("#writing-editor").fill("基于 v1 恢复")
    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("其他会话更新")

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(history.versions[0].id).toBe(newest.draft.id)
  })

  // ============================================================
  // 新 Scene 创建 + 断章更新左侧树
  // ============================================================

  test("新 Scene 创建和断章更新左侧树", async ({ page }) => {
    // 创建 3 个章节
    await createDraft(testProjectId, 1, "ch1", "第一章内容")
    await createDraft(testProjectId, 2, "ch2", "第二章内容")
    await createDraft(testProjectId, 3, "ch3", "第三章内容")

    // 创建 Scene 包含 1-3 章（split 依赖 scene_chunks）
    const scene = await createScene(testProjectId, {
      scene_index: 0, title: "测试Scene",
      chapter_ids: ["1", "2", "3"], narrative_tag: "draft",
      scene_chunks: [
        { chapter_index: 1, start_pos: 0, end_pos: 5 },
        { chapter_index: 2, start_pos: 0, end_pos: 5 },
        { chapter_index: 3, start_pos: 0, end_pos: 5 },
      ],
    })

    // 通过真实导航加载第 2 章，避免注入状态不一致
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await expect(page.locator("#writing-tree-container")).toContainText("测试Scene")

    // Scene 默认折叠，先展开 Scene 节点再选择第 2 章
    await page.locator('[data-action="select-scene"]').click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第一章内容", { timeout: 5000 })
    await page.locator('[data-action="select-chapter"][data-chapter="2"]').click()
    await expect(page.locator("#writing-editor")).toHaveValue("第二章内容", { timeout: 5000 })

    // 验证左侧树显示 Scene 节点
    await expect(page.locator("#writing-tree-container")).toContainText("测试Scene")
    await expect(page.locator("#writing-tree-container")).toContainText("第 1 章")
    await expect(page.locator("#writing-tree-container")).toContainText("第 2 章")

    // 点击断章按钮
    await page.locator(".writing-tools-menu summary").click()
    await page.locator('[data-action="split-scene"]').click()
    await expect(page.locator("#modal-overlay")).toBeVisible({ timeout: 5000 })
    await expect(page.locator("#modal-overlay")).toContainText("断章")

    // 确认断章（在第 2 章内容 offset 2 处切分）
    await page.locator("#split-pos").fill("2")
    await page.locator("#modal-footer .btn-primary").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("断章完成", { timeout: 10000 })

    // 验证树已更新
    const treeText = await page.locator("#writing-tree-container").textContent()
    expect(treeText).toContain("Scene")
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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // 展开 Scene 节点并选中第 1 章
    await page.locator('[data-action="select-scene"]').first().click()
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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-scene"]').first().click()

    await expect(page.locator('.cockpit-tab[data-tab="lore"]')).toHaveClass(/active/)
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

    await page.locator('.cockpit-tab[data-tab="map"]').click()
    await page.evaluate(() => writingView._rerender())
    await expect(page.locator('.cockpit-tab[data-tab="map"]')).toHaveClass(/active/)
  })

  test("专注模式隐藏两侧面板后保持桌面阅读宽度", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 专注写作", "用于验证专注模式宽度的正文。")
    await page.setViewportSize({ width: 1280, height: 800 })
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()

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
    expect(before.editorWidth / before.contentWidth).toBeGreaterThanOrEqual(0.63)

    await page.locator(".writing-panel-rail > summary").click()
    await expect(page.locator(".writing-panel-rail")).not.toHaveAttribute("open", "")
    const collapsedWidth = await page.locator("#writing-editor-container").evaluate((node) => node.getBoundingClientRect().width)
    expect(collapsedWidth).toBeGreaterThan(before.editorWidth)
  })

  test("剧情设定冲突检查流程、状态更新和发布快照归档", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "旧稿")
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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-scene"]').first().click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })

    await page.locator("#writing-title-input").fill("第一章 冲突检查")
    await page.locator("#writing-editor").fill("主角死亡。城门仍未开启。")
    await page.locator('[data-action="run-conflict-check"]').click()

    await expect(page.locator("#modal-overlay")).toContainText("剧情设定冲突检查", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "开始检查" }).click()
    await expect(page.locator(".writing-conflict-item", { hasText: "禁止项出现在正文" })).toBeVisible()
    await expect(page.locator(".writing-conflict-item", { hasText: "必须发生项缺失" })).toBeVisible()

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
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 判断", { timeout: 10000 })
    await expect(page.locator("#modal-overlay")).toContainText("主角突然接受守卫条件")

    await page
      .locator(".writing-conflict-item", { hasText: "主角突然接受守卫条件" })
      .getByRole("button", { name: "生成 AI 修复建议" })
      .click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("补动机过渡", { timeout: 10000 })

    await page
      .locator(".writing-conflict-item", { hasText: "必须发生项缺失" })
      .getByRole("button", { name: "稍后" })
      .click()
    await expect(page.locator(SEL.toastContainer)).toContainText("状态已更新", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "关闭" }).click()

    await page.locator('[data-action="publish"]').click()
    await expect(page.locator("#modal-overlay")).toContainText("未处理高严重度问题", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "继续发布" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })

    const latestDraft = await getLatestDraft(testProjectId, 1)
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
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await expect(page.locator("#writing-tree-container")).toContainText("回声仓")

    const row = page.locator('[data-action="select-chapter"][data-chapter="3"]')
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
  })

  test("重复发布无实质变化的正文不制造版本或任务", async ({ page }) => {
    const initial = await createDraft(testProjectId, 3, "第三章 归潮尽头", "第三章正文")
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="3"]').click()
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

    await page.locator('[data-action="publish"]').click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("无实质变化")
    expect(polledTaskUrls).toEqual([])

    const afterFirstPublish = await getLatestDraft(testProjectId, 3)
    expect(afterFirstPublish.version_number).toBe(initial.draft.version_number)
    expect(afterFirstPublish.status).toBe("published")

    await page.locator('[data-action="publish"]').click()
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
      await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
      await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
      if (width < 600) {
        await expect(page.locator("#mobile-note-editor")).toBeVisible({ timeout: 5000 })
        await expect(page.locator(".mobile-quick-note")).toContainText("完整编辑器")
      } else {
        await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })
        await expect(page.locator("#btn-conflict-check")).toBeVisible()
      }

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return Math.ceil(doc.scrollWidth - window.innerWidth)
      })
      expect(overflow).toBeLessThanOrEqual(2)
    }
  })

  // ============================================================
  // AI 提取章节卡
  // ============================================================

  test("AI 提取章节卡按钮和对话框", async ({ page }) => {
    await createDraft(testProjectId, 1, "ch1", "测试正文")
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // 验证"AI 提取章节卡"按钮存在
    await page.locator(".writing-tools-menu summary").click()
    await expect(page.locator('[data-action="extract-cards"]')).toBeVisible()

    // 点击按钮打开对话框
    await page.locator('[data-action="extract-cards"]').click()
    await expect(page.locator("#modal-overlay")).toBeVisible()
    await expect(page.locator("#modal-overlay")).toContainText("AI 提取章节卡")
    await expect(page.locator("#modal-overlay")).toContainText("起始章节")
    await expect(page.locator("#modal-overlay")).toContainText("结束章节")

    // 关闭对话框
    await page.locator("#modal-close").click()
    await expect(page.locator("#modal-overlay")).not.toBeVisible()
  })

  // ============================================================
  // 离线恢复 (localStorage 后备)
  // ============================================================

  test("离线恢复 — localStorage 后备内容", async ({ page }) => {
    const backupContent = "本地暂存的离线内容"
    const backupTitle = "离线标题"

    // 模拟：编辑后未保存就离开，内容被写入 localStorage
    await page.evaluate((projectId) => {
      const backupKey = `draft_backup_${projectId}_1`
      localStorage.setItem(backupKey, JSON.stringify({
        content: "本地暂存的离线内容",
        title: "离线标题",
        chapter_index: 1,
        timestamp: Date.now(),
      }))
    }, testProjectId)

    // 注入章节状态（无服务端版本）
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = ""
      writingView._versions = []
      writingView._currentDraftId = null
      writingView._currentVersionNumber = null
      return writingView._rerender()
    })

    // 触发版本刷新，应检测到 localStorage 备份并弹出恢复确认
    // 使用 fire-and-forget 方式，避免 evaluate 阻塞在 confirm 回调上
    await page.evaluate(() => {
      writingView._refreshVersions(1)
    })

    await expect(page.locator(SEL.modalOverlay)).toBeVisible({ timeout: 5000 })
    await expect(page.locator(SEL.modalBody)).toContainText("检测到本地暂存")
    await page.locator(`${SEL.modalFooter} .btn-danger`).click()

    // 恢复后重新渲染，使备份内容写入 DOM
    await page.evaluate(() => writingView._rerender())

    // 断言备份内容已恢复到编辑器
    await expect(page.locator("#writing-editor")).toHaveValue(backupContent, { timeout: 5000 })
    await expect(page.locator("#writing-title-input")).toHaveValue(backupTitle, { timeout: 5000 })
  })

  // ============================================================
  // 多 Tab 冲突检测
  // ============================================================

  test("多 Tab 冲突检测 — 草稿被其他会话删除", async ({ page }) => {
    // 创建 v1 和 v2（至少 2 个版本才能删单个版本）
    const d1 = await createDraft(testProjectId, 1, "v1", "原始内容")
    await createDraft(testProjectId, 1, "v2", "另一个版本")

    // 注入 v1 状态
    await page.evaluate((d1) => {
      writingView._currentChapter = 1
      writingView._currentDraftId = d1.draft.id
      writingView._currentVersionNumber = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: "v1", draftCount: 2 }
      writingView._currentContent = d1.draft.content
      writingView._currentTitle = d1.draft.title
      writingView._isReadonly = false
      writingView._lastSavedContent = d1.draft.content
      return writingView._rerender()
    }, d1)

    await expect(page.locator("#writing-editor")).toHaveValue("原始内容", { timeout: 5000 })

    // 模拟另一个会话删除了当前编辑的 v1 版本
    await fetch(
      `${API_BASE}/writing/drafts/${d1.draft.id}?novel_id=${encodeURIComponent(testProjectId)}`,
      { method: "DELETE" },
    )

    // 尝试暂存 — v1 草稿已不存在，应返回 404
    await page.locator("#writing-editor").fill("冲突内容")
    await page.locator('[data-action="autosave"]').click()

    // 应显示错误（草稿已被删除，404 not found）
    await expect(page.locator(SEL.toastContainer)).toContainText("不存在", { timeout: 10000 })
  })
})
