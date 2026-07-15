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
  worldBibleView._suggestions = []
  worldBibleView._suggestionBatchKey = null
  worldBibleView._conflicts = []
  worldBibleView._task = null
  worldBibleView._projectionConflictHint = null
  worldBibleView._projectionRetryPending = false
  worldBibleView._aiOpen = false
  worldBibleView._aiMessages = []
  worldBibleView._aiOutputTarget = "chat"
  worldBibleView._aiTemplateId = "builtin:none"
  worldBibleView._aiQualityMode = "fast"
  worldBibleView._aiSelectedChapters = ""
  worldBibleView._aiIncludeSynopsis = true
  worldBibleView._aiResult = null
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
      source_module: "world_bible",
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
    expect(html).toContain('data-bible-edit-suggestion="s1"')
    expect(html).not.toContain('data-bible-confirm-suggestion="s1"')
    expect(html).toContain('data-bible-reject-suggestion="s1"')
  })

  it("编辑后的页面建议只应用到工作稿", async () => {
    const suggestion = {
      id: "s1",
      target_type: "world_bible_page_patch",
      payload_json: { append_text: "AI 原文" },
    }
    worldBibleView._suggestions = [suggestion]
    api.world.applySuggestionToBibleDraft.mockResolvedValue({
      result_ref_json: { type: "world_bible_page_draft", id: "draft-1" },
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

    expect(api.world.applySuggestionToBibleDraft).toHaveBeenCalledWith(
      "s1",
      { append_text: "作者编辑稿" },
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
        include_world_synopsis: true,
        messages: [{ role: "user", content: "帮我补写这一页" }],
      }),
      "p1",
    )
    expect(worldBibleView._aiResult.suggestions[0].id).toBe("s1")
    expect(toast).toHaveBeenCalledWith("建议已生成；页面建议编辑后只会写入工作稿", "success")
  })

  it("世界书 AI 拒绝超过服务上限的章节附件", async () => {
    worldBibleView._activePage = page
    worldBibleView._aiSelectedChapters = Array.from(
      { length: 21 },
      (_, index) => String(index + 1),
    ).join(",")

    const result = await worldBibleView._runAi("page_patch")

    expect(result).toBe(false)
    expect(api.world.generateBiblePageAi).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("每次最多附带 20 章正文", "warning")
  })

  it("世界书 AI 只发送最近 40 条聊天记录", async () => {
    worldBibleView._activePage = page
    worldBibleView._aiMessages = Array.from({ length: 41 }, (_, index) => ({
      role: index % 2 ? "assistant" : "user",
      content: `message-${index + 1}`,
    }))
    api.world.generateBiblePageAi.mockResolvedValue({ reply: "ok" })

    await worldBibleView._runAi("page_patch")

    const payload = api.world.generateBiblePageAi.mock.calls[0][1]
    expect(payload.messages).toHaveLength(40)
    expect(payload.messages[0].content).toBe("message-2")
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

  it("世界书 AI 侧栏使用语义类并保留动态内容转义", () => {
    worldBibleView._activePage = page
    worldBibleView._aiOpen = true
    worldBibleView._aiMessages = [{ role: "user", content: "<img src=x onerror=alert(1)>" }]

    const html = worldBibleView._renderAiSidebar(page)

    expect(html).toContain('class="bible-ai-sidebar"')
    expect(html).toContain("bible-ai-message--user")
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;")
    expect(html).not.toContain("<img src=x")
  })

  it("不兼容创设建议可点击并自动切换批量范围", () => {
    worldBibleView._suggestions = [
      {
        id: "s1",
        review_group: "world_bible_ai",
        target_type: "world_bible_page",
        action_schema: "world_bible_ai.v1",
        risk_level: "low",
        payload_json: { title: "新建页面" },
      },
      {
        id: "s2",
        review_group: "world_bible_ai",
        target_type: "world_bible_page_patch",
        action_schema: "world_bible_ai.v1",
        risk_level: "low",
        payload_json: { append_text: "补写当前页" },
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
    expect(document.querySelector("[data-bible-batch-meta]").textContent).toContain("world_bible_page_patch")
  })

  it("批量提交前会拦截不一致创设建议类型", async () => {
    worldBibleView._suggestions = [
      {
        id: "s1",
        review_group: "world_bible_ai",
        target_type: "world_bible_page",
        action_schema: "world_bible_ai.v1",
      },
      {
        id: "s2",
        review_group: "world_bible_ai",
        target_type: "world_bible_page_patch",
        action_schema: "world_bible_ai.v1",
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
