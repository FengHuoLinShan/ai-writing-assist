import { beforeEach, describe, expect, it, vi } from "vitest"
import worldBibleView from "../views/worldBibleView.js"
import { clickModalButtonByText, clearDocument, resetState } from "./helpers.js"

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
  worldBibleView._categories = []
  worldBibleView._drafts = []
  worldBibleView._activePage = null
  worldBibleView._activeDraft = null
  worldBibleView._synopsis = null
  worldBibleView._pageTemplates = []
  worldBibleView._activationProfiles = []
  worldBibleView._activeActivationProfileId = null
  worldBibleView._activationTrace = null
  worldBibleView._synopsisTask = null
  if (worldBibleView._synopsisPoller?.stop) worldBibleView._synopsisPoller.stop()
  worldBibleView._synopsisPoller = null
  worldBibleView._synopsisTerminalTaskId = null
  worldBibleView._suggestions = []
  worldBibleView._suggestionBatchKey = null
  worldBibleView._conflicts = []
  worldBibleView._task = null
  worldBibleView._projectionConflictHint = null
  worldBibleView._projectionRetryPending = false
  worldBibleView._editorBaseline = null
  worldBibleView._editorBaselineKey = null
  worldBibleView._displayMode = "editor"
  worldBibleView._activeCategory = "all"
  worldBibleView._galleryCategory = null
  if (worldBibleView._projectionPoller?.stop) worldBibleView._projectionPoller.stop()
  worldBibleView._projectionPoller = null
  worldBibleView._bibleClickHandler = null
  api.world.listBibleCategories.mockResolvedValue({ items: [] })
  api.world.listBibleDrafts.mockResolvedValue({ items: [], total: 0 })
  api.world.getBibleSynopsis.mockResolvedValue({
    status: "missing",
    stale: true,
    warnings: [],
    auto_refresh_enabled: false,
  })
  api.world.listBiblePageTemplates = vi.fn().mockResolvedValue({ items: [] })
  api.world.applyBiblePageTemplate = vi.fn()
  api.context.listActivationProfiles = vi.fn().mockResolvedValue({ items: [] })
  api.context.previewActivationProfile = vi.fn()
  api.context.publishActivationProfile = vi.fn()
  api.context.createActivationProfile = vi.fn()
  api.context.updateActivationProfile = vi.fn()
})

describe("worldBibleView", () => {
  it("为页面概览和分区正文提供程序化标签，并把 AI 入口交给生成中心", () => {
    worldBibleView._activePage = page
    worldBibleView._activeDraft = {
      ...page,
      sections_json: [{
        section_id: "overview",
        title: "概述",
        section_type: "markdown",
        sensitivity_hint: "author_safe",
        projection_policy: "eligible",
        body_markdown: "分区内容",
        linked_asset_ref_hashes: [],
      }],
    }
    document.body.innerHTML = worldBibleView._renderActivePage()

    expect(document.getElementById("bible-free-text").labels[0].textContent).toContain("页面概览")
    expect(document.querySelector('[data-section-field="body_markdown"]').labels[0].textContent).toContain("分区正文")
    expect(document.querySelector('[data-action="bible-improve-with-ai"]')).not.toBeNull()
    expect(document.querySelector(".bible-ai-sidebar")).toBeNull()
  })

  it("结构化分区可编辑并随工作稿保存", async () => {
    api.world.listBiblePages.mockResolvedValue({
      items: [{
        ...page,
        status: "canonical",
        sections_json: [{
          section_id: "currency",
          section_type: "markdown",
          title: "货币",
          body_markdown: "旧正文",
          sort_order: 10,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        }],
      }],
      total: 1,
    })
    api.world.listBibleDrafts.mockResolvedValue({
      items: [{
        id: "draft-1",
        page_id: "page-1",
        title: "世界基本背景",
        page_type: "background",
        sections_json: [{
          section_id: "currency",
          section_type: "markdown",
          title: "货币",
          body_markdown: "旧正文",
          sort_order: 10,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        }],
      }],
      total: 1,
    })
    api.world.updateBibleDraft.mockImplementation(async (_id, payload) => ({ id: "draft-1", page_id: "page-1", ...payload }))

    document.body.innerHTML = await worldBibleView.render()
    document.querySelector('[data-section-field="title"]').value = "货币与交换"
    document.querySelector('[data-section-field="body_markdown"]').value = "新正文"
    await worldBibleView._savePage()

    expect(api.world.updateBibleDraft).toHaveBeenCalledWith(
      "draft-1",
      expect.objectContaining({
        sections_json: [expect.objectContaining({
          section_id: "currency",
          title: "货币与交换",
          body_markdown: "新正文",
        })],
      }),
      "p1",
    )
  })

  it("新增分区重绘前保留尚未保存的页面概览", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
    api.world.listBibleDrafts.mockResolvedValue({
      items: [{
        id: "draft-1",
        page_id: null,
        title: "世界基本背景",
        page_type: "background",
        free_text: "旧概览",
        sections_json: [],
      }],
      total: 1,
    })

    document.body.innerHTML = await worldBibleView.render()
    document.getElementById("bible-free-text").value = "尚未保存的新概览"
    worldBibleView._addSection()

    expect(worldBibleView._activeDraft.free_text).toBe("尚未保存的新概览")
    expect(worldBibleView._activeDraft.sections_json).toHaveLength(1)
    expect(document.getElementById("bible-free-text").value).toBe("尚未保存的新概览")
    expect(document.querySelectorAll(".world-bible-section-editor")).toHaveLength(1)
    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
    expect(worldBibleView._editorHasUnsavedChanges()).toBe(true)
  })

  it("AI 提案的 0/1 分区排序不会被误判为未保存修改", () => {
    worldBibleView._activeDraft = {
      id: "draft-ai",
      page_id: "page-1",
      updated_at: "2026-07-15T10:00:00Z",
      title: "AI 整页提案",
      page_type: "background",
      free_text: "概览",
      linked_asset_refs_json: [],
      sections_json: [
        {
          section_id: "first",
          section_type: "markdown",
          title: "第一节",
          body_markdown: "A",
          sort_order: 0,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        },
        {
          section_id: "second",
          section_type: "markdown",
          title: "第二节",
          body_markdown: "B",
          sort_order: 1,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        },
      ],
    }
    worldBibleView._setEditorBaseline(worldBibleView._activeDraft)
    document.body.innerHTML = worldBibleView._renderActivePage()

    expect(worldBibleView._editorHasUnsavedChanges()).toBe(false)
    document.querySelector('[data-section-id="second"] [data-section-field="body_markdown"]').value = "B2"
    expect(worldBibleView._editorHasUnsavedChanges()).toBe(true)
  })

  it("未保存编辑会阻止页面切换和离开", () => {
    worldBibleView._activePage = { ...page }
    worldBibleView._pages = [page, speciesPage]
    worldBibleView._drafts = []
    worldBibleView._setEditorBaseline(worldBibleView._activePage)
    document.body.innerHTML = worldBibleView._renderActivePage()
    document.getElementById("bible-free-text").value = "尚未保存的修改"
    const originalConfirm = window.confirm
    const confirmSpy = vi.fn(() => false)
    window.confirm = confirmSpy

    worldBibleView._openPageCard("page-2")

    expect(worldBibleView._activePage.id).toBe("page-1")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(worldBibleView.canLeave()).toBe(false)
    expect(confirmSpy).toHaveBeenCalledTimes(2)
    window.confirm = originalConfirm
  })

  it("AI 参考规则 dry-run 对动态 trace 做转义并显示排除原因", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [page], total: 1 })
    api.context.listActivationProfiles.mockResolvedValue({
      items: [{
        id: "profile-1",
        profile_key: "writing.world",
        name: "写作规则",
        status: "draft",
        version_number: 1,
        applicable_actions_json: ["writing.generate"],
        rules_json: [],
      }],
    })
    api.context.previewActivationProfile.mockResolvedValue({
      profile: { id: "profile-1", version: 1, status: "draft" },
      rule_evaluations: [{ rule_id: "<script>bad</script>", matched: false, candidate_count: 0, blocked_clauses: ["negative_matched"] }],
      items: [],
      excluded_items: [{ label: "<img src=x onerror=bad>", excluded_reason: "negative_matched", token_before: 0 }],
      warnings: [],
    })

    document.body.innerHTML = await worldBibleView.render()
    document.getElementById("bible-activation-task").value = "北境梦境"
    await worldBibleView._dryRunActivationProfile()
    const html = worldBibleView._renderActivationTrace()

    expect(api.context.previewActivationProfile).toHaveBeenCalledWith(expect.objectContaining({
      profile_id: "profile-1",
      action: "writing.generate",
      task_text: "北境梦境",
    }))
    expect(html).toContain("negative_matched")
    expect(html).not.toContain("<script>bad</script>")
    expect(html).not.toContain("<img src=x onerror=bad>")
  })

  it("新建页面使用应用内弹窗，不依赖浏览器 prompt", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
    api.world.createBibleDraft.mockResolvedValue({
      id: "draft-1",
      page_id: null,
      title: "种族设定",
      page_type: "species",
      free_text: null,
    })

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

    expect(api.world.createBibleDraft).toHaveBeenCalledWith({
      novel_id: "p1",
      title: "种族设定",
      page_type: "species",
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

  it("编辑正式页先保存服务器工作稿，发布才更新正式页面", async () => {
    worldBibleView._activePage = { ...page, status: "canonical", sort_order: 0 }
    api.world.createBibleDraft.mockResolvedValue({
      id: "draft-1",
      page_id: "page-1",
      title: page.title,
      page_type: page.page_type,
      free_text: page.free_text,
      linked_asset_refs_json: [],
      sort_order: 0,
    })
    api.world.updateBibleDraft.mockResolvedValue({
      id: "draft-1",
      page_id: "page-1",
      title: page.title,
      page_type: page.page_type,
      free_text: "工作稿正文",
      linked_asset_refs_json: [],
      sort_order: 0,
    })
    api.world.publishBibleDraft.mockResolvedValue({
      ...page,
      status: "canonical",
      version_number: 2,
      free_text: "工作稿正文",
    })
    document.body.innerHTML = worldBibleView._renderActivePage()
    expect(document.querySelector("[data-action='bible-publish-page']").textContent).toBe("保存并发布")
    document.getElementById("bible-free-text").value = "工作稿正文"

    await worldBibleView._savePage()

    expect(api.world.createBibleDraft).toHaveBeenCalledWith({
      novel_id: "p1",
      page_id: "page-1",
    })
    expect(api.world.updateBiblePage).not.toHaveBeenCalled()
    expect(worldBibleView._activeDraft.id).toBe("draft-1")

    document.body.innerHTML = worldBibleView._renderActivePage()
    await worldBibleView._publishDraft()

    expect(api.world.publishBibleDraft).toHaveBeenCalledWith("draft-1", "p1")
    expect(worldBibleView._activeDraft).toBeNull()
    expect(worldBibleView._activePage.version_number).toBe(2)
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

  it("仅当任务动作允许时重试投影刷新并恢复轮询", async () => {
    worldBibleView._activePage = page
    worldBibleView._task = {
      task_id: "task-retry",
      task_type: "world_bible_projection_refresh",
      status: "failed",
      progress: 0.5,
      error_message: "provider unavailable",
      available_actions: ["retry"],
    }
    api.tasks.retry.mockResolvedValue({
      task_id: "task-retry",
      status: "pending",
      attempt: 1,
      max_attempts: 2,
    })
    const polling = vi.spyOn(worldBibleView, "_startProjectionPolling").mockImplementation(() => {})

    expect(worldBibleView._renderProjectionStatus(page)).toContain("重试任务")
    await expect(worldBibleView._retryProjectionTask()).resolves.toBe(true)

    expect(api.tasks.retry).toHaveBeenCalledWith("task-retry", "p1")
    expect(worldBibleView._task.status).toBe("pending")
    expect(worldBibleView._task.error_message).toBeNull()
    expect(polling).toHaveBeenCalledWith("task-retry", page)
    polling.mockRestore()
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
      source_module: "world",
      review_group: "generation_center",
      status: "pending",
    })
    expect(api.world.listWorldConflicts).toHaveBeenCalledWith({ novel_id: "p1", status: "pending" })
    expect(showModal.mock.calls[0][0]).toBe("创设建议")
    expect(showModal.mock.calls[0][3]).toEqual({ size: "large" })
    expect(showModal.mock.calls[1][0]).toBe("冲突检查")
  })

  it("页面创设建议使用编辑后应用工作稿，不走直发确认", async () => {
    api.world.listSuggestions.mockResolvedValue({
      items: [{
        id: "s1",
        review_group: "generation_center",
        target_type: "world_bible_page_draft",
        action_schema: "world_generation.page_draft.v1",
        risk_level: "low",
        payload_json: {
          page: {
            title: "世界基本背景",
            page_type: "background",
            free_text: "补写",
            sections_json: [],
          },
        },
      }],
      total: 1,
    })

    await worldBibleView._openSuggestions()

    const html = showModal.mock.calls[0][1].html
    expect(html).toContain('data-bible-edit-suggestion="s1"')
    expect(html).not.toContain('data-bible-confirm-suggestion="s1"')
    expect(html).toContain('data-bible-reject-suggestion="s1"')
  })

  it("编辑后的页面建议只应用到工作稿", async () => {
    const suggestion = {
      id: "s1",
      target_type: "world_bible_page_draft",
      payload_json: {
        page: {
          title: "AI 标题",
          page_type: "background",
          free_text: "AI 原文",
          sections_json: [],
        },
      },
    }
    worldBibleView._suggestions = [suggestion]
    api.generate.applyWorldPageDraft.mockResolvedValue({
      draft: { id: "draft-1" },
    })
    api.world.listBiblePages.mockResolvedValue({ items: [page], total: 1 })
    api.world.listBibleDrafts.mockResolvedValue({
      items: [{ id: "draft-1", page_id: "page-1", title: page.title }],
      total: 1,
    })
    api.world.listSuggestions.mockResolvedValue({ items: [], total: 0 })

    worldBibleView._editSuggestionIntoDraft(suggestion)
    document.body.innerHTML = showModal.mock.calls[0][1].html
    document.getElementById("bible-suggestion-text").value = "作者编辑稿"
    await showModal.mock.calls[0][2][0].handler()

    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "s1",
      {
        page: {
          title: "AI 标题",
          page_type: "background",
          free_text: "作者编辑稿",
          sections_json: [],
          linked_asset_refs_json: [],
        },
      },
      "p1",
    )
    expect(api.world.confirmSuggestion).not.toHaveBeenCalled()
    expect(api.world.listSuggestions).not.toHaveBeenCalled()
    expect(worldBibleView._activeDraft.id).toBe("draft-1")
  })

  it("世界观简介面板展示只读版本并可提交刷新", async () => {
    worldBibleView._synopsis = {
      status: "fresh",
      stale: false,
      auto_refresh_enabled: false,
      current_revision: {
        id: "revision-1",
        version_number: 3,
        rendered_text: "只读世界观简介",
        token_estimate: 120,
        coverage_json: { source_count: 8 },
      },
      warnings: [],
    }
    api.world.refreshBibleSynopsis.mockResolvedValue({
      task_id: "task-synopsis",
      existing: false,
    })

    const html = worldBibleView._renderSynopsisPanel()
    expect(html).toContain("作者模式 · P1")
    expect(html).toContain("只读世界观简介")
    await worldBibleView._refreshSynopsis()

    expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1")
    expect(worldBibleView._synopsisTask.task_id).toBe("task-synopsis")
  })

  it("默认使用作者可读状态并把投影标识收进诊断信息", () => {
    worldBibleView._synopsis = {
      status: "failed",
      current_revision: null,
      warnings: ["raw warning"],
    }
    worldBibleView._activePage = { ...page, page_type: "faction" }
    worldBibleView._task = null

    const synopsisHtml = worldBibleView._renderSynopsisPanel()
    const pageHtml = worldBibleView._renderActivePage()

    expect(synopsisHtml).toContain("状态：生成失败")
    expect(synopsisHtml).not.toContain("World Core Brief")
    expect(synopsisHtml).toContain("诊断信息")
    expect(pageHtml).toContain("势力 ·")
    expect(pageHtml).toContain("上下文摘要尚未刷新")
    expect(pageHtml).toContain("本地恢复键")
    expect(pageHtml).toContain("worldBibleProjection:p1:page-1:context_brief")
  })

  it("不会把已经终止的简介任务重新挂回轮询并反复刷新页面", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
    api.world.getBibleSynopsis.mockResolvedValue({
      status: "failed",
      stale: true,
      active_task_id: "task-failed",
      auto_refresh_enabled: true,
    })
    worldBibleView._synopsisTerminalTaskId = "task-failed"
    const startPolling = vi.spyOn(worldBibleView, "_startSynopsisPolling")

    await worldBibleView._load()

    expect(startPolling).not.toHaveBeenCalled()
    startPolling.mockRestore()
  })

  it("世界书 AI 入口携带当前页跳转生成中心", () => {
    worldBibleView._activePage = page

    const result = worldBibleView._openInGenerationCenter()

    expect(result).toBe(true)
    expect(router.navigate).toHaveBeenCalledWith(
      "generate",
      null,
      true,
      expect.any(URLSearchParams),
    )
    const query = router.navigate.mock.calls[0][3]
    expect(query.get("tab")).toBe("world")
    expect(query.get("source_page_id")).toBe("page-1")
    expect(query.get("target")).toBe("world_bible_page")
  })

  it("世界书有未保存修改时先要求保存，不直接跳转生成中心", () => {
    worldBibleView._activePage = page
    document.body.innerHTML = worldBibleView._renderActivePage()
    document.getElementById("bible-free-text").value = "尚未保存的修改"

    const result = worldBibleView._openInGenerationCenter()

    expect(result).toBe(false)
    expect(showModal).toHaveBeenCalledWith(
      "保存后进入生成中心",
      expect.objectContaining({ html: expect.stringContaining("当前页面有未保存修改") }),
      expect.any(Array),
    )
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("世界书保存未提交修改成功后才携带精确页面 ID 跳转", async () => {
    worldBibleView._activePage = page
    document.body.innerHTML = worldBibleView._renderActivePage()
    document.getElementById("bible-free-text").value = "保存后转交的修改"
    api.world.createBibleDraft.mockResolvedValue({ id: "draft-1", page_id: "page-1" })
    api.world.updateBibleDraft.mockResolvedValue({
      id: "draft-1",
      page_id: "page-1",
      title: page.title,
      page_type: page.page_type,
      free_text: "保存后转交的修改",
      sections_json: [],
      linked_asset_refs_json: [],
    })

    worldBibleView._openInGenerationCenter()
    await clickModalButtonByText("保存并继续")

    expect(api.world.updateBibleDraft).toHaveBeenCalledWith(
      "draft-1",
      expect.objectContaining({ free_text: "保存后转交的修改" }),
      "p1",
    )
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("source_page_id")).toBe("page-1")
    expect(query.get("target")).toBe("world_bible_page")
  })

  it("世界书保存失败时留在当前页且不跳转", async () => {
    worldBibleView._activePage = page
    document.body.innerHTML = worldBibleView._renderActivePage()
    document.getElementById("bible-free-text").value = "保存会失败的修改"
    api.world.createBibleDraft.mockRejectedValue(new Error("保存服务不可用"))

    worldBibleView._openInGenerationCenter()
    await clickModalButtonByText("保存并继续")

    expect(router.navigate).not.toHaveBeenCalled()
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("保存服务不可用", "error")
  })

  it("创设建议弹窗用可读卡片展示而不是 raw JSON", async () => {
    api.world.listSuggestions.mockResolvedValue({
      items: [{
        id: "s1",
        review_group: "generation_center",
        target_type: "world_bible_page_draft",
        action_schema: "world_generation.page_draft.v1",
        risk_level: "low",
        payload_json: {
          page: {
            title: "补写当前页",
            page_type: "background",
            free_text: "<img src=x onerror=alert(1)>补写",
            sections_json: [],
          },
          source_refs: [{ source_type: "world_bible_page", title: "世界基本背景" }],
        },
      }],
      total: 1,
    })

    await worldBibleView._openSuggestions()

    const html = showModal.mock.calls[0][1].html
    expect(html).toContain("补写当前页")
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;补写")
    expect(html).not.toContain("\"sections_json\"")
  })

  it("整页建议编辑器可修改资产引用并与 sections 一起应用", async () => {
    const item = {
      id: "suggestion-assets",
      target_type: "world_bible_page_draft",
      payload_json: {
        page: {
          title: "北境规则",
          page_type: "background",
          free_text: "概览",
          sections_json: [],
          linked_asset_refs_json: [{ target_type: "core_entity", target_id: "entity-old" }],
        },
      },
    }
    worldBibleView._editSuggestionIntoDraft(item)
    const html = showModal.mock.calls.at(-1)[1].html
    expect(html).toContain('id="bible-suggestion-assets"')
    document.body.innerHTML = html
    document.getElementById("bible-suggestion-assets").value = JSON.stringify([
      { target_type: "core_entity", target_id: "entity-new" },
    ])
    api.generate.applyWorldPageDraft.mockResolvedValue({ draft: { id: "draft-assets", page_id: "page-1" } })
    const loadSpy = vi.spyOn(worldBibleView, "_load").mockResolvedValue()
    const openDraftSpy = vi.spyOn(worldBibleView, "_openDraft").mockImplementation(() => {})

    await worldBibleView._applyEditedSuggestion(item)

    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "suggestion-assets",
      expect.objectContaining({
        page: expect.objectContaining({
          linked_asset_refs_json: [{ target_type: "core_entity", target_id: "entity-new" }],
        }),
      }),
      "p1",
    )
    loadSpy.mockRestore()
    openDraftSpy.mockRestore()
  })

  it("世界书整页建议 409 使用与生成中心一致的不覆盖提示", async () => {
    const item = {
      id: "suggestion-conflict",
      payload_json: {
        page: {
          title: "规则",
          page_type: "background",
          free_text: "",
          sections_json: [],
          linked_asset_refs_json: [],
        },
      },
    }
    worldBibleView._editSuggestionIntoDraft(item)
    document.body.innerHTML = showModal.mock.calls.at(-1)[1].html
    const conflict = new Error("baseline drift")
    conflict.status = 409
    api.generate.applyWorldPageDraft.mockRejectedValue(conflict)

    await worldBibleView._applyEditedSuggestion(item)

    expect(toast).toHaveBeenCalledWith(
      "来源工作稿已变更，本次提案未覆盖新修改。请重新生成。",
      "warning",
    )
  })

  it("世界书编辑页不再内嵌第二套 AI 侧栏", () => {
    worldBibleView._activePage = page
    const html = worldBibleView._renderActivePage()

    expect(html).toContain('data-action="bible-improve-with-ai"')
    expect(html).not.toContain('class="bible-ai-sidebar"')
    expect(html).not.toContain('id="bible-ai-input"')
  })

  it("不兼容创设建议可点击并自动切换批量范围", () => {
    worldBibleView._suggestions = [
      {
        id: "s1",
        review_group: "generation_center",
        target_type: "core_entity_draft",
        action_schema: "world_generation.core_entity.v1",
        risk_level: "low",
        payload_json: { title: "新建页面" },
      },
      {
        id: "s2",
        review_group: "generation_center",
        target_type: "world_bible_page_draft",
        action_schema: "world_generation.page_draft.v1",
        risk_level: "low",
        payload_json: { page: { title: "整页提案", free_text: "重构当前页" } },
      },
    ]
    worldBibleView._suggestionBatchKey = worldBibleView._suggestionGroupKey(worldBibleView._suggestions[0])
    document.body.innerHTML = worldBibleView._renderSuggestionsModal()
    worldBibleView._bindSuggestionModal()

    const first = document.querySelector('[data-bible-batch-suggestion="s1"]')
    const second = document.querySelector('[data-bible-batch-suggestion="s2"]')
    expect(first.disabled).toBe(false)
    expect(second.disabled).toBe(false)
    expect(first.checked).toBe(true)
    expect(second.checked).toBe(false)

    second.checked = true
    second.dispatchEvent(new Event("change"))

    expect(first.checked).toBe(false)
    expect(second.checked).toBe(true)
    expect(document.querySelector("[data-bible-batch-meta]").textContent).toContain("world_bible_page_draft")
  })

  it("批量提交前会拦截不一致创设建议类型", async () => {
    worldBibleView._suggestions = [
      {
        id: "s1",
        review_group: "generation_center",
        target_type: "core_entity_draft",
        action_schema: "world_generation.core_entity.v1",
      },
      {
        id: "s2",
        review_group: "generation_center",
        target_type: "world_bible_page_draft",
        action_schema: "world_generation.page_draft.v1",
      },
    ]
    document.body.innerHTML = `
      <input type="checkbox" data-bible-batch-suggestion="s1" checked />
      <input type="checkbox" data-bible-batch-suggestion="s2" checked />
    `

    await worldBibleView._decideSuggestionBatch(true)

    expect(toast).toHaveBeenCalledWith("选中的建议类型不一致，请分别处理", "warning")
    expect(api.world.confirmSuggestion).not.toHaveBeenCalled()
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

  it("加载已归档类别供历史页面展示和恢复", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })

    await worldBibleView.render()

    expect(api.world.listBibleCategories).toHaveBeenCalledWith("p1", true)
  })

  it("从图鉴打开正式页时不会泄漏另一个新页工作稿", () => {
    worldBibleView._pages = [speciesPage]
    worldBibleView._drafts = [{ id: "draft-new", page_id: null, title: "新页工作稿" }]
    worldBibleView._activeDraft = worldBibleView._drafts[0]

    worldBibleView._openPageCard("page-2")

    expect(worldBibleView._activePage.id).toBe("page-2")
    expect(worldBibleView._activeDraft).toBeNull()
  })

  it("发布 CAS 冲突时保留服务器已保存的最新工作稿", async () => {
    const staleDraft = {
      id: "draft-1",
      page_id: "page-1",
      title: page.title,
      page_type: page.page_type,
      free_text: "旧工作稿",
      linked_asset_refs_json: [],
      sort_order: 0,
    }
    const savedDraft = { ...staleDraft, free_text: "已保存的作者改动" }
    worldBibleView._activePage = { ...page, status: "canonical" }
    worldBibleView._activeDraft = staleDraft
    worldBibleView._drafts = [staleDraft]
    api.world.updateBibleDraft.mockResolvedValue(savedDraft)
    const conflict = new Error("version conflict")
    conflict.status = 409
    api.world.publishBibleDraft.mockRejectedValue(conflict)
    document.body.innerHTML = worldBibleView._renderActivePage()
    document.getElementById("bible-free-text").value = savedDraft.free_text

    await worldBibleView._publishDraft()

    expect(worldBibleView._activeDraft).toEqual(savedDraft)
    expect(worldBibleView._drafts[0]).toEqual(savedDraft)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("工作稿已保留"), "error")
  })

  it("已归档自定义类别可恢复", async () => {
    api.world.updateBibleCategory.mockResolvedValue({ id: "category-1", status: "active" })
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })

    await worldBibleView._restoreCategory("category-1")

    expect(api.world.updateBibleCategory).toHaveBeenCalledWith(
      "category-1",
      { status: "active" },
      "p1",
    )
    expect(toast).toHaveBeenCalledWith("类别已恢复，可重新用于工作稿", "success")
  })

  it("固定简介时阻止直接刷新，取消固定会显式提交刷新", async () => {
    worldBibleView._synopsis = { pinned: true, auto_refresh_enabled: false }

    expect(await worldBibleView._refreshSynopsis()).toBe(false)
    expect(api.world.refreshBibleSynopsis).not.toHaveBeenCalled()

    api.world.unpinBibleSynopsis.mockResolvedValue({ pinned: false, stale: true })
    api.world.refreshBibleSynopsis.mockResolvedValue({ task_id: "task-refresh", existing: false })
    await worldBibleView._unpinSynopsis()

    expect(api.world.unpinBibleSynopsis).toHaveBeenCalledWith("p1")
    expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1")
    expect(worldBibleView._synopsisTask.task_id).toBe("task-refresh")
  })
})
