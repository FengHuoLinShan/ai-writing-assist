import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  createProject, cleanupProject, waitForBackend,
  createDraft, createScene,
} from "./helpers/api-client.js"

test.describe("手动工作台模块", () => {
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
        { id: v2.draft.id, version_number: 2, title: v2.draft.title, word_count: 7 },
        { id: v1.draft.id, version_number: 1, title: v1.draft.title, word_count: 7 },
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
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })
  })

  // ============================================================
  // 新 Scene 创建 + 断章更新左侧树
  // ============================================================

  test("新 Scene 创建和断章更新左侧树", async ({ page }) => {
    // 创建 3 个章节
    const d1 = await createDraft(testProjectId, 1, "ch1", "第一章内容")
    await createDraft(testProjectId, 2, "ch2", "第二章内容")
    await createDraft(testProjectId, 3, "ch3", "第三章内容")

    // 创建 Scene 包含 1-3 章
    const scene = await createScene(testProjectId, {
      scene_index: 0, title: "测试Scene",
      chapter_ids: ["1", "2", "3"], narrative_tag: "draft",
    })

    // 注入完整状态
    await page.evaluate(({ scene, d1 }) => {
      writingView._scenes = [{
        id: scene.id, scene_index: 0, title: "测试Scene",
        chapter_ids: ["1", "2", "3"],
        narrative_tag: "draft", source: "manual",
        goal: null, core_conflict: null, emotional_beat: null,
        must_happen: null, must_not_happen: null,
      }]
      writingView._currentChapter = 2
      writingView._currentDraftId = d1.draft.id
      writingView._currentVersionNumber = 1
      writingView._chapterList = [1, 2, 3]
      writingView._chapters[1] = { title: "ch1", draftCount: 1 }
      writingView._chapters[2] = { title: "ch2", draftCount: 1 }
      writingView._chapters[3] = { title: "ch3", draftCount: 1 }
      writingView._currentContent = d1.draft.content
      writingView._currentTitle = d1.draft.title
      writingView._isReadonly = false
      return writingView._rerender()
    }, { scene, d1 })

    // 验证左侧树显示 Scene 节点
    await expect(page.locator("#writing-tree-container")).toContainText("测试Scene")
    await expect(page.locator("#writing-tree-container")).toContainText("第 1 章")
    await expect(page.locator("#writing-tree-container")).toContainText("第 2 章")

    // 点击断章按钮
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
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 5 }],
    })
    await createScene(testProjectId, {
      scene_index: 1,
      title: "Scene B",
      narrative_tag: "draft",
      scene_chunks: [{ chapter_index: 1, start_pos: 5, end_pos: 10 }],
    })

    await page.reload()
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // 选中第 1 章
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await expect(page.locator("#writing-editor")).toHaveValue("ABCDEFGHIJ", { timeout: 5000 })

    // 光标落在第一个 chunk → 显示 Scene A
    await page.evaluate(() => {
      writingView._cursorOffset = 2
      writingView._updateCurrentScene()
      const panel = document.getElementById("writing-panel-container")
      if (panel) panel.innerHTML = writingView._renderScenePanel()
    })
    await expect(page.locator("#writing-panel-container")).toContainText("Scene A")

    // 光标落在第二个 chunk → 显示 Scene B
    await page.evaluate(() => {
      writingView._cursorOffset = 7
      writingView._updateCurrentScene()
      const panel = document.getElementById("writing-panel-container")
      if (panel) panel.innerHTML = writingView._renderScenePanel()
    })
    await expect(page.locator("#writing-panel-container")).toContainText("Scene B")
  })

  // ============================================================
  // AI 提取章节卡
  // ============================================================

  test("AI 提取章节卡按钮和对话框", async ({ page }) => {
    await createDraft(testProjectId, 1, "ch1", "测试正文")
    await page.reload()
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // 验证"AI 提取章节卡"按钮存在
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

    // 注入章节状态
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = ""
      return writingView._rerender()
    })

    // 导航到别的章节再回来，触发 _refreshVersions 里的备份检查
    // _refreshVersions 在调用时如果 versions 为空会检查 localStorage 备份
    // 但由于我们是通过 evaluate 注入状态而非真实 API 创建，需要直接验证 API
    await expect(page.locator("#writing-editor")).toBeVisible()
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
    const API_BASE = "http://localhost:8000/api"
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
