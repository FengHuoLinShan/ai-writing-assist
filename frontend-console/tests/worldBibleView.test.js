import { beforeEach, describe, expect, it, vi } from "vitest"
import worldBibleView from "../views/worldBibleView.js"
import { clearDocument, resetState } from "./helpers.js"

const page = {
  id: "page-1",
  novel_id: "p1",
  page_type: "background",
  title: "世界基本背景",
  status: "draft",
  free_text: "已有设定正文",
}
const speciesPage = {
  id: "page-2",
  novel_id: "p1",
  page_type: "species",
  title: "种族设定",
  status: "canonical",
  free_text: "灵族与人族长期共存。",
}

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  worldBibleView._pages = []
  worldBibleView._activePage = null
  worldBibleView._suggestions = []
  worldBibleView._conflicts = []
  worldBibleView._task = null
  worldBibleView._projectionConflictHint = null
  worldBibleView._aiOpen = false
  worldBibleView._aiMessages = []
  worldBibleView._aiOutputTarget = "chat"
  worldBibleView._aiTemplateId = "builtin:none"
  worldBibleView._aiQualityMode = "fast"
  worldBibleView._aiSelectedChapters = ""
  worldBibleView._aiResult = null
  worldBibleView._displayMode = "editor"
  worldBibleView._activeCategory = "all"
  worldBibleView._galleryCategory = null
  if (worldBibleView._projectionPoller?.stop) worldBibleView._projectionPoller.stop()
  worldBibleView._projectionPoller = null
  worldBibleView._bibleClickHandler = null
})

describe("worldBibleView", () => {
  it("新建页面使用应用内弹窗，不依赖浏览器 prompt", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
    api.world.createBiblePage.mockResolvedValue({ ...page, title: "种族设定", page_type: "species" })

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    document.querySelector("[data-action='bible-new-page']").click()

    expect(prompt).not.toHaveBeenCalled()
    expect(showModal).toHaveBeenCalledWith(
      "新建世界书页面",
      expect.objectContaining({ html: expect.stringContaining("bible-create-title") }),
      expect.any(Array),
    )

    document.body.innerHTML = showModal.mock.calls[0][1].html
    document.getElementById("bible-create-title").value = "种族设定"
    document.getElementById("bible-create-type").value = "species"
    await showModal.mock.calls[0][2][0].handler()

    expect(api.world.createBiblePage).toHaveBeenCalledWith({
      novel_id: "p1",
      title: "种族设定",
      page_type: "species",
      status: "draft",
    })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("刷新投影后轮询任务，并用当前项目 ID 查询状态", async () => {
    worldBibleView._activePage = page
    api.world.refreshBibleProjection.mockResolvedValue({ task_id: "task-1", existing: false })
    api.tasks.get
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "pending",
        progress: 0,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "pending",
        progress: 0,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "done",
        progress: 1,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })

    await worldBibleView._refreshProjection(false)

    expect(router.refresh).toHaveBeenCalled()
    await worldBibleView._restoreProjectionTask(page)
    await vi.waitFor(() => {
      expect(worldBibleView._task.status).toBe("done")
    })
    expect(api.world.refreshBibleProjection).toHaveBeenCalledWith("page-1", "p1", "context_brief", false)
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(localStorage.getItem("worldBibleProjection:p1:page-1:context_brief")).toBe("task-1")
    expect(router.renderCurrentView).toHaveBeenCalled()
  })

  it("普通刷新遇到已完成任务时保留真实 task 并使用单独 hint 提示", async () => {
    worldBibleView._activePage = page
    const err = new Error("请求失败：status: projection_task_finished；task_id: task-done；task_status: done")
    err.status = 409
    api.world.refreshBibleProjection.mockRejectedValue(err)
    api.tasks.get.mockResolvedValue({
      task_id: "task-done",
      task_type: "world_bible_projection_refresh",
      status: "done",
      progress: 1,
      meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
    })

    await worldBibleView._refreshProjection(false)

    expect(localStorage.getItem("worldBibleProjection:p1:page-1:context_brief")).toBe("task-done")
    expect(api.tasks.get).toHaveBeenCalledWith("task-done", "p1")
    expect(worldBibleView._task.status).toBe("done")
    expect(worldBibleView._task.error_message).toBeUndefined()
    expect(worldBibleView._projectionConflictHint).toContain("强制重新刷新")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("刷新投影失败时不向作者暴露任务注册表内部错误", async () => {
    worldBibleView._activePage = page
    api.world.refreshBibleProjection.mockRejectedValue(new Error(
      "ValueError: No handler registered for task type: world_bible_projection_refresh. Registered types: []",
    ))

    await worldBibleView._refreshProjection(false)

    expect(toast).toHaveBeenCalledWith(
      "投影刷新任务暂不可用，请确认后端 worker 已更新并重启后重试",
      "error",
    )
  })

  it("bindEvents does not add duplicate click listeners on repeated renders", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page], total: 1 })
    const spy = vi.spyOn(worldBibleView, "_createPage").mockImplementation(() => {})

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()

    document.querySelector("[data-action='bible-new-page']").click()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it("打开建议和冲突弹窗时使用世界书专用过滤条件", async () => {
    api.world.listSuggestions.mockResolvedValue({ items: [], total: 0 })
    api.world.listWorldConflicts.mockResolvedValue({ items: [], total: 0 })

    await worldBibleView._openSuggestions()
    await worldBibleView._openConflicts()

    expect(api.world.listSuggestions).toHaveBeenCalledWith({
      novel_id: "p1",
      source_module: "world_bible",
      status: "pending",
    })
    expect(api.world.listWorldConflicts).toHaveBeenCalledWith({ novel_id: "p1", status: "pending" })
    expect(showModal.mock.calls[0][0]).toBe("创设建议")
    expect(showModal.mock.calls[1][0]).toBe("冲突检查")
  })

  it("创设建议弹窗保留单条确认/拒绝按钮", async () => {
    api.world.listSuggestions.mockResolvedValue({
      items: [{
        id: "s1",
        review_group: "world_bible_ai",
        target_type: "world_bible_page_patch",
        action_schema: "world_bible_ai.v1",
        risk_level: "low",
        payload_json: { append_text: "补写" },
      }],
      total: 1,
    })

    await worldBibleView._openSuggestions()

    const html = showModal.mock.calls[0][1].html
    expect(html).toContain('data-bible-confirm-suggestion="s1"')
    expect(html).toContain('data-bible-reject-suggestion="s1"')
  })

  it("世界书 AI 边栏生成建议时带当前页和输出目标", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page], total: 1 })
    api.world.generateBiblePageAi.mockResolvedValue({
      suggestions: [{
        id: "s1",
        target_type: "world_bible_page_patch",
        review_group: "world_bible_ai",
        risk_level: "low",
        title: "补写当前页",
      }],
      model: "deepseek-v4-flash",
      provider: "fake",
    })

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    document.querySelector("[data-action='bible-toggle-ai']").click()
    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()

    expect(document.querySelector(".bible-ai-sidebar").textContent).toContain("当前页：世界基本背景")
    document.getElementById("bible-ai-output-target").value = "page_patch"
    document.getElementById("bible-ai-output-target").dispatchEvent(new Event("change"))
    document.getElementById("bible-ai-input").value = "帮我补写这一页"
    await worldBibleView._runAi()

    expect(api.world.generateBiblePageAi).toHaveBeenCalledWith(
      "page-1",
      expect.objectContaining({
        output_target: "page_patch",
        include_current_page: true,
        messages: [{ role: "user", content: "帮我补写这一页" }],
      }),
      "p1",
    )
    expect(worldBibleView._aiResult.suggestions[0].id).toBe("s1")
  })

  it("创设建议弹窗用可读卡片展示而不是 raw JSON", async () => {
    api.world.listSuggestions.mockResolvedValue({
      items: [{
        id: "s1",
        review_group: "world_bible_ai",
        target_type: "world_bible_page_patch",
        action_schema: "world_bible_ai.v1",
        risk_level: "low",
        payload_json: {
          append_text: "<img src=x onerror=alert(1)>补写",
          source_refs: [{ source_type: "world_bible_page", title: "世界基本背景" }],
        },
      }],
      total: 1,
    })

    await worldBibleView._openSuggestions()

    const html = showModal.mock.calls[0][1].html
    expect(html).toContain("补写当前页")
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;补写")
    expect(html).not.toContain("\"append_text\"")
  })

  it("恢复世界书展示模式偏好，并能切换回编辑模式", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page], total: 1 })
    localStorage.setItem("worldBible:p1:displayMode", "filter")

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()

    expect(document.querySelector(".world-bible-filter")).not.toBeNull()
    expect(document.querySelector("[data-mode='filter']").className).toContain("btn-primary")

    document.querySelector("[data-mode='editor']").click()

    expect(worldBibleView._displayMode).toBe("editor")
    expect(localStorage.getItem("worldBible:p1:displayMode")).toBe("editor")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("筛选模式按世界书页面类型展示计数和页面卡", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page, speciesPage], total: 2 })
    localStorage.setItem("worldBible:p1:displayMode", "filter")
    localStorage.setItem("worldBible:p1:activeCategory", "species")

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()

    expect(document.querySelector(".world-bible-filter").textContent).toContain("种族")
    expect(document.querySelector(".world-bible-filter").textContent).toContain("2 个页面")
    expect(document.querySelector(".world-bible-page-card-grid").textContent).toContain("种族设定")
    expect(document.querySelector(".world-bible-page-card-grid").textContent).not.toContain("世界基本背景")

    document.querySelector("[data-action='bible-set-category'][data-category='all']").click()

    expect(worldBibleView._activeCategory).toBe("all")
    expect(localStorage.getItem("worldBible:p1:activeCategory")).toBe("all")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("图鉴模式可钻取分类，并从页面卡进入编辑模式", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page, speciesPage], total: 2 })
    localStorage.setItem("worldBible:p1:displayMode", "gallery")

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    document.querySelector("[data-action='bible-gallery-open'][data-category='species']").click()

    expect(worldBibleView._galleryCategory).toBe("species")
    expect(router.refresh).toHaveBeenCalled()

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    expect(document.querySelector(".world-bible-category-header").textContent).toContain("种族")

    document.querySelector("[data-action='bible-open-page-card'][data-page-id='page-2']").click()

    expect(worldBibleView._activePage.id).toBe("page-2")
    expect(worldBibleView._displayMode).toBe("editor")
    expect(worldBibleView._galleryCategory).toBeNull()
    expect(localStorage.getItem("worldBible:p1:displayMode")).toBe("editor")
  })

  it("未知页面类型使用 fallback，页面卡动态文本保持转义", async () => {
    api.world.listBiblePages.mockResolvedValue({
      items: [{
        id: "page-xss",
        novel_id: "p1",
        page_type: "myth<script>",
        title: "<img src=x onerror=alert(1)>",
        status: "draft",
        free_text: "<script>alert(1)</script>隐藏设定",
      }],
      total: 1,
    })
    localStorage.setItem("worldBible:p1:displayMode", "filter")

    document.body.innerHTML = await worldBibleView.render()

    expect(document.querySelector(".world-bible-filter").textContent).toContain("myth<script>")
    expect(document.querySelector("img")).toBeNull()
    expect(document.querySelector("script")).toBeNull()
    expect(document.body.innerHTML).toContain("&lt;img src=x onerror=alert(1)&gt;")
    expect(document.body.innerHTML).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
  })
})
