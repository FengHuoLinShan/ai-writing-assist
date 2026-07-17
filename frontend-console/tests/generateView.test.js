import { describe, it, expect, vi, beforeEach } from "vitest"
import generateView from "../views/generateView.js"

beforeEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
  localStorage.clear()
  generateView._destroyTaskReferencePickers()
  document.body.innerHTML = ""
  state.currentProjectId = "p1"
  generateView._selectedTemplateId = "builtin:none"
  generateView._templates = []
  generateView._templatesLoaded = false
  generateView._templateLoadError = null
  generateView._activationProfiles = []
  generateView._activationProfilesLoaded = false
  generateView._activationProfileId = null
  generateView._messages = []
  generateView._selectedChapters = []
  generateView._povChapters = []
  generateView._povScenes = []
  generateView._povCharacters = []
  generateView._povForm = {
    chapterIndex: null,
    sceneId: "",
    viewpointCharacterId: "",
    instruction: "",
  }
  generateView._lastPovSubmission = null
  generateView._povLoadWarning = null
  generateView._qualityMode = "fast"
  generateView._includeWorldSynopsis = true
  generateView._lastEntity = null
  generateView._lastWorldResult = null
  generateView._lastWorldSuggestionId = null
  generateView._routeSourcePageId = null
  generateView._worldTargetKind = "core_entity"
  generateView._sourcePage = null
  generateView._sourceDraft = null
  generateView._worldCategories = []
  generateView._worldPageTemplates = []
  generateView._worldScenes = []
  generateView._worldThreads = []
  generateView._worldCharacters = []
  generateView._worldEntities = []
  generateView._selectedSceneId = ""
  generateView._selectedThreadIds = []
  generateView._selectedCharacterIds = []
  generateView._selectedEntityIds = []
  generateView._newPageType = "custom"
  generateView._newPageTemplateKey = ""
  generateView._worldWorkspaceWarning = null
  generateView._lastContextUsage = null
  generateView._lastChatContextUsage = null
  generateView._lastEntityContextUsage = null
  generateView._busy = false
  generateView._abortControllers = null
  generateView._generateSubTab = "world"
  generateView._taskPreset = "custom"
  generateView._taskForm = {
    task: "",
    scope: "arc",
    reveal_mode: "author_safe",
    budget_tokens: 0,
    entity_ids: undefined,
    character_ids: undefined,
    viewpoint_character_id: undefined,
    chapter_index: undefined,
    scene_id: undefined,
    include_world_synopsis: true,
  }
  generateView._lastContextBundle = null
  generateView._lastContextSource = null
  generateView._lastContextMarkdown = null
  generateView._lastContextRequestParams = null
  generateView._activeStorageKey = generateView._storageKey()
  generateView._storageDirty = false
  generateView._storageNotices = new Set()
  generateView._requestEpoch = 0
  generateView._composerDraft = ""
  generateView._composerDrafts = new Map()
  generateView._pageProposalDirty = false
  api.generate.listPromptTemplates.mockResolvedValue({
    items: [
      {
        id: "builtin:none",
        name: "不带模板",
        object_template: "none",
        prompt_text: "不预设对象类型",
        is_builtin: true,
        version_number: 1,
      },
      {
        id: "builtin:character",
        name: "人物",
        object_template: "character",
        prompt_text: "聚焦人物卡",
        is_builtin: true,
        version_number: 1,
      },
    ],
    total: 2,
  })
  api.generate.createPromptTemplate.mockResolvedValue({
    id: "tpl-1",
    name: "DND 圣骑士",
    object_template: "custom",
    prompt_text: "生成 DND 圣骑士对象",
    is_builtin: false,
    version_number: 1,
  })
  api.generate.copyPromptTemplate.mockResolvedValue({
    id: "tpl-copy-1",
    name: "人物",
    object_template: "character",
    prompt_text: "聚焦人物卡",
    is_builtin: false,
    version_number: 1,
  })
  api.generate.updatePromptTemplate.mockResolvedValue({
    id: "tpl-copy-1",
    name: "人物",
    object_template: "character",
    prompt_text: "人物模板：必须写清楚誓言与代价。",
    is_builtin: false,
    version_number: 2,
  })
  api.generate.listPromptTemplateRevisions.mockResolvedValue([])
  api.context.compile.mockResolvedValue({
    total_tokens: 1200,
    budget_tokens: 4000,
    scope: "arc",
    reveal_mode: "author_full",
    sections: [
      { key: "project", tier: "core", token_count: 200, truncated: false },
      { key: "characters", tier: "standard", token_count: 1000, truncated: true },
    ],
    evicted: ["rag_chunks"],
    truncated: ["characters"],
    warnings: [],
  })
  api.context.render.mockResolvedValue({ markdown: "# 上下文\n\n测试内容" })
  api.context.listActivationProfiles = vi.fn().mockResolvedValue({ items: [] })
  api.writing.listChapters.mockResolvedValue({ chapters: [] })
  api.outline.listScenesByChapter.mockResolvedValue([])
  api.world.listCharacters.mockResolvedValue({ items: [], total: 0 })
  api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
  api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
  api.world.listBibleDrafts.mockResolvedValue({ items: [], total: 0 })
  api.world.listBibleCategories.mockResolvedValue({ items: [{ category_key: "custom", name: "自定义", status: "active" }] })
  api.world.listBiblePageTemplates.mockResolvedValue({ items: [], total: 0 })
  api.world.listSuggestions.mockResolvedValue({ items: [], total: 0 })
  api.outline.listScenesOrdered.mockResolvedValue([])
  api.outline.listThreads.mockResolvedValue({ items: [] })
  api.writing.generate.mockResolvedValue({ task_id: "task-1" })
  api.tasks.get.mockResolvedValue({
    task_id: "task-1",
    status: "done",
    progress: 1,
    result: { draft_id: "draft-pov-1", chapter_index: 1 },
  })
})

function mountAiReferenceModalShell() {
  document.body.insertAdjacentHTML("beforeend", `
    <div id="modal-overlay" class="hidden">
      <div id="modal-title"></div>
      <div id="modal-body"></div>
      <div id="modal-footer"></div>
    </div>
  `)
}

describe("generateView bounded local state", () => {
  it("生成中心只把显式选择的已发布 Activation Profile 放入请求", async () => {
    api.context.listActivationProfiles.mockResolvedValue({
      items: [
        { id: "published-1", name: "写作规则", version_number: 3, status: "published" },
        { id: "draft-1", name: "工作稿", version_number: 4, status: "draft" },
      ],
    })
    await generateView._loadActivationProfiles()
    generateView._activationProfileId = "published-1"

    expect(generateView._activationProfiles.map((item) => item.id)).toEqual(["published-1"])
    expect(generateView._buildPayload()).toEqual(expect.objectContaining({
      activation_profile_id: "published-1",
    }))
  })

  it("measures the 512 KiB limit in UTF-8 bytes instead of JavaScript characters", () => {
    const storageKey = generateView._storageKey()
    const previous = JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧快照" }] })
    localStorage.setItem(storageKey, previous)
    generateView._messages = [{ role: "user", content: "界".repeat(180_000) }]

    expect(JSON.stringify(generateView._persistedState()).length).toBeLessThan(512 * 1024)
    expect(generateView._persistState()).toBe(false)
    expect(localStorage.getItem(storageKey)).toBe(previous)
  })

  it("oversized history keeps the latest 40 messages and reports compaction", () => {
    generateView._messages = Array.from({ length: 80 }, (_, index) => ({
      role: index % 2 ? "assistant" : "user",
      content: `${index}:` + "x".repeat(10_000),
    }))

    expect(generateView._persistState()).toBe(true)

    const stored = JSON.parse(localStorage.getItem(generateView._storageKey()))
    expect(stored.messages).toHaveLength(40)
    expect(stored.messages[0].content.startsWith("40:")).toBe(true)
    expect(stored.messages.at(-1).content.startsWith("79:")).toBe(true)
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("最近 40 条对话"),
      "warning",
    )
  })

  it("不把可重建的预览正文写入 v2 本地会话", () => {
    generateView._messages = Array.from({ length: 30 }, (_, index) => ({
      role: "user",
      content: `${index}:` + "x".repeat(10_000),
    }))
    generateView._lastContextBundle = { markdown: "y".repeat(300_000) }

    expect(generateView._persistState()).toBe(true)

    const stored = JSON.parse(localStorage.getItem(generateView._storageKey()))
    expect(stored).not.toHaveProperty("lastContextBundle")
    expect(stored.messages).toHaveLength(30)
    expect(stored.messages[0].content.startsWith("0:")).toBe(true)
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("预览数据"), "warning")
  })

  it("single oversized message does not overwrite the previous snapshot", () => {
    const storageKey = generateView._storageKey()
    const previous = JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧快照" }] })
    localStorage.setItem(storageKey, previous)
    generateView._messages = [{ role: "user", content: "x".repeat(600 * 1024) }]

    expect(generateView._persistState()).toBe(false)

    expect(localStorage.getItem(storageKey)).toBe(previous)
    expect(generateView._storageDirty).toBe(true)
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("超过 512 KiB 保存上限"),
      "warning",
    )
  })

  it("keeps at most five project snapshots and evicts the oldest", () => {
    for (let index = 1; index <= 5; index += 1) {
      localStorage.setItem(
        `generate_world_workspace_state_v2_old-${index}_project_core_entity`,
        JSON.stringify({ savedAt: index, messages: [] }),
      )
    }
    state.currentProjectId = "new-project"
    generateView._activeStorageKey = generateView._storageKey()

    expect(generateView._persistState()).toBe(true)

    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((key) => key.startsWith("generate_world_workspace_state_v2_"))
    expect(keys).toHaveLength(5)
    expect(keys).toContain("generate_world_workspace_state_v2_new-project_project_core_entity")
    expect(keys).not.toContain("generate_world_workspace_state_v2_old-1_project_core_entity")
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("最久未使用的项目缓存"),
      "warning",
    )
  })

  it("quota failure is visible and leaves current in-memory state dirty", () => {
    const quotaError = new Error("quota")
    quotaError.name = "QuotaExceededError"
    const setItem = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw quotaError
    })
    generateView._messages = [{ role: "user", content: "尚未保存" }]

    expect(generateView._persistState()).toBe(false)

    expect(generateView._storageDirty).toBe(true)
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("本地会话保存失败"),
      "warning",
    )
    setItem.mockRestore()
  })

  it("quota failure evicts only the oldest generate snapshot and retries the write", () => {
    localStorage.setItem("unrelated-module-state", "keep")
    localStorage.setItem(
      "generate_world_workspace_state_v2_oldest_project_core_entity",
      JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "oldest" }] }),
    )
    localStorage.setItem(
      "generate_world_workspace_state_v2_recent_project_core_entity",
      JSON.stringify({ savedAt: 2, messages: [{ role: "user", content: "recent" }] }),
    )
    const originalSetItem = localStorage.setItem.bind(localStorage)
    let currentWriteAttempts = 0
    const setItem = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (key === generateView._storageKey() && currentWriteAttempts++ === 0) {
        const quotaError = new Error("quota")
        quotaError.name = "QuotaExceededError"
        throw quotaError
      }
      originalSetItem(key, value)
    })
    generateView._messages = [{ role: "user", content: "current" }]

    expect(generateView._persistState()).toBe(true)

    expect(currentWriteAttempts).toBe(2)
    expect(localStorage.getItem("generate_world_workspace_state_v2_oldest_project_core_entity")).toBeNull()
    expect(localStorage.getItem("generate_world_workspace_state_v2_recent_project_core_entity")).toContain("recent")
    expect(localStorage.getItem("unrelated-module-state")).toBe("keep")
    expect(localStorage.getItem(generateView._storageKey())).toContain("current")
    setItem.mockRestore()
  })

  it("does not loop forever when a storage implementation refuses to remove an eviction candidate", () => {
    localStorage.setItem(
      "generate_world_workspace_state_v2_oldest_project_core_entity",
      JSON.stringify({ savedAt: 1, messages: [] }),
    )
    const quotaError = new Error("quota")
    quotaError.name = "QuotaExceededError"
    const setItem = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw quotaError
    })
    const removeItem = vi.spyOn(localStorage, "removeItem").mockImplementation(() => {})

    expect(generateView._persistState()).toBe(false)

    expect(setItem).toHaveBeenCalledTimes(1)
    expect(removeItem).toHaveBeenCalledTimes(1)
    setItem.mockRestore()
    removeItem.mockRestore()
  })

  it("corrupted snapshot is removed with a visible warning", () => {
    const storageKey = generateView._storageKey()
    localStorage.setItem(storageKey, "{broken")

    generateView._restoreState(storageKey)

    expect(localStorage.getItem(storageKey)).toBeNull()
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("本地会话已损坏"),
      "warning",
    )
  })

  it("treats valid JSON with an invalid state shape as corrupted", () => {
    const storageKey = generateView._storageKey()
    localStorage.setItem(storageKey, JSON.stringify({ messages: "not-an-array" }))

    generateView._restoreState(storageKey)

    expect(localStorage.getItem(storageKey)).toBeNull()
    expect(generateView._messages).toEqual([])
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("本地会话已损坏"),
      "warning",
    )
  })

  it("reports disabled storage once per project without a toast storm", () => {
    const getItem = vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new DOMException("disabled", "SecurityError")
    })

    generateView._restoreState(generateView._storageKey())
    generateView._restoreState(generateView._storageKey())

    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("无法读取生成中心本地会话"),
      "warning",
    )
    getItem.mockRestore()
  })

  it("不迁移旧 v1 会话", () => {
    localStorage.setItem("generate_chatbox_state_v1_p1", JSON.stringify({
      selectedTemplateId: "builtin:character",
      messages: [{ role: "user", content: "旧版会话" }],
    }))

    generateView._resetProjectState()
    generateView._restoreState(generateView._storageKey())

    expect(generateView._selectedTemplateId).toBe("builtin:none")
    expect(generateView._messages).toEqual([])
  })

  it("switching projects resets unsaved project-scoped state before restore", () => {
    const destroyPicker = vi.fn()
    generateView._taskReferencePickers = { scene: { destroy: destroyPicker } }
    generateView._messages = [{ role: "user", content: "项目一私有内容" }]
    generateView._lastContextBundle = { project: "p1" }
    state.currentProjectId = "p2"

    generateView._activateProjectState()

    expect(generateView._activeStorageKey).toBe("generate_world_workspace_state_v2_p2_project_core_entity")
    expect(generateView._messages).toEqual([])
    expect(generateView._lastContextBundle).toBeNull()
    expect(generateView._selectedTemplateId).toBe("builtin:none")
    expect(destroyPicker).toHaveBeenCalledOnce()
    expect(generateView._taskReferencePickers).toBeNull()
    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_project_core_entity")).toContain("项目一私有内容")
    expect(localStorage.getItem("generate_world_workspace_state_v2_p2_project_core_entity")).toBeNull()
  })

  it("restores only the destination project after saving the previous project", () => {
    localStorage.setItem("generate_world_workspace_state_v2_p2_project_core_entity", JSON.stringify({
      savedAt: 2,
      messages: [{ role: "user", content: "项目二快照" }],
    }))
    generateView._messages = [{ role: "user", content: "项目一当前内容" }]
    state.currentProjectId = "p2"

    generateView._activateProjectState()

    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_project_core_entity")).toContain("项目一当前内容")
    expect(generateView._messages).toEqual([{ role: "user", content: "项目二快照" }])
  })

  it("persists to the active project when global selection changes before teardown", () => {
    generateView._messages = [{ role: "user", content: "项目一私有内容" }]
    state.currentProjectId = "p2"

    expect(generateView._persistState()).toBe(true)

    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_project_core_entity")).toContain("项目一私有内容")
    expect(localStorage.getItem("generate_world_workspace_state_v2_p2_project_core_entity")).toBeNull()
  })

  it("does not overwrite newer in-memory state with an older snapshot for the active project", () => {
    localStorage.setItem(generateView._storageKey(), JSON.stringify({
      savedAt: 1,
      messages: [{ role: "user", content: "旧快照" }],
    }))
    generateView._messages = [{ role: "user", content: "当前未保存内容" }]

    generateView._activateProjectState()

    expect(generateView._messages).toEqual([{ role: "user", content: "当前未保存内容" }])
  })

  it("按来源页面与目标隔离 world v2 会话", () => {
    generateView._messages = [{ role: "user", content: "项目级对象讨论" }]

    generateView._activateProjectState("page-1", "world_bible_page")
    expect(generateView._messages).toEqual([])
    generateView._messages = [{ role: "user", content: "第一页完善讨论" }]

    generateView._activateProjectState("page-1", "core_entity")
    expect(generateView._messages).toEqual([])
    generateView._messages = [{ role: "user", content: "基于第一页创建对象" }]

    generateView._activateProjectState("page-1", "world_bible_page")
    expect(generateView._messages).toEqual([{ role: "user", content: "第一页完善讨论" }])
    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_project_core_entity")).toContain("项目级对象讨论")
    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_page-1_core_entity")).toContain("基于第一页创建对象")
  })

  it("按 v2 会话在内存中保留各自未发送的 composer 草稿", () => {
    generateView._composerDraft = "项目级未发送内容"
    generateView._rememberComposerDraft()

    generateView._activateProjectState("page-1", "world_bible_page")
    expect(generateView._composerDraft).toBe("")
    generateView._composerDraft = "第一页未发送内容"
    generateView._rememberComposerDraft()

    generateView._activateProjectState(null, "core_entity")

    expect(generateView._composerDraft).toBe("项目级未发送内容")
    expect(generateView._composerDrafts.get("generate_world_workspace_state_v2_p1_page-1_world_bible_page"))
      .toBe("第一页未发送内容")
  })

  it("旧 target 的迟到生成响应不会写入新 target 会话", async () => {
    let resolveRequest
    api.generate.generateWorldSuggestion.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    generateView._messages = [{ role: "user", content: "完善当前页" }]
    document.body.innerHTML = await generateView.render()

    const pending = generateView._generateWorldSuggestion()
    await new Promise((resolve) => setTimeout(resolve, 0))
    const oldSignal = api.generate.generateWorldSuggestion.mock.calls[0][1].signal
    generateView._activateProjectState(null, "world_bible_new_page")
    expect(oldSignal.aborted).toBe(true)

    resolveRequest({
      result: {
        kind: "core_entity",
        suggestion: { id: "stale-suggestion", payload_json: { name: "迟到对象" } },
      },
    })
    await pending

    expect(generateView._lastWorldResult).toBeNull()
    expect(generateView._lastWorldSuggestionId).toBeNull()
    expect(localStorage.getItem("generate_world_workspace_state_v2_p1_project_world_bible_new_page") || "")
      .not.toContain("stale-suggestion")
  })

  it("整页提案有未应用编辑时阻止离开", () => {
    generateView._pageProposalDirty = true
    const originalConfirm = window.confirm
    const confirm = vi.fn().mockReturnValue(false)
    window.confirm = confirm

    expect(generateView.canLeave()).toBe(false)
    expect(generateView._pageProposalDirty).toBe(true)

    confirm.mockReturnValue(true)
    expect(generateView.canLeave()).toBe(true)
    expect(generateView._pageProposalDirty).toBe(false)
    window.confirm = originalConfirm
  })
})

describe("generateView chatbox", () => {
  it("初始页面显示 Chatbox、模板、高质量和生成按钮", async () => {
    const html = await generateView.render()

    expect(html).toContain("不带模板")
    expect(html).toContain("人物")
    expect(html).toContain("编辑对象模板")
    expect(html).toContain("高质量")
    expect(html).toContain("说明你想创造、推敲或重构的世界设定")
    expect(html).toContain("生成世界对象建议")
    expect(html).toContain("世界设定")
    expect(html).toContain("角色视角正文")
    expect(html).toContain("任务")
    expect(html).toContain("上下文预览")
    expect(html).not.toContain("generate-pasted-context")
  })

  it("自由对话渲染顶部工具栏，并把模板行移到工具栏下方", async () => {
    state.currentProject = { id: "p1", title: "测试项目" }
    const html = await generateView.render()

    expect(html).toContain("generate-toolbar")
    expect(html).toContain("世界设定")
    expect(html).toContain("测试项目")
    expect(html).toContain('data-action="send-chat-message"')
    expect(html).toContain('data-action="generate-world-suggestion"')
    expect(html).toContain("generate-template-row--toolbar")
  })

  it("在页面标题栏挂载生成中心说明，离开时清理", () => {
    document.body.innerHTML = `
      <div class="topbar-center"><span id="topbar-module">生成中心</span></div>
    `

    generateView._mountTopbarNote()

    expect(document.getElementById("topbar-generate-note")?.textContent).toBe("先自由聊，确定后再生成待处理建议。")

    generateView.onLeave()

    expect(document.getElementById("topbar-generate-note")).toBeNull()
  })

  it("发送自由聊天只调用 chat 接口，不调用结构化生成和 context confirm", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.worldChat.mockResolvedValue({ reply: "可以设计成旧友型反派" })
    document.getElementById("generate-chat-input").value = "帮我设计一个反派"

    await generateView._sendChatMessage()

    expect(api.generate.worldChat).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        source_context: { kind: "project" },
        target: expect.objectContaining({ kind: "core_entity", template: "none" }),
        quality_mode: "fast",
        messages: [{ role: "user", content: "帮我设计一个反派" }],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(api.context.confirm).not.toHaveBeenCalled()
    expect(document.getElementById("generate-chat-messages")?.innerHTML).toContain("旧友型反派")
  })

  it("聊天请求失败时在聊天流里显示错误，不只依赖 toast", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.worldChat.mockRejectedValue(new Error("请求超时"))
    document.getElementById("generate-chat-input").value = "设计一个典型 dnd 圣骑士"

    await generateView._sendChatMessage()

    const html = document.getElementById("generate-chat-messages")?.innerHTML || ""
    expect(html).toContain("设计一个典型 dnd 圣骑士")
    expect(html).toContain("聊天失败：请求超时")
    expect(api.generate.worldChat).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "设计一个典型 dnd 圣骑士" }],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(toast).toHaveBeenCalledWith("聊天失败：请求超时", "error")
  })

  it("主输入框粘贴已有对话后直接点击生成，会把输入内容作为生成上下文", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: {
        kind: "core_entity",
        suggestion: { id: "s1", status: "pending", payload_json: { name: "沈无咎", entity_type: "character", summary: "旧友型反派" } },
      },
    })
    document.getElementById("generate-chat-input").value = "外部 Chatbox：反派不是纯恶人。"

    await generateView._generateWorldSuggestion()

    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "外部 Chatbox：反派不是纯恶人。" }],
        quality_mode: "fast",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(document.getElementById("generate-result")?.innerHTML).toContain("沈无咎")
    expect(document.getElementById("generate-chat-input").value).toBe("")
  })

  it("编辑内置模板会创建项目级副本并保存提示词", async () => {
    document.body.innerHTML = await generateView.render()

    generateView._openTemplateEditor()

    expect(showModal).toHaveBeenCalledWith(
      "编辑模板",
      expect.objectContaining({ html: expect.stringContaining("不预设对象类型") }),
      expect.any(Array),
    )

    document.body.insertAdjacentHTML("beforeend", generateView._renderTemplateEditor("builtin:character"))
    document.getElementById("generate-template-editor-select").value = "builtin:character"
    document.getElementById("generate-template-editor-prompt").value = "人物模板：必须写清楚誓言与代价。"
    api.generate.listPromptTemplates.mockResolvedValue({
      items: [
        {
          id: "builtin:none",
          name: "不带模板",
          object_template: "none",
          prompt_text: "不预设对象类型",
          is_builtin: true,
          version_number: 1,
        },
        {
          id: "builtin:character",
          name: "人物",
          object_template: "character",
          prompt_text: "聚焦人物卡",
          is_builtin: true,
          version_number: 1,
        },
        {
          id: "tpl-copy-1",
          name: "人物",
          object_template: "character",
          prompt_text: "人物模板：必须写清楚誓言与代价。",
          is_builtin: false,
          version_number: 2,
        },
      ],
      total: 3,
    })

    await generateView._saveTemplateFromEditor()

    expect(api.generate.copyPromptTemplate).toHaveBeenCalledWith(
      "builtin:character",
      expect.objectContaining({ novel_id: "p1" }),
    )
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith(
      "tpl-copy-1",
      "p1",
      expect.objectContaining({ prompt_text: "人物模板：必须写清楚誓言与代价。" }),
    )
    generateView._messages = [{ role: "user", content: "设计一个圣骑士" }]
    generateView._selectedTemplateId = "tpl-copy-1"

    expect(generateView._buildPayload().target).toEqual(expect.objectContaining({
      kind: "core_entity",
      template_id: "tpl-copy-1",
      template_version: 2,
      template: "character",
      template_name: "人物",
      template_prompt: "人物模板：必须写清楚誓言与代价。",
    }))
  })

  it("自定义模板可加载历史版本到编辑器但不自动保存", async () => {
    generateView._templates = [{
      id: "tpl-1",
      value: "tpl-1",
      label: "人物模板",
      prompt: "当前版本",
      object_template: "character",
      is_builtin: false,
      version_number: 3,
    }]
    generateView._templatesLoaded = true
    api.generate.listPromptTemplateRevisions.mockResolvedValue([
      {
        id: "rev-2",
        template_id: "tpl-1",
        version_number: 2,
        name: "人物模板旧版",
        prompt_text: "旧版本提示词 <script>",
        validation_state: "valid",
        created_at: "2026-07-11T10:00:00Z",
      },
    ])
    document.body.innerHTML = generateView._renderTemplateEditor("tpl-1")
    generateView._bindTemplateEditor()

    document.getElementById("generate-template-history-load").click()
    await vi.waitFor(() => {
      expect(api.generate.listPromptTemplateRevisions).toHaveBeenCalledWith("tpl-1", "p1")
    })

    const history = document.getElementById("generate-template-history")
    expect(history.innerHTML).toContain("v2")
    expect(history.innerHTML).toContain("&lt;script&gt;")
    expect(history.querySelector("script")).toBeNull()
    history.querySelector("[data-template-revision-index='0']").click()

    expect(document.getElementById("generate-template-editor-name").value).toBe("人物模板旧版")
    expect(document.getElementById("generate-template-editor-prompt").value).toBe("旧版本提示词 <script>")
    expect(document.querySelector(".generate-template-editor-help").textContent).toContain("内容尚未保存")
    expect(api.generate.updatePromptTemplate).not.toHaveBeenCalled()
  })

  it("可以创建新提示词模板并用于生成 payload", async () => {
    document.body.innerHTML = await generateView.render()
    document.body.insertAdjacentHTML("beforeend", generateView._renderTemplateEditor("builtin:none"))
    document.getElementById("generate-template-editor-name").value = "DND 圣骑士"
    document.getElementById("generate-template-editor-prompt").value = "生成 DND 圣骑士对象，突出誓言、神术、阵营冲突。"
    api.generate.listPromptTemplates.mockResolvedValue({
      items: [
        {
          id: "builtin:none",
          name: "不带模板",
          object_template: "none",
          prompt_text: "不预设对象类型",
          is_builtin: true,
          version_number: 1,
        },
        {
          id: "tpl-1",
          name: "DND 圣骑士",
          object_template: "custom",
          prompt_text: "生成 DND 圣骑士对象",
          is_builtin: false,
          version_number: 1,
        },
      ],
      total: 2,
    })

    await generateView._createTemplateFromEditor()

    expect(api.generate.createPromptTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        name: "DND 圣骑士",
        object_template: "custom",
        prompt_text: "生成 DND 圣骑士对象，突出誓言、神术、阵营冲突。",
      }),
    )
    expect(document.getElementById("generate-template-row")?.textContent).toContain("DND 圣骑士")
    expect(generateView._buildPayload().target).toEqual(expect.objectContaining({
      kind: "core_entity",
      template_id: "tpl-1",
      template_version: 1,
      template: "custom",
      template_name: "DND 圣骑士",
      template_prompt: "生成 DND 圣骑士对象",
    }))
  })

  it("模板加载失败时降级到前端内置模板", async () => {
    api.generate.listPromptTemplates.mockRejectedValue(new Error("网络错误"))
    const html = await generateView.render()

    expect(html).toContain("不带模板")
    expect(html).toContain("人物")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("模板加载失败"), "warning")
  })

  it("勾选高质量后提交 pro，否则提交 fast", async () => {
    document.body.innerHTML = await generateView.render()
    generateView._messages = [{ role: "user", content: "生成一个反派" }]
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: { kind: "core_entity", suggestion: { id: "s1", payload_json: { name: "普通草稿", entity_type: "character" } } },
    })

    await generateView._generateWorldSuggestion()
    expect(api.generate.generateWorldSuggestion).toHaveBeenLastCalledWith(
      expect.objectContaining({ quality_mode: "fast" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    document.getElementById("generate-quality-pro").checked = true
    await generateView._generateWorldSuggestion()
    expect(api.generate.generateWorldSuggestion).toHaveBeenLastCalledWith(
      expect.objectContaining({ quality_mode: "pro" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it("章节选择弹窗显示标题和摘录，多选后回填附件区", async () => {
    document.body.innerHTML = await generateView.render()
    api.writing.listChapters.mockResolvedValue({
      chapters: [{ id: "d1", chapter_index: 1, title: "旧怨" }],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      title: "旧怨",
      content: "主角在雨夜背叛了旧友，旧友从此消失。",
    })

    await generateView._openChapterPicker()

    expect(showModal).toHaveBeenCalledWith(
      "选择附带正文",
      expect.objectContaining({ html: expect.stringContaining("主角在雨夜背叛") }),
      expect.any(Array),
    )
    document.body.insertAdjacentHTML("beforeend", showModal.mock.calls[0][1].html)
    document.getElementById("generate-chapter-1").checked = true
    showModal.mock.calls[0][2][1].handler()

    expect(generateView._selectedChapters).toEqual([
      expect.objectContaining({ chapter_index: 1, title: "旧怨" }),
    ])
    expect(document.getElementById("generate-selected-chapters")?.textContent).toContain("第1章")
  })

  it("章节选择会为后续章节加载正文摘录而不把选择上限误作预览上限", async () => {
    const chapters = Array.from({ length: 21 }, (_, index) => ({
      id: `draft-${index + 1}`,
      chapter_index: index + 1,
      title: `第 ${index + 1} 章`,
    }))
    api.writing.listChapters.mockResolvedValue({ chapters })
    api.writing.get.mockImplementation(async (id) => ({
      id,
      title: id,
      content: `content-${id}`,
    }))

    await generateView._openChapterPicker()

    const html = showModal.mock.calls[0][1].html
    expect(html).toContain('id="generate-chapter-21"')
    expect(html).toContain("content-draft-21")
    expect(api.writing.get).toHaveBeenCalledTimes(21)
    expect(api.writing.get).toHaveBeenCalledWith("draft-21", "p1")
  })

  it("生成请求符合聊天和章节的服务上限", () => {
    generateView._messages = Array.from({ length: 41 }, (_, index) => ({
      role: index % 2 ? "assistant" : "user",
      content: `message-${index + 1}`,
    }))
    generateView._selectedChapters = Array.from({ length: 21 }, (_, index) => ({
      chapter_index: index + 1,
    }))

    const payload = generateView._buildPayload()

    expect(payload.messages).toHaveLength(40)
    expect(payload.messages[0].content).toBe("message-2")
    expect(payload.selected_chapter_indices).toEqual(
      Array.from({ length: 20 }, (_, index) => index + 1),
    )
  })

  it("无聊天和粘贴内容时不会生成数据库草稿", async () => {
    document.body.innerHTML = await generateView.render()

    await generateView._generateWorldSuggestion()

    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请先聊天或粘贴已有对话到输入框", "warning")
  })

  it("离开视图时中断进行中的聊天和生成请求", async () => {
    document.body.innerHTML = await generateView.render()
    const signals = []
    const deferreds = []
    function makeDeferred() {
      const d = {}
      d.promise = new Promise((resolve) => { d.resolve = resolve })
      return d
    }
    api.generate.worldChat.mockImplementation((_payload, options) => {
      signals.push(options?.signal)
      return deferreds[0].promise
    })
    api.generate.generateWorldSuggestion.mockImplementation((_payload, options) => {
      signals.push(options?.signal)
      return deferreds[1].promise
    })

    deferreds.push(makeDeferred(), makeDeferred())
    generateView._messages = [{ role: "user", content: "聊" }]
    document.getElementById("generate-chat-input").value = "继续聊"

    generateView._sendChatMessage()
    generateView._generateWorldSuggestion()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(signals).toHaveLength(2)
    expect(signals.every((signal) => signal && !signal.aborted)).toBe(true)
    expect(api.generate.worldChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    generateView.onLeave()

    expect(signals.every((signal) => signal.aborted)).toBe(true)
    deferreds.forEach((d) => d.resolve({}))
  })

  it("在 DOM 提交后通过 onRendered 同步绑定当前视图", async () => {
    const spy = vi.spyOn(generateView, "_bindEvents")
    document.body.innerHTML = await generateView.render()

    generateView.onRendered()

    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it("生成中心内部重绘后重新绑定新页签事件", async () => {
    document.body.innerHTML = '<main id="workspace-content"></main>'
    const spy = vi.spyOn(generateView, "onRendered")

    await generateView._switchGenerateSubTab("task")

    expect(document.getElementById("gen-task")).not.toBeNull()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it("章节选择器分批拉取章节，每次最多 5 个并行", async () => {
    vi.useFakeTimers()
    document.body.innerHTML = await generateView.render()
    const chapters = Array.from({ length: 12 }, (_, i) => ({
      id: `d${i + 1}`,
      chapter_index: i + 1,
      title: `第${i + 1}章`,
    }))
    api.writing.listChapters.mockResolvedValue({ chapters })

    const deferreds = new Map()
    api.writing.get.mockImplementation((id) => {
      if (!deferreds.has(id)) {
        const deferred = {}
        deferred.promise = new Promise((resolve) => { deferred.resolve = resolve })
        deferreds.set(id, deferred)
      }
      return deferreds.get(id).promise
    })

    const pickerPromise = generateView._openChapterPicker()
    await vi.advanceTimersByTimeAsync(0)

    expect(api.writing.get).toHaveBeenCalledTimes(5)

    const firstBatchIds = Array.from(deferreds.keys()).slice(0, 5)
    for (const id of firstBatchIds) {
      deferreds.get(id).resolve({ title: `第${id.slice(1)}章`, content: "正文" })
    }
    await vi.advanceTimersByTimeAsync(0)

    expect(api.writing.get).toHaveBeenCalledTimes(10)

    const secondBatchIds = Array.from(deferreds.keys()).slice(5, 10)
    for (const id of secondBatchIds) {
      deferreds.get(id).resolve({ title: `第${id.slice(1)}章`, content: "正文" })
    }
    await vi.advanceTimersByTimeAsync(0)

    expect(api.writing.get).toHaveBeenCalledTimes(12)

    const thirdBatchIds = Array.from(deferreds.keys()).slice(10, 12)
    for (const id of thirdBatchIds) {
      deferreds.get(id).resolve({ title: `第${id.slice(1)}章`, content: "正文" })
    }

    await pickerPromise
    vi.useRealTimers()
  })
})


describe("generateView task tab", () => {
  it("任务标签显示任务卡片和表单", async () => {
    generateView._generateSubTab = "task"
    const html = await generateView.render()

    expect(html).toContain("生成剧情线")
    expect(html).toContain("润色正文")
    expect(html).toContain("检查冲突")
    expect(html).toContain("自定义任务")
    expect(html).toContain("任务描述")
    expect(html).toContain("gen-task")
    expect(html).toContain("gen-scope")
    expect(html).toContain("编译上下文")
    expect(html).toContain("不会启动不存在的业务执行链路")
    expect(html).toContain('id="gen-budget" type="number" min="0" max="1000000" value="0"')
    expect(html).toContain("0 表示不做应用层裁剪")
  })

  it("默认以零预算编译完整上下文并如实显示未裁剪", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "检查完整上下文",
      scope: "chapter",
      reveal_mode: "author_full",
      budget_tokens: 0,
    }
    api.context.compile.mockResolvedValue({
      sections: [{ tier: 1, key: "world_entities", token_count: 12000 }],
      total_tokens: 12000,
      budget_tokens: 0,
      scope: "chapter",
      reveal_mode: "author_full",
      evicted: [],
      truncated: [],
      warnings: [],
    })
    document.body.innerHTML = await generateView.render()

    await generateView._runTask()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({ budget_tokens: 0 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(generateView._renderCompileResult(generateView._lastContextBundle)).toContain(
      "Tokens：12000（无应用层裁剪）",
    )
  })

  it("点击任务卡片填充默认值", async () => {
    generateView._generateSubTab = "task"
    document.body.innerHTML = await generateView.render()

    generateView._selectTaskPreset("plot")

    expect(generateView._taskPreset).toBe("plot")
    expect(generateView._taskForm.task).toContain("梳理主线")
    expect(generateView._taskForm.scope).toBe("arc")
    expect(generateView._taskForm.reveal_mode).toBe("author_full")
  })

  it("执行任务调用 api.context.compile 并渲染结果", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-task").value = "测试任务"
    document.getElementById("gen-scope").value = "arc"
    document.getElementById("gen-reveal").value = "author_safe"
    document.getElementById("gen-budget").value = "4000"

    await generateView._runTask()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        task: "测试任务",
        scope: "arc",
        reveal_mode: "author_safe",
        budget_tokens: 4000,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(generateView._generateSubTab).toBe("preview")
    document.body.innerHTML = await generateView.render()
    expect(document.getElementById("gen-task-output")?.textContent).toContain("1200")
  })

  it("无任务描述时阻止执行", async () => {
    generateView._generateSubTab = "task"
    document.body.innerHTML = await generateView.render()

    await generateView._runTask()

    expect(api.context.compile).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请输入任务描述", "warning")
  })

  it("执行任务编译失败时 toast 并显示错误", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
    api.context.compile.mockRejectedValue(new Error("编译超时"))
    document.body.innerHTML = await generateView.render()

    await generateView._runTask()

    expect(toast).toHaveBeenCalledWith("编译失败：编译超时", "error")
    expect(document.getElementById("gen-task-output")?.textContent).toContain("编译失败")
  })

  it("预览上下文编译失败时不弹 toast，仅在输出区显示错误", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
    api.context.compile.mockRejectedValue(new Error("预览失败"))
    document.body.innerHTML = await generateView.render()

    await generateView._previewTaskContext()

    expect(toast).not.toHaveBeenCalledWith("编译失败：预览失败", "error")
    expect(document.getElementById("gen-task-output")?.textContent).toContain("编译失败")
  })

  it("渲染 Markdown 调用 api.context.render", async () => {
    generateView._generateSubTab = "task"
    generateView._lastContextRequestParams = { novel_id: "p1", task: "旧任务", scope: "arc" }
    document.body.innerHTML = await generateView.render()

    await generateView._renderTaskMarkdown()

    expect(api.context.render).toHaveBeenCalledWith(
      expect.objectContaining({ task: "旧任务" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(generateView._lastContextMarkdown).toContain("测试内容")
    expect(document.querySelector('[data-action="copy-task-md"]')?.disabled).toBe(false)
    expect(document.querySelector('[data-action="export-task-md"]')?.disabled).toBe(false)
  })

  it("执行任务后保留视角人物 ID", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "写角色视角场景",
      scope: "chapter",
      reveal_mode: "character",
      budget_tokens: 4000,
      viewpoint_character_id: "char-1",
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-reveal").value = "character"
    document.getElementById("gen-viewpoint-character").value = "char-1"

    await generateView._runTask()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({
        task: "写角色视角场景",
        reveal_mode: "character",
        viewpoint_character_id: "char-1",
        character_ids: ["char-1"],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(generateView._taskForm.viewpoint_character_id).toBe("char-1")
  })

  it("角色视角模式不自动把相关人物当作视角人物", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "写角色视角场景",
      scope: "chapter",
      reveal_mode: "character",
      budget_tokens: 4000,
      character_ids: ["char-1"],
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-reveal").value = "character"
    document.getElementById("gen-characters").value = "char-1"
    document.getElementById("gen-viewpoint-character").value = ""

    await generateView._runTask()

    expect(api.context.compile).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("角色视角模式必须选择视角人物", "warning")
  })

  it("切换到非角色视角预设时清空视角人物 ID", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      ...generateView._taskForm,
      viewpoint_character_id: "char-1",
    }
    document.body.innerHTML = await generateView.render()

    await generateView._selectTaskPreset("plot")

    expect(generateView._taskForm.reveal_mode).toBe("author_full")
    expect(generateView._taskForm.viewpoint_character_id).toBeUndefined()
  })

  it("上下文编译期间禁用任务操作按钮", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
    document.body.innerHTML = await generateView.render()
    let resolveCompile
    api.context.compile.mockImplementation(() => new Promise((resolve) => { resolveCompile = resolve }))

    generateView._runTask()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(document.querySelector('[data-action="run-task"]')?.disabled).toBe(true)
    expect(document.querySelector('[data-action="preview-task-context"]')?.disabled).toBe(true)
    expect(document.querySelector('[data-action="render-task-md"]')?.disabled).toBe(true)

    resolveCompile({
      sections: [],
      total_tokens: 0,
      budget_tokens: 4000,
      scope: "arc",
      reveal_mode: "author_safe",
    })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(document.querySelector('[data-action="run-task"]')?.disabled).toBe(false)
  })
})

describe("generateView context preview tab", () => {
  it("上下文预览标签展示最近一次编译结果", async () => {
    generateView._generateSubTab = "preview"
    generateView._lastContextSource = "task"
    generateView._taskPreset = "plot"
    generateView._lastContextBundle = {
      total_tokens: 800,
      budget_tokens: 4000,
      scope: "chapter",
      reveal_mode: "author_safe",
      sections: [{ key: "characters", tier: "standard", token_count: 800, truncated: false }],
      evicted: [],
      truncated: [],
      warnings: [],
    }

    const html = await generateView.render()

    expect(html).toContain("上下文预览")
    expect(html).toContain("任务：生成剧情线")
    expect(html).toContain("characters")
    expect(html).toContain("800")
  })

  it("无编译结果时显示空状态", async () => {
    generateView._generateSubTab = "preview"
    generateView._lastContextBundle = null

    const html = await generateView.render()

    expect(html).toContain("还未执行任何 AI 生成")
  })
})

describe("generateView POV prose tab", () => {
  it("切换到角色视角正文模式会加载章节和角色，不调用对象生成 API", async () => {
    api.writing.listChapters.mockResolvedValue({
      chapters: [{ chapter_index: 1, title: "旧怨" }],
    })
    api.world.listCharacters.mockResolvedValue({
      items: [{ entity_id: "char-1", name: "秦岚" }],
      total: 1,
    })

    await generateView._switchGenerateSubTab("pov_prose")

    expect(generateView._generateSubTab).toBe("pov_prose")
    expect(api.writing.listChapters).toHaveBeenCalledWith("p1")
    expect(api.world.listCharacters).toHaveBeenCalledWith({
      novel_id: "p1",
      skip: 0,
      limit: 50,
    })
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(api.context.confirm).not.toHaveBeenCalled()
  })

  it("现有页面来源请求携带服务器 baseline 与完整显式上下文选择", () => {
    generateView._routeSourcePageId = "page-1"
    generateView._worldTargetKind = "world_bible_page"
    generateView._sourcePage = { id: "page-1", version_number: 7 }
    generateView._sourceDraft = { id: "draft-1", page_id: "page-1", updated_at: "2026-07-15T10:00:00Z" }
    generateView._selectedChapters = [{ chapter_index: 3 }, { chapter_index: 5 }]
    generateView._selectedSceneId = "scene-3"
    generateView._selectedThreadIds = ["thread-1"]
    generateView._selectedCharacterIds = ["character-1"]
    generateView._selectedEntityIds = ["entity-1"]
    generateView._messages = [{ role: "user", content: "重构这页，让规则更严密" }]

    const payload = generateView._buildPayload()

    expect(payload.source_context).toEqual({
      kind: "world_bible_page",
      page_id: "page-1",
      baseline: {
        kind: "draft",
        page_version: 7,
        draft_id: "draft-1",
        draft_updated_at: "2026-07-15T10:00:00Z",
      },
    })
    expect(payload.target).toEqual({ kind: "world_bible_page", page_id: "page-1" })
    expect(payload).toEqual(expect.objectContaining({
      selected_chapter_indices: [3, 5],
      scene_id: "scene-3",
      thread_ids: ["thread-1"],
      character_ids: ["character-1"],
      entity_ids: ["entity-1"],
    }))

    generateView._sourceDraft = null
    expect(generateView._buildPayload().source_context.baseline).toEqual({
      kind: "published",
      page_version: 7,
    })
  })

  it("作者编辑完整页面提案后只调用工作稿 apply 并返回世界书", async () => {
    generateView._worldCategories = [{ category_key: "rule", name: "规则" }]
    generateView._lastWorldResult = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-page-1" },
      proposal: {
        operation: "replace_existing",
        page: {
          title: "原提案标题",
          page_type: "rule",
          free_text: "原概览",
          sections_json: [{ section_id: "section-1", title: "边界", section_type: "markdown", content: "原内容" }],
          linked_asset_refs_json: [],
        },
      },
    }
    document.body.innerHTML = generateView._renderWorldResult(generateView._lastWorldResult)
    document.getElementById("generate-page-title").value = "作者编辑后的标题"
    document.getElementById("generate-page-free-text").value = "作者编辑后的概览"
    document.getElementById("generate-page-sections").value = JSON.stringify([
      { section_id: "section-1", title: "边界", section_type: "markdown", content: "作者修订内容" },
    ])
    api.generate.applyWorldPageDraft.mockResolvedValue({
      draft: { id: "draft-2", page_id: "page-1" },
    })

    await generateView._applyWorldPageDraft()

    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "suggestion-page-1",
      {
        page: expect.objectContaining({
          title: "作者编辑后的标题",
          free_text: "作者编辑后的概览",
          sections_json: [expect.objectContaining({ content: "作者修订内容" })],
        }),
      },
      "p1",
      { signal: expect.any(AbortSignal) },
    )
    expect(router.navigate).toHaveBeenCalledWith(
      "world",
      "bible",
      true,
      expect.any(URLSearchParams),
    )
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("draft_id")).toBe("draft-2")
    expect(query.get("page_id")).toBe("page-1")
  })

  it("页面工作稿 baseline 冲突时保留当前提案且不导航", async () => {
    generateView._worldCategories = [{ category_key: "rule", name: "规则" }]
    generateView._lastWorldResult = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-page-1" },
      proposal: {
        operation: "replace_existing",
        page: { title: "规则", page_type: "rule", free_text: "", sections_json: [], linked_asset_refs_json: [] },
      },
    }
    document.body.innerHTML = generateView._renderWorldResult(generateView._lastWorldResult)
    const conflict = new Error("baseline drift")
    conflict.status = 409
    api.generate.applyWorldPageDraft.mockRejectedValue(conflict)

    await generateView._applyWorldPageDraft()

    expect(router.navigate).not.toHaveBeenCalled()
    expect(generateView._lastWorldResult.suggestion.id).toBe("suggestion-page-1")
    expect(toast).toHaveBeenCalledWith(
      "来源工作稿已变更，本次提案未覆盖新修改。请重新生成。",
      "warning",
    )
  })

  it("刷新后用 pending suggestion ID 恢复整页提案", async () => {
    generateView._routeSourcePageId = "page-1"
    generateView._worldTargetKind = "world_bible_page"
    generateView._lastWorldSuggestionId = "suggestion-restore"
    api.world.listBiblePages.mockResolvedValue({
      items: [{ id: "page-1", title: "北境", version_number: 3, sections_json: [] }],
      total: 1,
    })
    api.world.listSuggestions.mockResolvedValue({
      items: [{
        id: "suggestion-restore",
        target_type: "world_bible_page_draft",
        status: "pending",
        payload_json: {
          operation: "replace_existing",
          target_page_id: "page-1",
          page: {
            title: "恢复的北境",
            page_type: "custom",
            free_text: "恢复概览",
            sections_json: [],
            linked_asset_refs_json: [],
          },
        },
      }],
      total: 1,
    })

    await generateView._loadWorldWorkspace()

    expect(api.world.listSuggestions).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      review_group: "generation_center",
      status: "pending",
    }))
    expect(generateView._lastWorldResult).toEqual(expect.objectContaining({
      kind: "world_bible_page",
      suggestion: expect.objectContaining({ id: "suggestion-restore" }),
      proposal: expect.objectContaining({ target_page_id: "page-1" }),
    }))
  })

  it("世界创设工作区分页加载全部人物和世界对象", async () => {
    const firstCharacters = Array.from({ length: 50 }, (_, index) => ({
      entity_id: `char-${index + 1}`,
      name: `人物 ${index + 1}`,
    }))
    const firstEntities = Array.from({ length: 50 }, (_, index) => ({
      id: `entity-${index + 1}`,
      name: `对象 ${index + 1}`,
      entity_type: "item",
    }))
    api.world.listCharacters
      .mockResolvedValueOnce({ items: firstCharacters, total: 51 })
      .mockResolvedValueOnce({
        items: [{ entity_id: "char-51", name: "人物 51" }],
        total: 51,
      })
    api.world.listEntities
      .mockResolvedValueOnce({ items: firstEntities, total: 51 })
      .mockResolvedValueOnce({
        items: [{ id: "entity-51", name: "对象 51", entity_type: "item" }],
        total: 51,
      })

    await generateView._loadWorldWorkspace()

    expect(generateView._worldCharacters).toHaveLength(51)
    expect(generateView._worldEntities).toHaveLength(51)
    expect(api.world.listCharacters).toHaveBeenNthCalledWith(2, {
      novel_id: "p1",
      skip: 50,
      limit: 50,
    })
    expect(api.world.listEntities).toHaveBeenNthCalledWith(2, {
      novel_id: "p1",
      display_state: "active",
      skip: 50,
      limit: 50,
    })
  })

  it("世界创设工作区只加载全部活跃 Scene，不使用包含历史态的分页列表", async () => {
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "scene-1", title: "活跃 Scene", status: "canonical" },
      { id: "scene-2", title: "计划 Scene", status: "draft" },
    ])

    await generateView._loadWorldWorkspace()

    expect(generateView._worldScenes.map((item) => item.id)).toEqual(["scene-1", "scene-2"])
    expect(api.outline.listScenesOrdered).toHaveBeenCalledWith("p1")
    expect(api.outline.listScenes).not.toHaveBeenCalled()
  })

  it("整页提案按 section_id 展示新增、修改与删除", () => {
    generateView._sourcePage = {
      title: "原页",
      sections_json: [
        { section_id: "kept", title: "旧标题", body_markdown: "旧正文" },
        { section_id: "removed", title: "将删除", body_markdown: "" },
      ],
    }
    generateView._worldCategories = [{ category_key: "custom", name: "自定义" }]
    const html = generateView._renderWorldResult({
      kind: "world_bible_page",
      suggestion: { id: "suggestion-diff" },
      proposal: {
        operation: "replace_existing",
        page: {
          title: "新页",
          page_type: "custom",
          free_text: "",
          linked_asset_refs_json: [],
          sections_json: [
            { section_id: "kept", title: "新标题", body_markdown: "新正文" },
            { section_id: "added", title: "新增分区", body_markdown: "" },
          ],
        },
      },
    })
    document.body.innerHTML = html

    const diffText = document.querySelector(".generate-page-section-diff").textContent
    expect(diffText).toContain("修改")
    expect(diffText).toContain("标题、正文")
    expect(diffText).toContain("新增")
    expect(diffText).toContain("删除")
  })

  it("角色超过单页上限时分页加载全部角色", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      entity_id: `char-${index + 1}`,
      name: `角色 ${index + 1}`,
    }))
    api.world.listCharacters
      .mockResolvedValueOnce({ items: firstPage, total: 51 })
      .mockResolvedValueOnce({
        items: [{ entity_id: "char-51", name: "角色 51" }],
        total: 51,
      })

    await generateView._switchGenerateSubTab("pov_prose")

    expect(api.world.listCharacters).toHaveBeenNthCalledWith(1, {
      novel_id: "p1",
      skip: 0,
      limit: 50,
    })
    expect(api.world.listCharacters).toHaveBeenNthCalledWith(2, {
      novel_id: "p1",
      skip: 50,
      limit: 50,
    })
    expect(generateView._povCharacters).toHaveLength(51)
    expect(generateView._povCharacters.at(-1)).toEqual({
      entity_id: "char-51",
      name: "角色 51",
    })
  })

  it("选择章节后加载 Scene，并清空旧 Scene 和角色选择", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "old-scene",
      viewpointCharacterId: "old-char",
      instruction: "保留指令",
    }
    api.outline.listScenesByChapter.mockResolvedValue([
      { id: "scene-2", title: "第二场", chapter_index: 2, pov_character_id: "char-2" },
    ])

    await generateView._changePovChapter("2")

    expect(api.outline.listScenesByChapter).toHaveBeenCalledWith("p1", 2)
    expect(generateView._povForm).toEqual({
      chapterIndex: 2,
      sceneId: "",
      viewpointCharacterId: "",
      instruction: "保留指令",
    })
    expect(generateView._povScenes).toEqual([
      expect.objectContaining({ id: "scene-2" }),
    ])
  })

  it("选择 Scene 后自动重置为该 Scene 的 POV 角色，无 POV 时清空角色", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "",
      viewpointCharacterId: "manual-char",
      instruction: "",
    }
    generateView._povScenes = [
      { id: "scene-1", title: "第一场", pov_character_id: "char-1" },
      { id: "scene-2", title: "第二场", pov_character_id: null },
    ]

    await generateView._changePovScene("scene-1")
    expect(generateView._povForm.viewpointCharacterId).toBe("char-1")

    await generateView._changePovScene("scene-2")
    expect(generateView._povForm.viewpointCharacterId).toBe("")
  })

  it("手动选择不同角色时显示不修改 Scene POV 的提示", () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povChapters = [{ chapter_index: 1, title: "旧怨" }]
    generateView._povScenes = [
      { id: "scene-1", title: "第一场", pov_character_id: "char-1" },
    ]
    generateView._povCharacters = [
      { entity_id: "char-1", name: "秦岚" },
      { entity_id: "char-2", name: "林澈" },
    ]
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "scene-1",
      viewpointCharacterId: "char-2",
      instruction: "",
    }

    const html = generateView._renderPovProseTab()

    expect(html).toContain("本次使用手动选择角色，不修改 Scene POV 设置")
  })

  it("角色视角正文生成会创建 character confirmation 并调用 writing.generate", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povChapters = [{ chapter_index: 1, title: "旧怨" }]
    generateView._povScenes = [
      { id: "scene-1", title: "第一场", pov_character_id: "char-1" },
    ]
    generateView._povCharacters = [{ entity_id: "char-1", name: "秦岚" }]
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "scene-1",
      viewpointCharacterId: "char-1",
      instruction: "保持克制",
    }
    document.body.innerHTML = generateView._renderPovProseTab()
    mountAiReferenceModalShell()
    api.context.confirm.mockResolvedValue({
      id: "confirm-1",
      user_note: "避免提前揭示真相",
      context_summary: {},
    })
    api.writing.generate.mockResolvedValue({ task_id: "task-1" })

    const promise = generateView._generatePovProse()
    await Promise.resolve()
    document.querySelector("#modal-footer .btn-primary").click()
    await promise

    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      action: "writing.generate",
      task: "基于所选 Scene 和 POV 角色有限认知，生成正文建议预览",
      scope: "chapter",
      chapter_index: 1,
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: false,
      budget_tokens: 0,
    }))
    expect(api.writing.generate).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      context_confirmation_id: "confirm-1",
    }))
    const instruction = api.writing.generate.mock.calls[0][0].instruction
    expect(instruction).toContain("保持克制")
    expect(instruction).toContain("用户指令是作者意图，不等于角色知识")
    expect(instruction).toContain("角色判断、台词、内心只能使用确认上下文中该角色可见的信息")
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(document.getElementById("generate-pov-result")?.innerHTML).toContain("draft-pov-1")
    expect(document.getElementById("generate-pov-result")?.innerHTML).toContain("打开并审阅建议")
  })

  it("角色视角结果从生成中心直达对应待审核建议", () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povScenes = [{ id: "scene-1", title: "第一场" }]
    generateView._povCharacters = [{ entity_id: "char-1", name: "秦岚" }]
    generateView._povForm = {
      chapterIndex: 6,
      sceneId: "scene-1",
      viewpointCharacterId: "char-1",
      instruction: "",
    }
    generateView._lastPovSubmission = {
      chapterIndex: 6,
      sceneId: "scene-1",
      viewpointCharacterId: "char-1",
      result: { task_id: "task-1", draft_id: "draft-pov-1" },
    }
    document.body.innerHTML = `<div id="workspace-content">${generateView._renderPovProseTab()}</div>`

    generateView._bindEvents()
    document.querySelector('[data-action="open-generated-destination"]').click()

    expect(state.viewStates.writing).toEqual(expect.objectContaining({
      projectId: "p1",
      currentChapter: 6,
      currentDraftId: "draft-pov-1",
      isReadonly: true,
    }))
    expect(router.navigate).toHaveBeenCalledWith(
      "writing",
      null,
      true,
      expect.objectContaining({}),
    )
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("chapter_index")).toBe("6")
    expect(query.get("draft_id")).toBe("draft-pov-1")
  })

  it("角色视角正文缺必要选择时不会打开 confirmation 或调用生成", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "",
      viewpointCharacterId: "",
      instruction: "",
    }
    document.body.innerHTML = generateView._renderPovProseTab()

    await generateView._generatePovProse()

    expect(api.context.confirm).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请先选择 Scene", "warning")
  })

  it("角色视角正文 confirmation 取消时不调用 writing.generate", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povScenes = [
      { id: "scene-1", title: "第一场", pov_character_id: "char-1" },
    ]
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "scene-1",
      viewpointCharacterId: "char-1",
      instruction: "",
    }
    document.body.innerHTML = generateView._renderPovProseTab()
    mountAiReferenceModalShell()

    const promise = generateView._generatePovProse()
    await Promise.resolve()
    document.querySelector("#modal-footer .btn-ghost").click()
    await promise

    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("角色视角正文 writing.generate 失败时保留表单并显示错误", async () => {
    generateView._generateSubTab = "pov_prose"
    generateView._povScenes = [
      { id: "scene-1", title: "第一场", pov_character_id: "char-1" },
    ]
    generateView._povCharacters = [{ entity_id: "char-1", name: "秦岚" }]
    generateView._povForm = {
      chapterIndex: 1,
      sceneId: "scene-1",
      viewpointCharacterId: "char-1",
      instruction: "不要激烈",
    }
    document.body.innerHTML = generateView._renderPovProseTab()
    mountAiReferenceModalShell()
    api.context.confirm.mockResolvedValue({ id: "confirm-1", context_summary: {} })
    api.writing.generate.mockRejectedValue(new Error("生成失败"))

    const promise = generateView._generatePovProse()
    await Promise.resolve()
    document.querySelector("#modal-footer .btn-primary").click()
    await promise

    expect(api.writing.generate).toHaveBeenCalled()
    expect(document.getElementById("generate-pov-result")?.innerHTML).toContain("生成失败")
    expect(generateView._povForm.instruction).toBe("不要激烈")
  })
})

describe("generateView context integration", () => {
  it("生成的结果卡片包含查看上下文按钮", async () => {
    generateView._lastWorldResult = {
      kind: "core_entity",
      suggestion: {
        id: "s1",
        status: "pending",
        payload_json: { name: "沈无咎", entity_type: "character", summary: "旧友型反派" },
      },
    }
    generateView._lastEntityContextUsage = { status: "included", warnings: [] }
    const html = await generateView.render()

    expect(html).toContain("查看本次上下文")
  })

  it("查看上下文读取本次响应 provenance，不事后重新编译", async () => {
    generateView._lastContextUsage = {
      section_key: "world_bible_synopsis",
      status: "included",
      revision_id: "revision-1",
      source_hash: "source-hash",
      block_hash: "block-hash",
      token_count: 320,
      stale: false,
      fallback: false,
      warnings: [],
    }
    document.body.innerHTML = await generateView.render()

    await generateView._viewGenerationContext()

    expect(api.context.compile).not.toHaveBeenCalled()
    expect(showModal).toHaveBeenCalledWith(
      "本次实际使用的上下文",
      expect.objectContaining({ html: expect.stringContaining("revision-1") }),
      [],
      { size: "large" },
    )
  })

  it("聊天与对象生成分别保留各自的实际上下文", async () => {
    const entityUsage = {
      status: "included",
      revision_id: "revision-entity",
      context_snapshot_id: "snapshot-entity",
      warnings: [],
    }
    const chatUsage = {
      status: "fallback",
      revision_id: "revision-chat",
      context_snapshot_id: "snapshot-chat",
      warnings: [],
    }
    generateView._messages = [{ role: "user", content: "先生成对象" }]
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: { kind: "core_entity", suggestion: { id: "suggestion-1", payload_json: { name: "空城" } } },
      context_usage: entityUsage,
    })
    document.body.innerHTML = await generateView.render()
    await generateView._generateWorldSuggestion()

    document.getElementById("generate-chat-input").value = "继续讨论"
    api.generate.worldChat.mockResolvedValue({ reply: "好", context_usage: chatUsage })
    await generateView._sendChatMessage()

    await generateView._viewGenerationContext("entity")
    expect(showModal.mock.calls.at(-1)[1].html).toContain("revision-entity")
    expect(showModal.mock.calls.at(-1)[1].html).toContain("snapshot-entity")

    await generateView._viewGenerationContext("chat")
    expect(showModal.mock.calls.at(-1)[1].html).toContain("revision-chat")
    expect(showModal.mock.calls.at(-1)[1].html).toContain("snapshot-chat")
    expect(document.getElementById("generate-chat-context-usage")?.textContent).toContain("查看最近聊天上下文")
  })

  it("生成中心 payload 默认开启世界观简介", () => {
    const payload = generateView._buildPayload()

    expect(payload.include_world_synopsis).toBe(true)
    expect(payload.source_context).toEqual({ kind: "project" })
    expect(payload.target).toEqual(expect.objectContaining({ kind: "core_entity" }))
  })
})

describe("generateView task execution", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
  })

  it("执行任务成功后切换到上下文预览标签", async () => {
    document.body.innerHTML = await generateView.render()

    await generateView._runTask()

    expect(generateView._generateSubTab).toBe("preview")
  })

  it("任务高级参数使用四类名称选择器，并只保留隐藏 ID wire 字段", async () => {
    document.body.innerHTML = await generateView.render()

    expect(document.getElementById("gen-entities-picker")).not.toBeNull()
    expect(document.getElementById("gen-characters-picker")).not.toBeNull()
    expect(document.getElementById("gen-scene-picker")).not.toBeNull()
    expect(document.getElementById("gen-viewpoint-character-picker")).not.toBeNull()
    for (const id of ["gen-entities", "gen-characters", "gen-scene", "gen-viewpoint-character"]) {
      expect(document.getElementById(id)?.type).toBe("hidden")
    }
    expect(document.body.textContent).not.toContain("character ID")
    expect(document.body.textContent).not.toContain("Scene ID")
  })

  it("选择章节后优先展示该章 Scene，同时仍可搜索项目内其他 Scene", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      ...generateView._taskForm,
      chapter_index: 2,
    }
    api.outline.listScenesByChapter.mockResolvedValue([
      { id: "scene-chapter", title: "王宫密道", status: "draft", chapter_ids: ["2"] },
    ])
    api.outline.getSceneWorkbench.mockResolvedValue({
      items: [
        { scene: { id: "scene-chapter", title: "王宫密道", status: "draft", chapter_ids: ["2"] } },
        { scene: { id: "scene-other", title: "王宫屋顶", status: "canonical", chapter_ids: ["5"] } },
      ],
      total: 2,
    })
    document.body.innerHTML = await generateView.render()
    generateView.onRendered()

    const picker = document.getElementById("gen-scene-picker")
    const query = picker.querySelector("[data-reference-query]")
    query.value = "王宫"
    query.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 230))

    const results = Array.from(picker.querySelectorAll("[data-reference-result]"))
    expect(results.map((item) => item.textContent)).toEqual([
      expect.stringContaining("王宫密道"),
      expect.stringContaining("王宫屋顶"),
    ])
    expect(api.outline.listScenesByChapter).toHaveBeenCalledWith("p1", 2)
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      q: "王宫",
      view_mode: "normal",
      skip: 0,
      limit: 20,
    })

    results[1].click()
    expect(document.getElementById("gen-scene").value).toBe("scene-other")
  })

  it("角色视角缺少人物 ID 时不提交编译", async () => {
    generateView._taskForm = {
      task: "写角色视角场景",
      scope: "chapter",
      reveal_mode: "character",
      budget_tokens: 4000,
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-reveal").value = "character"
    document.getElementById("gen-viewpoint-character").value = ""

    await generateView._runTask()

    expect(api.context.compile).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("角色视角模式必须选择视角人物", "warning")
  })

  it("切换读者视角时立即禁用作者简介并显示原因", async () => {
    document.body.innerHTML = await generateView.render()
    generateView._bindEvents()
    const reveal = document.getElementById("gen-reveal")
    reveal.value = "reader"
    reveal.dispatchEvent(new Event("change"))

    expect(document.getElementById("gen-include-world-synopsis").disabled).toBe(true)
    expect(document.getElementById("gen-include-world-synopsis").checked).toBe(false)
    expect(document.getElementById("gen-world-synopsis-visibility-hint").hidden).toBe(false)
  })
})

describe("generateView content-first layout", () => {
  it("keeps a collapsed assistant rail full-width on narrow screens", () => {
    const styles = generateView._renderStyles()

    expect(styles).toContain("grid-template-columns:minmax(0,78fr) minmax(180px,22fr)")
    expect(styles).toContain(".generate-chatbox, .generate-chatbox:has(.generate-side-rail:not([open])) { grid-template-columns:1fr")
    expect(styles).toContain(".generate-side-rail { grid-column:1 / -1; }")
    expect(styles).toContain(".generate-template-row--toolbar")
  })
})

describe("generateView abort on leave", () => {
  it("onLeave 中止进行中的上下文请求", () => {
    const controller = new AbortController()
    const abortSpy = vi.spyOn(controller, "abort")
    generateView._abortControllers = new Set([controller])

    generateView.onLeave()

    expect(abortSpy).toHaveBeenCalled()
    expect(generateView._abortControllers.size).toBe(0)
  })
})
