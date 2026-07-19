import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))
vi.mock("../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn(async () => []), setItems: vi.fn() })),
}))

import GenerateView from "../../../vue/views/generate/GenerateView.vue"
import { emptyGenerateSession, generateSessionKey } from "../../../vue/views/generate/generateSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

let api
let state
let router
let toast
let showModalHtml

function baseProps(overrides = {}) {
  return {
    projectId: "p1", tab: "world", preset: "custom", sourcePageId: null, targetKind: "core_entity",
    sessionKey: generateSessionKey("p1"), initialSession: emptyGenerateSession(),
    templates: [{ id: "builtin:none", value: "builtin:none", label: "不带模板", prompt: "自由", object_template: "none", is_builtin: true, version_number: 1 }],
    activationProfiles: [], sourcePage: null, sourceDraft: null, worldCategories: [{ category_key: "custom", name: "自定义", status: "active" }],
    worldPageTemplates: [], worldScenes: [], worldThreads: [], worldCharacters: [], worldEntities: [], worldWorkspaceWarning: null,
    restoredWorldResult: null, povChapters: [], povCharacters: [], povLoadWarning: null,
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  document.body.innerHTML = '<div id="topbar-module"></div><div id="modal-body"></div>'
  api = {
    generate: {
      worldChat: vi.fn(), generateWorldSuggestion: vi.fn(), applyWorldPageDraft: vi.fn(),
      listPromptTemplates: vi.fn(), createPromptTemplate: vi.fn(), copyPromptTemplate: vi.fn(), updatePromptTemplate: vi.fn(), listPromptTemplateRevisions: vi.fn(),
    },
    context: { compile: vi.fn(), render: vi.fn() },
    world: { listBiblePages: vi.fn(), listBibleDrafts: vi.fn(), listBibleCategories: vi.fn(), listBiblePageTemplates: vi.fn(), listCharacters: vi.fn(), listEntities: vi.fn(), getEntity: vi.fn() },
    outline: { listScenesOrdered: vi.fn(), listThreads: vi.fn(), listScenesByChapter: vi.fn(), getSceneWorkbench: vi.fn(), getScene: vi.fn() },
    writing: { listChapters: vi.fn(), get: vi.fn(), getDraft: vi.fn(), generate: vi.fn() },
    tasks: { get: vi.fn() },
  }
  state = { currentProjectId: "p1", currentProject: { title: "项目一" }, viewStates: {} }
  router = { navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams()) }
  toast = vi.fn()
  showModalHtml = vi.fn((title, body) => { document.getElementById("modal-body").innerHTML = body })
  setBridgeOverrides({ api, state, router, toast, confirm: vi.fn(() => true), showModalHtml, closeModal: vi.fn(), esc: globalThis.esc })
  confirmAiReference.mockReset()
})

afterEach(() => resetBridgeOverrides())

describe("GenerateView Vue behavior matrix", () => {
  it("renders the world workspace without v-html and completes chat", async () => {
    api.generate.worldChat.mockResolvedValue({ reply: "旧友型反派", context_usage: { revision_id: "r-chat" } })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("帮我设计反派")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-chat-messages").text()).toContain("旧友型反派"))
    expect(api.generate.worldChat).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", messages: [{ role: "user", content: "帮我设计反派" }] }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.html()).not.toContain("v-html")
  })

  it("turns pasted composer text into a project-scoped pending world suggestion", async () => {
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: {
        kind: "core_entity",
        suggestion: { id: "suggestion-1", payload_json: { name: "雾港", entity_type: "location" } },
      },
      context_usage: { revision_id: "revision-1" },
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("把这段外部对话收束为港口设定")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-result").text()).toContain("雾港"))
    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      target: expect.objectContaining({ kind: "core_entity" }),
      messages: [{ role: "user", content: "把这段外部对话收束为港口设定" }],
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it("aborts an in-flight world request and rejects its late response after unmount", async () => {
    let resolve
    api.generate.worldChat.mockImplementation((_payload, options) => new Promise((done) => { resolve = done; expect(options.signal.aborted).toBe(false) }))
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("迟到请求")
    const button = wrapper.get('[data-action="send-chat-message"]')
    await button.trigger("click")
    const signal = api.generate.worldChat.mock.calls[0][1].signal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    resolve({ reply: "不应回写" })
    await Promise.resolve()
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("不应回写"), expect.anything())
  })

  it("keeps silent preview errors inline and does not toast", async () => {
    api.context.compile.mockRejectedValue(new Error("compile down"))
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("测试任务")
    await wrapper.get('[data-action="preview-task-context"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#gen-task-output").text()).toContain("compile down"))
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("compile down"), "error")
  })

  it("compiles a task into preview and renders API markdown as text", async () => {
    api.context.compile.mockResolvedValue({
      scope: "arc", reveal_mode: "author_safe", total_tokens: 12,
      sections: [{ key: '<img src=x onerror="boom">', tier: "core", token_count: 12 }],
    })
    api.context.render.mockResolvedValue({ markdown: '<img src=x onerror="boom">' })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("检查主线冲突")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("已加载 1 段上下文"))
    expect(api.context.compile).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", task: "检查主线冲突", budget_tokens: 0 }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toContain("<img"))
    expect(wrapper.find("img").exists()).toBe(false)
  })

  it("uses character confirmation, polls with project ownership, then opens the exact writing candidate", async () => {
    api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
    confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "避免剧透" })
    api.writing.generate.mockResolvedValue({ task_id: "task-1" })
    api.tasks.get.mockResolvedValue({ status: "done", progress: 1, result: { draft_id: "draft-1" } })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "pov_prose", povChapters: [{ chapter_index: 1, title: "旧怨" }], povCharacters: [{ entity_id: "char-1", name: "秦岚" }] }), attachTo: document.body })
    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.findAll("#generate-pov-scene option")).toHaveLength(2))
    await wrapper.get("#generate-pov-scene").setValue("scene-1")
    await wrapper.get("#generate-pov-instruction").setValue("保持克制")
    await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-pov-result").text()).toContain("打开并审阅建议"))
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", reveal_mode: "character", viewpoint_character_id: "char-1" }))
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(api.writing.generate.mock.calls[0][0].instruction).toContain("用户指令是作者意图，不等于角色知识")
    await wrapper.get('[data-action="open-generated-destination"]').trigger("click")
    expect(state.viewStates.writing).toEqual(expect.objectContaining({ projectId: "p1", currentChapter: 1, currentDraftId: "draft-1", isReadonly: true }))
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("draft_id")).toBe("draft-1")
  })

  it("loads template history into the owned modal without injecting API text as markup", async () => {
    api.generate.listPromptTemplateRevisions.mockResolvedValue([{ version_number: 2, prompt_text: '<img src=x onerror="boom">' }])
    const wrapper = mount(GenerateView, { props: baseProps({ templates: [{ id: "tpl-1", value: "tpl-1", label: "自定义", prompt: "当前", object_template: "custom", is_builtin: false, version_number: 3 }], initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-1" } }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-history-load").click()
    await vi.waitFor(() => expect(document.getElementById("generate-template-history").textContent).toContain("v2"))
    expect(document.getElementById("generate-template-history").querySelector("img")).toBeNull()
    expect(api.generate.listPromptTemplateRevisions).toHaveBeenCalledWith("tpl-1", "p1")
  })

  it("copies a builtin template into the project before saving its prompt", async () => {
    api.generate.copyPromptTemplate.mockResolvedValue({ id: "tpl-copy" })
    api.generate.updatePromptTemplate.mockResolvedValue({
      id: "tpl-copy", name: "不带模板副本", prompt_text: "只保留可验证事实",
      object_template: "none", is_builtin: false, version_number: 2,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-prompt").value = "只保留可验证事实"
    const save = showModalHtml.mock.calls[0][2][0].handler
    await save()
    expect(api.generate.copyPromptTemplate).toHaveBeenCalledWith("builtin:none", { novel_id: "p1", name: "不带模板" })
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith("tpl-copy", "p1", { prompt_text: "只保留可验证事实" })
  })

  it("creates and selects a new project template", async () => {
    api.generate.createPromptTemplate.mockResolvedValue({
      id: "tpl-new", name: "推理约束", prompt_text: "优先检查时间线",
      object_template: "custom", is_builtin: false, version_number: 1,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-name").value = "推理约束"
    document.getElementById("generate-template-editor-prompt").value = "优先检查时间线"

    const created = await showModalHtml.mock.calls[0][2][1].handler()

    expect(created).not.toBe(false)
    expect(api.generate.createPromptTemplate).toHaveBeenCalledWith({
      novel_id: "p1", name: "推理约束", object_template: "custom", prompt_text: "优先检查时间线",
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-action="select-object-template"]').some((button) => button.text() === "推理约束")).toBe(true))
  })

  it("loads chapter previews in batches of five and enforces the 20 chapter UI cap", async () => {
    const chapters = Array.from({ length: 21 }, (_, index) => ({ id: `draft-${index + 1}`, chapter_index: index + 1, title: `第 ${index + 1} 章` }))
    api.writing.listChapters.mockResolvedValue({ chapters })
    let active = 0
    let maxActive = 0
    api.writing.get.mockImplementation(async (id) => {
      active += 1
      maxActive = Math.max(maxActive, active)
      await Promise.resolve()
      active -= 1
      return { title: id, content: `${id} 正文` }
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get('[data-action="select-source-chapters"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith(
      "选择附带正文", expect.any(String), expect.any(Array), undefined,
    ))

    expect(maxActive).toBe(5)
    expect(api.writing.get).toHaveBeenCalledTimes(21)
    document.querySelectorAll('.generate-chapter-card input[type="checkbox"]').forEach((input) => { input.checked = true })
    const confirmSelection = showModalHtml.mock.calls.at(-1)[2].find((button) => button.text === "确认选择").handler
    expect(confirmSelection()).toBe(false)
    expect(toast).toHaveBeenCalledWith("每次最多附带 20 章正文", "warning")
  })

  it("retries transient POV polling failures and finishes the owned task", async () => {
    vi.useFakeTimers()
    try {
      api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
      confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "" })
      api.writing.generate.mockResolvedValue({ task_id: "task-retry" })
      api.tasks.get
        .mockRejectedValueOnce(new Error("temporary network failure"))
        .mockResolvedValueOnce({ status: "running", progress: 0.4 })
        .mockResolvedValueOnce({ status: "done", progress: 1, result: { draft_id: "draft-retry" } })
      const wrapper = mount(GenerateView, { props: baseProps({
        tab: "pov_prose",
        povChapters: [{ chapter_index: 1, title: "旧怨" }],
        povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
      }), attachTo: document.body })
      await wrapper.get("#generate-pov-chapter").setValue("1")
      await flushPromises()
      await wrapper.get("#generate-pov-scene").setValue("scene-1")
      await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(2)
      expect(wrapper.get("#generate-pov-result").text()).toContain("40%")

      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(3)
      expect(wrapper.get("#generate-pov-result").text()).toContain("打开并审阅建议")
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("draft-retry"), "success")
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    ["失败", { status: "failed", error_message: "上游生成失败" }, "上游生成失败"],
    ["取消", { status: "cancelled" }, "角色视角正文生成已取消"],
    ["缺少建议 ID", { status: "done", result: {} }, "任务已完成，但未返回正文建议 ID"],
  ])("shows the POV %s terminal state instead of leaving an empty result", async (_label, task, expectedMessage) => {
    api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
    confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "" })
    api.writing.generate.mockResolvedValue({ task_id: "task-terminal" })
    api.tasks.get.mockResolvedValue(task)
    const wrapper = mount(GenerateView, { props: baseProps({
      tab: "pov_prose",
      povChapters: [{ chapter_index: 1, title: "旧怨" }],
      povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
    }), attachTo: document.body })
    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.findAll("#generate-pov-scene option")).toHaveLength(2))
    await wrapper.get("#generate-pov-scene").setValue("scene-1")
    await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")

    await vi.waitFor(() => expect(wrapper.get("#generate-pov-result").text()).toContain(expectedMessage))
    expect(toast).toHaveBeenCalledWith(`角色视角正文生成失败：${expectedMessage}`, "error")
  })

  it("shows escaped context provenance returned by the generation API", async () => {
    api.generate.worldChat.mockResolvedValue({
      reply: "已生成",
      context_usage: {
        section_key: "world_bible_synopsis", status: "fresh", token_count: 42,
        revision_id: '<img src=x onerror="boom">', source_hash: "source-1",
        block_hash: "block-1", context_snapshot_id: "snapshot-1", stale: false, fallback: false,
      },
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("审计上下文")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="view-generation-context"]').exists()).toBe(true))
    await wrapper.get('[data-action="view-generation-context"]').trigger("click")

    expect(showModalHtml).toHaveBeenLastCalledWith("本次实际使用的上下文", expect.any(String), [], { size: "large" })
    expect(document.getElementById("modal-body").textContent).toContain('<img src=x onerror="boom">')
    expect(document.getElementById("modal-body").querySelector("img")).toBeNull()
    expect(document.getElementById("modal-body").textContent).toContain("snapshot-1")
  })

  it("copies and exports rendered context with the browser APIs", async () => {
    api.context.compile.mockResolvedValue({ scope: "arc", sections: [], total_tokens: 0 })
    api.context.render.mockResolvedValue({ markdown: "# 审计上下文" })
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    const createObjectURL = vi.fn(() => "blob:context")
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("审计上下文")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="render-task-md"]').exists()).toBe(true))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 审计上下文"))

    await wrapper.get('[data-action="copy-task-md"]').trigger("click")
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith("# 审计上下文"))
    await wrapper.get('[data-action="export-task-md"]').trigger("click")

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:context")
    expect(toast).toHaveBeenCalledWith("上下文已导出为 Markdown 文件", "success")
    click.mockRestore()
  })

  it("warns when the clipboard API rejects without losing rendered context", async () => {
    api.context.compile.mockResolvedValue({ scope: "arc", sections: [], total_tokens: 0 })
    api.context.render.mockResolvedValue({ markdown: "# 仍可手动复制" })
    const writeText = vi.fn(async () => { throw new Error("clipboard denied") })
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("复制失败测试")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="render-task-md"]').exists()).toBe(true))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 仍可手动复制"))

    await wrapper.get('[data-action="copy-task-md"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("复制失败，请手动选择复制", "warning"))
    expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 仍可手动复制")
  })

  it("keeps the chapter picker usable when individual preview fetches fail", async () => {
    api.writing.listChapters.mockResolvedValue({ chapters: [
      { id: "draft-broken", chapter_index: 1, title: "回退标题" },
      { chapter_index: 2, title: "摘要标题" },
    ] })
    api.writing.get.mockRejectedValue(new Error("draft unavailable"))
    api.writing.getDraft.mockResolvedValue({ title: "可用工作稿", content: "这是可用的第二章正文" })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get('[data-action="select-source-chapters"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith(
      "选择附带正文", expect.any(String), expect.any(Array), undefined,
    ))

    expect(api.writing.get).toHaveBeenCalledWith("draft-broken", "p1")
    expect(api.writing.getDraft).toHaveBeenCalledWith(2, "p1")
    expect(document.getElementById("modal-body").textContent).toContain("回退标题")
    expect(document.getElementById("modal-body").textContent).toContain("暂无正文摘录")
    expect(document.getElementById("modal-body").textContent).toContain("这是可用的第二章正文")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("加载章节失败"), "error")
  })

  it("drops a late custom-template save after the Generate view unmounts", async () => {
    let resolveUpdate
    api.generate.updatePromptTemplate.mockImplementation(() => new Promise((resolve) => { resolveUpdate = resolve }))
    const wrapper = mount(GenerateView, { props: baseProps({
      templates: [{
        id: "tpl-owned", value: "tpl-owned", label: "当前自定义", prompt: "旧提示词",
        object_template: "custom", is_builtin: false, version_number: 1,
      }],
      initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-owned" },
    }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-name").value = "修订名称"
    document.getElementById("generate-template-editor-prompt").value = "修订提示词"
    const pending = showModalHtml.mock.calls[0][2][0].handler()
    await flushPromises()
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith("tpl-owned", "p1", {
      name: "修订名称", prompt_text: "修订提示词",
    })

    wrapper.unmount()
    resolveUpdate({
      id: "tpl-owned", name: "修订名称", prompt_text: "修订提示词",
      object_template: "custom", is_builtin: false, version_number: 2,
    })
    await expect(pending).resolves.toBe(false)
    expect(toast).not.toHaveBeenCalledWith("模板已保存", "success")
  })

  it("applies an edited full-page proposal only to the owned project draft", async () => {
    api.generate.applyWorldPageDraft.mockResolvedValue({ draft: { id: "draft-page-1", page_id: "page-1" } })
    const result = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-page-1" },
      proposal: { operation: "replace_existing", page: { title: "旧标题", page_type: "custom", free_text: "概览", sections_json: [], linked_asset_refs_json: [] } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sourcePage: { id: "page-1", title: "旧标题", sections_json: [] }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("作者修订标题")
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(router.navigate).toHaveBeenCalled())
    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "suggestion-page-1",
      expect.objectContaining({ page: expect.objectContaining({ title: "作者修订标题" }) }),
      "p1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(router.navigate.mock.calls.at(-1)[3].get("draft_id")).toBe("draft-page-1")
  })

  it("keeps an edited page proposal in place when the baseline conflicts", async () => {
    api.generate.applyWorldPageDraft.mockRejectedValue(Object.assign(new Error("conflict"), { status: 409 }))
    const result = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-conflict" },
      proposal: { operation: "replace_existing", page: { title: "旧标题", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sourcePage: { id: "page-1", title: "旧标题", sections_json: [] }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("尚未应用的作者修订")
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("未覆盖新修改"), "warning"))
    expect(wrapper.get("#generate-page-title").element.value).toBe("尚未应用的作者修订")
    expect(router.navigate).not.toHaveBeenCalled()
  })
})
