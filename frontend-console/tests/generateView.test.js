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
  generateView._lastEntity = null
  generateView._busy = false
  generateView._renderTimeout = null
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
  }
  generateView._lastContextBundle = null
  generateView._lastContextSource = null
  generateView._lastContextMarkdown = null
  generateView._lastContextRequestParams = null
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

describe("generateView chatbox", () => {
  it("初始页面显示 Chatbox、模板、高质量和生成按钮", async () => {
    const html = await generateView.render()

    expect(html).toContain("不带模板")
    expect(html).toContain("人物")
    expect(html).toContain("编辑模板")
    expect(html).toContain("高质量")
    expect(html).toContain("直接聊，或把其他 Chatbox 的完整讨论粘贴到这里")
    expect(html).toContain("生成对象（数据库草稿）")
    expect(html).toContain("自由对话")
    expect(html).toContain("角色视角正文")
    expect(html).toContain("任务")
    expect(html).toContain("上下文预览")
    expect(html).not.toContain("generate-pasted-context")
  })

  it("在页面标题栏挂载生成中心说明，离开时清理", () => {
    document.body.innerHTML = `
      <header id="workspace-header"><h2 id="view-title">生成中心</h2><div id="view-actions"></div></header>
      <div class="topbar-center"><span id="topbar-module">生成中心</span></div>
    `

    generateView._mountTopbarNote()

    expect(document.getElementById("topbar-generate-note")?.textContent).toBe("先自由聊，确定后再生成数据库草稿。")

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

  it("离开视图时取消 render 的 setTimeout，避免回调操作新视图 DOM", async () => {
    vi.useFakeTimers()
    const spy = vi.spyOn(generateView, "_bindEvents")
    await generateView.render()

    generateView.onLeave()
    vi.runAllTimers()

    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
    vi.useRealTimers()
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
    expect(html).toContain("执行任务")
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
      limit: 200,
    })
    expect(api.generate.generateObjectDraft).not.toHaveBeenCalled()
    expect(api.context.confirm).not.toHaveBeenCalled()
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
      task: "基于所选 Scene 和 POV 角色有限认知，生成正文候选草稿",
      scope: "chapter",
      chapter_index: 1,
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: true,
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
    const html = await generateView.render()

    expect(html).toContain("查看上下文")
  })

  it("从自由对话查看上下文切换到预览标签", async () => {
    generateView._messages = [{ role: "user", content: "设计一个反派" }]
    document.body.innerHTML = await generateView.render()

    await generateView._viewGenerationContext()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        task: "基于当前聊天和模板生成对象草稿",
        messages: [{ role: "user", content: "设计一个反派" }],
      }),
      expect.anything(),
    )
    expect(generateView._generateSubTab).toBe("preview")
  })

  it("查看上下文 payload 携带 quality_mode", async () => {
    generateView._messages = [{ role: "user", content: "设计一个反派" }]
    generateView._qualityMode = "pro"
    document.body.innerHTML = await generateView.render()

    await generateView._viewGenerationContext()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({ quality_mode: "pro" }),
      expect.anything(),
    )
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
