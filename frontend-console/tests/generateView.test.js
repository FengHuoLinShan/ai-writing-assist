import { describe, it, expect, vi, beforeEach } from "vitest"
import generateView from "../views/generateView.js"

beforeEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
  localStorage.clear()
  state.currentProjectId = "p1"
  generateView._template = "none"
  generateView._messages = []
  generateView._pastedContext = ""
  generateView._selectedChapters = []
  generateView._qualityMode = "fast"
  generateView._lastEntity = null
  generateView._busy = false
  generateView._templatePromptOverrides = {}
  generateView._customTemplates = []
})

describe("generateView chatbox", () => {
  it("初始页面显示 Chatbox、模板、高质量和生成按钮", async () => {
    const html = await generateView.render()

    expect(html).toContain("不带模板")
    expect(html).toContain("人物")
    expect(html).toContain("编辑模板")
    expect(html).toContain("高质量")
    expect(html).toContain("直接聊，或把其他 Chatbox 的完整讨论粘贴到这里")
    expect(html).toContain("生成对象（数据库草稿）")
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

    expect(api.generate.objectDraftChat).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      template: "none",
      quality_mode: "fast",
      messages: [{ role: "user", content: "帮我设计一个反派" }],
    }))
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
    expect(api.generate.objectDraftChat).toHaveBeenCalledWith(expect.objectContaining({
      messages: [{ role: "user", content: "设计一个典型 dnd 圣骑士" }],
    }))
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

    expect(api.generate.generateObjectDraft).toHaveBeenCalledWith(expect.objectContaining({
      messages: [{ role: "user", content: "外部 Chatbox：反派不是纯恶人。" }],
      pasted_context: undefined,
      quality_mode: "fast",
    }))
    expect(document.getElementById("generate-result")?.innerHTML).toContain("沈无咎")
    expect(document.getElementById("generate-chat-input").value).toBe("")
  })

  it("编辑模板弹窗可以查看并保存内置模板提示词", async () => {
    document.body.innerHTML = await generateView.render()

    generateView._openTemplateEditor()

    expect(showModal).toHaveBeenCalledWith(
      "编辑模板",
      expect.stringContaining("不预设对象类型"),
      expect.any(Array),
    )

    document.body.insertAdjacentHTML("beforeend", generateView._renderTemplateEditor("character"))
    document.getElementById("generate-template-editor-select").value = "character"
    document.getElementById("generate-template-editor-prompt").value = "人物模板：必须写清楚誓言与代价。"

    generateView._saveTemplateFromEditor()

    expect(generateView._templatePromptOverrides.character).toBe("人物模板：必须写清楚誓言与代价。")
    generateView._messages = [{ role: "user", content: "设计一个圣骑士" }]
    generateView._template = "character"

    expect(generateView._buildPayload()).toEqual(expect.objectContaining({
      template: "character",
      template_name: "人物",
      template_prompt: "人物模板：必须写清楚誓言与代价。",
    }))
  })

  it("可以创建新提示词模板并用于生成 payload", async () => {
    document.body.innerHTML = await generateView.render()
    document.body.insertAdjacentHTML("beforeend", generateView._renderTemplateEditor("none"))
    document.getElementById("generate-template-editor-name").value = "DND 圣骑士"
    document.getElementById("generate-template-editor-prompt").value = "生成 DND 圣骑士对象，突出誓言、神术、阵营冲突。"

    generateView._createTemplateFromEditor()

    expect(generateView._customTemplates).toHaveLength(1)
    expect(document.getElementById("generate-template-row")?.textContent).toContain("DND 圣骑士")
    expect(generateView._buildPayload()).toEqual(expect.objectContaining({
      template: "custom",
      template_name: "DND 圣骑士",
      template_prompt: "生成 DND 圣骑士对象，突出誓言、神术、阵营冲突。",
    }))
  })

  it("勾选高质量后提交 pro，否则提交 fast", async () => {
    document.body.innerHTML = await generateView.render()
    generateView._messages = [{ role: "user", content: "生成一个反派" }]
    api.generate.generateObjectDraft.mockResolvedValue({
      entity: { id: "e1", name: "普通草稿", entity_type: "character", status: "draft" },
    })

    await generateView._generateObjectDraft()
    expect(api.generate.generateObjectDraft).toHaveBeenLastCalledWith(expect.objectContaining({
      quality_mode: "fast",
    }))

    document.getElementById("generate-quality-pro").checked = true
    await generateView._generateObjectDraft()
    expect(api.generate.generateObjectDraft).toHaveBeenLastCalledWith(expect.objectContaining({
      quality_mode: "pro",
    }))
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
      expect.stringContaining("主角在雨夜背叛"),
      expect.any(Array),
    )
    document.body.insertAdjacentHTML("beforeend", showModal.mock.calls[0][1])
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
})
