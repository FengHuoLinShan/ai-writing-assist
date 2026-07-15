import { describe, it, expect, vi, beforeEach } from "vitest"
import generateView from "../views/generateView.js"

beforeEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
  localStorage.clear()
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
  generateView._lastContextUsage = null
  generateView._lastChatContextUsage = null
  generateView._lastEntityContextUsage = null
  generateView._busy = false
  generateView._abortControllers = null
  generateView._generateSubTab = "chat"
  generateView._taskPreset = "custom"
  generateView._taskForm = {
    task: "",
    scope: "arc",
    reveal_mode: "author_safe",
    budget_tokens: 4000,
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
  api.writing.generate.mockResolvedValue({ task_id: "task-1" })
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

  it("drops reproducible previews before dropping conversation messages", () => {
    generateView._messages = Array.from({ length: 30 }, (_, index) => ({
      role: "user",
      content: `${index}:` + "x".repeat(10_000),
    }))
    generateView._lastContextBundle = { markdown: "y".repeat(300_000) }

    expect(generateView._persistState()).toBe(true)

    const stored = JSON.parse(localStorage.getItem(generateView._storageKey()))
    expect(stored.lastContextBundle).toBeNull()
    expect(stored.messages).toHaveLength(30)
    expect(stored.messages[0].content.startsWith("0:")).toBe(true)
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("省略可重新生成的预览数据"),
      "warning",
    )
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
        `generate_chatbox_state_v1_old-${index}`,
        JSON.stringify({ savedAt: index, messages: [] }),
      )
    }
    state.currentProjectId = "new-project"
    generateView._activeStorageKey = generateView._storageKey()

    expect(generateView._persistState()).toBe(true)

    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((key) => key.startsWith("generate_chatbox_state_v1_"))
    expect(keys).toHaveLength(5)
    expect(keys).toContain("generate_chatbox_state_v1_new-project")
    expect(keys).not.toContain("generate_chatbox_state_v1_old-1")
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
      "generate_chatbox_state_v1_oldest",
      JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "oldest" }] }),
    )
    localStorage.setItem(
      "generate_chatbox_state_v1_recent",
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
    expect(localStorage.getItem("generate_chatbox_state_v1_oldest")).toBeNull()
    expect(localStorage.getItem("generate_chatbox_state_v1_recent")).toContain("recent")
    expect(localStorage.getItem("unrelated-module-state")).toBe("keep")
    expect(localStorage.getItem(generateView._storageKey())).toContain("current")
    setItem.mockRestore()
  })

  it("does not loop forever when a storage implementation refuses to remove an eviction candidate", () => {
    localStorage.setItem(
      "generate_chatbox_state_v1_oldest",
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

  it("restores legacy v1 snapshots and fills fields added after the snapshot", () => {
    const storageKey = generateView._storageKey()
    localStorage.setItem(storageKey, JSON.stringify({
      selectedTemplateId: "builtin:character",
      messages: [{ role: "user", content: "旧版会话" }],
      povForm: { chapterIndex: 3 },
      taskForm: { task: "旧版任务" },
    }))

    generateView._resetProjectState()
    generateView._restoreState(storageKey)

    expect(generateView._selectedTemplateId).toBe("builtin:character")
    expect(generateView._messages).toEqual([{ role: "user", content: "旧版会话" }])
    expect(generateView._povForm).toEqual(expect.objectContaining({
      chapterIndex: 3,
      sceneId: "",
      viewpointCharacterId: "",
      instruction: "",
    }))
    expect(generateView._taskForm).toEqual(expect.objectContaining({
      task: "旧版任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }))
  })

  it("switching projects resets unsaved project-scoped state before restore", () => {
    generateView._messages = [{ role: "user", content: "项目一私有内容" }]
    generateView._lastContextBundle = { project: "p1" }
    state.currentProjectId = "p2"

    generateView._activateProjectState()

    expect(generateView._activeStorageKey).toBe("generate_chatbox_state_v1_p2")
    expect(generateView._messages).toEqual([])
    expect(generateView._lastContextBundle).toBeNull()
    expect(generateView._selectedTemplateId).toBe("builtin:none")
    expect(localStorage.getItem("generate_chatbox_state_v1_p1")).toContain("项目一私有内容")
    expect(localStorage.getItem("generate_chatbox_state_v1_p2")).toBeNull()
  })

  it("restores only the destination project after saving the previous project", () => {
    localStorage.setItem("generate_chatbox_state_v1_p2", JSON.stringify({
      savedAt: 2,
      messages: [{ role: "user", content: "项目二快照" }],
    }))
    generateView._messages = [{ role: "user", content: "项目一当前内容" }]
    state.currentProjectId = "p2"

    generateView._activateProjectState()

    expect(localStorage.getItem("generate_chatbox_state_v1_p1")).toContain("项目一当前内容")
    expect(generateView._messages).toEqual([{ role: "user", content: "项目二快照" }])
  })

  it("persists to the active project when global selection changes before teardown", () => {
    generateView._messages = [{ role: "user", content: "项目一私有内容" }]
    state.currentProjectId = "p2"

    expect(generateView._persistState()).toBe(true)

    expect(localStorage.getItem("generate_chatbox_state_v1_p1")).toContain("项目一私有内容")
    expect(localStorage.getItem("generate_chatbox_state_v1_p2")).toBeNull()
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
})

describe("generateView chatbox", () => {
  it("初始页面显示 Chatbox、模板、高质量和生成按钮", async () => {
    const html = await generateView.render()

    expect(html).toContain("不带模板")
    expect(html).toContain("人物")
    expect(html).toContain("编辑模板")
    expect(html).toContain("高质量")
    expect(html).toContain("直接聊，或把其他 Chatbox 的完整讨论粘贴到这里")
    expect(html).toContain("生成世界对象建议")
    expect(html).toContain("自由对话")
    expect(html).toContain("角色视角正文")
    expect(html).toContain("任务")
    expect(html).toContain("上下文预览")
    expect(html).not.toContain("generate-pasted-context")
  })

  it("自由对话渲染顶部工具栏，并把模板行移到工具栏下方", async () => {
    state.currentProject = { id: "p1", title: "测试项目" }
    const html = await generateView.render()

    expect(html).toContain("generate-toolbar")
    expect(html).toContain("自由对话")
    expect(html).toContain("测试项目")
    expect(html).toContain('data-action="send-chat-message"')
    expect(html).toContain('data-action="generate-object-draft"')
    expect(html).toContain("generate-template-row--toolbar")
  })

  it("在页面标题栏挂载生成中心说明，离开时清理", () => {
    document.body.innerHTML = `
      <header id="workspace-header"><div id="view-actions"></div></header>
      <div class="topbar-center"><span id="topbar-module">生成中心</span></div>
    `

    generateView._mountTopbarNote()

    expect(document.getElementById("topbar-generate-note")?.textContent).toBe("先自由聊，确定后再生成待处理建议。")

    generateView.onLeave()

    expect(document.getElementById("topbar-generate-note")).toBeNull()
  })

  it("发送自由聊天只调用 chat 接口，不调用结构化生成和 context confirm", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.objectDraftChat.mockResolvedValue({ reply: "可以设计成旧友型反派" })
    document.getElementById("generate-chat-input").value = "帮我设计一个反派"

    await generateView._sendChatMessage()

    expect(api.generate.objectDraftChat).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        template_id: "builtin:none",
        template_version: 1,
        template: "none",
        quality_mode: "fast",
        messages: [{ role: "user", content: "帮我设计一个反派" }],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(api.generate.generateObjectDraft).not.toHaveBeenCalled()
    expect(api.context.confirm).not.toHaveBeenCalled()
    expect(document.getElementById("generate-chat-messages")?.innerHTML).toContain("旧友型反派")
  })

  it("聊天请求失败时在聊天流里显示错误，不只依赖 toast", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.objectDraftChat.mockRejectedValue(new Error("请求超时"))
    document.getElementById("generate-chat-input").value = "设计一个典型 dnd 圣骑士"

    await generateView._sendChatMessage()

    const html = document.getElementById("generate-chat-messages")?.innerHTML || ""
    expect(html).toContain("设计一个典型 dnd 圣骑士")
    expect(html).toContain("聊天失败：请求超时")
    expect(api.generate.objectDraftChat).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "设计一个典型 dnd 圣骑士" }],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(toast).toHaveBeenCalledWith("聊天失败：请求超时", "error")
  })

  it("主输入框粘贴已有对话后直接点击生成，会把输入内容作为生成上下文", async () => {
    document.body.innerHTML = await generateView.render()
    api.generate.generateObjectDraft.mockResolvedValue({
      entity: {
        id: "e1",
        name: "沈无咎",
        entity_type: "character",
        status: "draft",
        summary: "旧友型反派",
      },
    })
    document.getElementById("generate-chat-input").value = "外部 Chatbox：反派不是纯恶人。"

    await generateView._generateObjectDraft()

    expect(api.generate.generateObjectDraft).toHaveBeenCalledWith(
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

    expect(generateView._buildPayload()).toEqual(expect.objectContaining({
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
    expect(generateView._buildPayload()).toEqual(expect.objectContaining({
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
    api.generate.generateObjectDraft.mockResolvedValue({
      entity: { id: "e1", name: "普通草稿", entity_type: "character", status: "draft" },
    })

    await generateView._generateObjectDraft()
    expect(api.generate.generateObjectDraft).toHaveBeenLastCalledWith(
      expect.objectContaining({ quality_mode: "fast" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    document.getElementById("generate-quality-pro").checked = true
    await generateView._generateObjectDraft()
    expect(api.generate.generateObjectDraft).toHaveBeenLastCalledWith(
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

  it("章节选择不会因预览回读上限隐藏后续章节", async () => {
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
    expect(api.writing.get).toHaveBeenCalledTimes(20)
    expect(api.writing.get).not.toHaveBeenCalledWith("draft-21", "p1")
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

    await generateView._generateObjectDraft()

    expect(api.generate.generateObjectDraft).not.toHaveBeenCalled()
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
    api.generate.objectDraftChat.mockImplementation((_payload, options) => {
      signals.push(options?.signal)
      return deferreds[0].promise
    })
    api.generate.generateObjectDraft.mockImplementation((_payload, options) => {
      signals.push(options?.signal)
      return deferreds[1].promise
    })

    deferreds.push(makeDeferred(), makeDeferred())
    generateView._messages = [{ role: "user", content: "聊" }]
    document.getElementById("generate-chat-input").value = "继续聊"

    generateView._sendChatMessage()
    generateView._generateObjectDraft()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(signals).toHaveLength(2)
    expect(signals.every((signal) => signal && !signal.aborted)).toBe(true)
    expect(api.generate.objectDraftChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(api.generate.generateObjectDraft).toHaveBeenCalledWith(
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
    expect(toast).toHaveBeenCalledWith("角色视角模式必须选择或输入视角人物 ID", "warning")
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
    expect(api.generate.generateObjectDraft).not.toHaveBeenCalled()
    expect(api.context.confirm).not.toHaveBeenCalled()
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
    expect(document.getElementById("generate-pov-result")?.innerHTML).toContain("task-1")
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
    generateView._lastEntity = {
      id: "e1",
      name: "沈无咎",
      entity_type: "character",
      status: "draft",
      summary: "旧友型反派",
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
    api.generate.generateObjectDraft.mockResolvedValue({
      suggestion: { id: "suggestion-1", payload_json: { name: "空城" } },
      context_usage: entityUsage,
    })
    document.body.innerHTML = await generateView.render()
    await generateView._generateObjectDraft()

    document.getElementById("generate-chat-input").value = "继续讨论"
    api.generate.objectDraftChat.mockResolvedValue({ reply: "好", context_usage: chatUsage })
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
    expect(payload.selected_world_bible_draft_ids).toEqual([])
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
    expect(toast).toHaveBeenCalledWith("角色视角模式必须选择或输入视角人物 ID", "warning")
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
