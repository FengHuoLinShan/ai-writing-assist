import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WritingView from "../../../vue/views/writing/WritingView.vue"
import { getAppState, resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { clearWritingSession } from "../../../vue/views/writing/writingSession.js"
import mapQuickCreateView from "../../../views/mapQuickCreateView.js"

function props(overrides = {}) {
  return {
    projectId: "p1",
    chapterList: [1],
    chapters: { 1: { chapter_index: 1, title: "<img src=x>", word_count: 2, status: "draft" } },
    scenes: [{ id: "s1", title: "Scene <script>", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 20 }] }],
    chapterLoadError: null,
    authorPreferences: { dailyGoal: 1000, editorFont: "serif", defaultFocusMode: false },
    requestedLocation: { chapter: 1, draftId: "d1" },
    ...overrides,
  }
}

describe("WritingView", () => {
  let confirmMock
  let confirmActionMock
  let toastMock
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    clearWritingSession()
    const state = { currentProjectId: "p1", viewStates: {} }
    const api = globalThis.api
    api.writing.get.mockResolvedValue({ id: "d1", novel_id: "p1", title: "<img src=x>", content: "正文", version_number: 1, status: "draft" })
    api.writing.autosave.mockImplementation(async (_id, payload) => ({
      id: "d1",
      novel_id: "p1",
      status: "draft",
      version_number: 1,
      ...payload,
    }))
    api.writing.getVersionHistory.mockResolvedValue({ versions: [{ id: "d1", version_number: 1, status: "draft" }] })
    api.writing.listConflictChecks.mockResolvedValue({ items: [] })
    api.world.getMapSceneSummary.mockResolvedValue({ summary: "安全" })
    confirmMock = vi.fn(() => true)
    confirmActionMock = vi.fn((_message, onConfirm) => onConfirm())
    toastMock = vi.fn()
    setBridgeOverrides({ state, api, confirm: confirmMock, confirmAction: confirmActionMock, toast: toastMock, router: globalThis.router })
  })
  afterEach(() => {
    vi.useRealTimers()
    resetBridgeOverrides()
  })

  it("Vue 模板拥有写作台 DOM，动态内容按文本转义", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    expect(wrapper.find("#writing-editor").exists()).toBe(true)
    expect(wrapper.find("#writing-tree-container img").exists()).toBe(false)
    expect(wrapper.find("#writing-tree-container").text()).toContain("<img src=x>")
    expect(wrapper.find("#writing-tree-container").text()).toContain("Scene <script>")
    expect(wrapper.find("script").exists()).toBe(false)
    wrapper.unmount()
  })

  it("同章点击第二个 Scene 后保留显式写作位置", async () => {
    const wrapper = mount(WritingView, {
      props: props({
        scenes: [
          { id: "s1", title: "入口", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 1 }] },
          { id: "s2", title: "密道", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 1, end_pos: 2 }] },
        ],
      }),
      attachTo: document.body,
    })
    await flushPromises()

    const secondScene = wrapper.findAll(".scene-tree-label").find((button) => button.text().includes("密道"))
    await secondScene.trigger("click")
    await flushPromises()

    expect(wrapper.find(".scene-tree-label--current").text()).toContain("密道")
    expect(getAppState().viewStates.writing).toMatchObject({
      projectId: "p1",
      currentChapter: 1,
      currentSceneId: "s2",
    })
    wrapper.unmount()
  })

  it("不把 rail 响应式默认值误存为用户选择", async () => {
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: null }),
      attachTo: document.body,
    })
    await flushPromises()

    const rail = wrapper.get(".writing-tree-rail")
    const key = "workspace-rail:p1:writing:chapters"
    await rail.trigger("toggle")
    expect(sessionStorage.getItem(key)).toBeNull()

    rail.element.open = !rail.element.open
    await rail.trigger("toggle")
    expect(sessionStorage.getItem(key)).toBe(rail.element.open ? "open" : "closed")
    wrapper.unmount()
  })

  it("移动速记通过工作区保存为工作稿", async () => {
    const originalWidth = window.innerWidth
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    try {
      const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
      await flushPromises()
      const editor = wrapper.get('#mobile-note-editor')
      await editor.setValue("移动速记")
      await wrapper.findAll("button").find((button) => button.text() === "保存为工作稿").trigger("click")
      await flushPromises()

      expect(globalThis.api.writing.autosave).toHaveBeenCalledWith(
        "d1",
        expect.objectContaining({ content: "移动速记" }),
        "p1",
      )
      expect(toastMock).toHaveBeenCalledWith("已保存到工作稿", "success")
      wrapper.unmount()
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth })
    }
  })

  it("输入正文更新 reactive 状态且保留原有 DOM id", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    const editor = wrapper.find("#writing-editor")
    await editor.setValue("作者新输入")
    expect(editor.element.value).toBe("作者新输入")
    expect(wrapper.find("#writing-save-status").text()).toBe("未保存")
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("作者新输入")
    wrapper.unmount()
  })

  it("快速切换章节时只保存旧章节并以最后一次选择为准", async () => {
    let resolveSave
    globalThis.api.writing.autosave.mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve }))
    globalThis.api.writing.getVersionHistory.mockImplementation(async (chapter) => ({
      versions: [{ id: `d${chapter}`, version_number: 1, status: "draft" }],
    }))
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: Number(String(id).slice(1)),
      title: `第 ${String(id).slice(1)} 章`,
      content: `正文 ${String(id).slice(1)}`,
      version_number: 1,
      status: "draft",
    }))
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2, 3],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
          3: { chapter_index: 3, title: "第三章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("第一章尚未保存的正文")

    const vm = wrapper.vm.$.setupState.vm
    const selectSecond = vm.selectChapter(2)
    await vi.waitFor(() => expect(globalThis.api.writing.autosave).toHaveBeenCalledTimes(1))
    const selectThird = vm.selectChapter(3)
    resolveSave({ id: "d1", version_number: 2, status: "draft" })
    await Promise.all([selectSecond, selectThird])
    await flushPromises()

    expect(globalThis.api.writing.autosave).toHaveBeenCalledWith(
      "d1",
      expect.objectContaining({ content: "第一章尚未保存的正文" }),
      "p1",
    )
    expect(vm.selectedChapter.value).toBe(3)
    expect(vm.editorState.chapter).toBe(3)
    expect(globalThis.api.writing.get).not.toHaveBeenCalledWith("d2", "p1")
    expect(globalThis.api.writing.get).toHaveBeenCalledWith("d3", "p1")
    wrapper.unmount()
  })

  it("从 Scene 地图摘要沿用 open_target 打开精确深链", async () => {
    globalThis.api.world.getMapSceneSummary.mockResolvedValue({
      summary: "安全",
      open_target: {
        map_id: "m1",
        scene_id: "s1",
        focus_entity_id: "e1",
        focus_path_id: "path1",
        focus_layer_node_id: "layer1",
        mode: "map",
      },
    })
    const open = vi.spyOn(window, "open").mockImplementation(() => null)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "地图").trigger("click")
    await wrapper.find(".writing-map-summary button").trigger("click")

    expect(open).toHaveBeenCalledWith(
      "#workbench/p1/map?map_id=m1&scene_id=s1&focus_entity_id=e1&focus_path_id=path1&focus_layer_node_id=layer1&mode=live",
      "_blank",
      "noopener",
    )
    wrapper.unmount()
  })

  it("未选章节时保留项目级提取入口，章节级操作保持禁用", async () => {
    const wrapper = mount(WritingView, { props: props({ requestedLocation: null }), attachTo: document.body })
    await flushPromises()

    expect(wrapper.find("#writing-editor").exists()).toBe(false)
    expect(wrapper.find("#btn-autosave").attributes("disabled")).toBeDefined()
    const extractionButton = wrapper.findAll("button").find((button) => button.text() === "从正文提取 Scene")
    expect(extractionButton).toBeDefined()
    await extractionButton.trigger("click")
    expect(wrapper.find('[aria-label="自动提取"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it("无章节时隐藏正文提取入口", async () => {
    const wrapper = mount(WritingView, {
      props: props({ chapterList: [], chapters: {}, scenes: [], requestedLocation: null }),
      attachTo: document.body,
    })
    await flushPromises()

    expect(wrapper.text()).toContain("请从左侧选择章节开始写作")
    expect(wrapper.findAll("button").some((button) => button.text() === "从正文提取 Scene")).toBe(false)
    wrapper.unmount()
  })

  it("组件卸载后丢弃 Scene 晚到响应", async () => {
    let resolveSummary
    globalThis.api.world.getMapSceneSummary.mockReturnValue(new Promise((resolve) => { resolveSummary = resolve }))
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await vi.waitFor(() => expect(globalThis.api.world.getMapSceneSummary).toHaveBeenCalled())
    wrapper.unmount()
    resolveSummary({ summary: "不应写回" })
    await flushPromises()
    expect(document.body.textContent).not.toContain("不应写回")
  })

  it("保留原写作台可达命令，对话框仍由 Vue 模板渲染", async () => {
    globalThis.api.writing.getVersionHistory.mockResolvedValue({ versions: [
      { id: "d2", version_number: 2, status: "draft" },
      { id: "d1", version_number: 1, status: "draft" },
    ] })
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      title: "第一章",
      content: id === "d2" ? "新正文" : "旧正文",
      version_number: id === "d2" ? 2 : 1,
      status: "draft",
    }))
    globalThis.api.outline.listThreads.mockResolvedValue({ items: [{ id: "t1", title: "剧情 <script>", chapter_ids: [1] }] })
    const wrapper = mount(WritingView, { props: props({ requestedLocation: { chapter: 1, draftId: "d2" } }), attachTo: document.body })
    await flushPromises()

    for (const label of ["AI 续写", "AI 正文建议", "AI 角色视角建议", "启动深度导入", "从正文提取 Scene", "世界对象与别名/关系自动提取", "剧情线自动提取", "导出本章", "打开地图"]) {
      expect(wrapper.findAll("button").some((button) => button.text() === label)).toBe(true)
    }

    await wrapper.findAll("button").find((button) => button.text() === "从正文提取 Scene").trigger("click")
    expect(wrapper.find('[aria-label="自动提取"]').exists()).toBe(true)
    wrapper.vm.$.setupState.vm.autoExtraction.open = false

    await wrapper.find("#btn-conflict-check").trigger("click")
    expect(wrapper.find('[aria-label="剧情设定冲突检查选项"]').exists()).toBe(true)
    wrapper.vm.$.setupState.vm.conflictOptions.open = false

    await wrapper.findAll("button").find((button) => button.text() === "大纲浮窗").trigger("click")
    await flushPromises()
    expect(wrapper.find("#outline-float-panel").text()).toContain("剧情 <script>")
    expect(wrapper.find("#outline-float-panel script").exists()).toBe(false)

    await wrapper.findAll("button").find((button) => button.text() === "比较").trigger("click")
    await flushPromises()
    expect(wrapper.find('[aria-label="版本历史"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("旧正文")
    expect(wrapper.text()).toContain("新正文")
    wrapper.unmount()
  })

  it("版本与最近冲突检查常驻编辑器顶部操作行", async () => {
    globalThis.api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "check-1", status: "completed", items: [], summary_json: { message: "无未处理冲突" } }],
    })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    const actions = wrapper.get("#writing-editor-buttons")
    expect(actions.find("#writing-versions-container").exists()).toBe(true)
    expect(actions.find("#writing-conflict-strip").exists()).toBe(true)
    expect(actions.find("#writing-conflict-strip").text()).toContain("无未处理冲突")
    expect(wrapper.find("#writing-editor-container > .writing-conflict-strip").exists()).toBe(false)

    await actions.get("#writing-conflict-strip").trigger("keydown", { key: " " })
    expect(wrapper.find('[aria-label="剧情设定冲突检查"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it("章节批量删除保留显式确认与 novel_id 边界", async () => {
    globalThis.api.writing.deleteChapter.mockResolvedValue({ ok: true })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "管理 ▾").trigger("click")
    await wrapper.get('input[aria-label="选择第 1 章"]').setValue(true)
    await wrapper.findAll("button").find((button) => button.text().includes("批量删除章节")).trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.deleteChapter).toHaveBeenCalledWith(1, "p1")
    expect(wrapper.find("#writing-editor").exists()).toBe(false)
    wrapper.unmount()
  })

  it("发布前在无检查记录时必须明确确认", async () => {
    confirmActionMock.mockImplementation(() => {})
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#btn-publish").trigger("click")
    await flushPromises()
    expect(confirmActionMock).toHaveBeenCalledWith(
      expect.stringContaining("还没有剧情设定冲突检查记录"),
      expect.any(Function),
      "继续发布",
    )
    expect(globalThis.api.writing.publish).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("发布前阻断尚有未处理高严重度问题的章节", async () => {
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", summary_json: { open_high_count: 2 } }] })
    confirmActionMock.mockImplementation(() => {})
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#btn-publish").trigger("click")
    await flushPromises()
    expect(confirmActionMock).toHaveBeenCalledWith(
      expect.stringContaining("2 个未处理高严重度问题"),
      expect.any(Function),
      "继续发布",
    )
    expect(globalThis.api.writing.publish).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("发布前冲突检查读取失败时提示错误并停止发布", async () => {
    globalThis.api.writing.listConflictChecks.mockRejectedValue(new Error("检查服务不可用"))
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    await wrapper.get("#btn-publish").trigger("click")
    await flushPromises()

    expect(toastMock).toHaveBeenCalledWith(
      "无法读取发布前冲突检查：检查服务不可用。本次发布已停止，请稍后重试。",
      "error",
    )
    expect(globalThis.api.writing.publish).not.toHaveBeenCalled()
    expect(globalThis.api.writing.autosave).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("发布后处理失败时保留原 payload 并支持手动重试", async () => {
    vi.useFakeTimers()
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", items: [], summary_json: { open_high_count: 0 } }] })
    globalThis.api.writing.publish
      .mockResolvedValueOnce({ task_id: "publish-task", new_version: true })
      .mockResolvedValueOnce({ new_version: false })
    globalThis.api.tasks.get.mockResolvedValue({ status: "failed", error_message: "索引写入失败" })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#btn-publish").trigger("click")
    await flushPromises()
    const firstPayload = globalThis.api.writing.publish.mock.calls[0][0]
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(wrapper.text()).toContain("手动重试")
    await wrapper.findAll("button").find((button) => button.text() === "手动重试").trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.publish).toHaveBeenNthCalledWith(2, firstPayload)
    wrapper.unmount()
  })

  it("基于历史版本创建时，暂存入口改为发布新版本而非覆盖历史稿", async () => {
    globalThis.api.writing.getVersionHistory.mockResolvedValue({ versions: [
      { id: "d2", version_number: 2, status: "draft", updated_at: "u2" },
      { id: "d1", version_number: 1, status: "published", updated_at: "u1" },
    ] })
    globalThis.api.writing.get.mockImplementation(async (id) => ({ id, novel_id: "p1", title: "第一章", content: id === "d2" ? "新稿" : "旧稿", version_number: id === "d2" ? 2 : 1, updated_at: id === "d2" ? "u2" : "u1", status: id === "d2" ? "draft" : "published" }))
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", items: [] }] })
    globalThis.api.writing.publish.mockResolvedValue({ new_version: true })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    const wrapper = mount(WritingView, { props: props({ requestedLocation: { chapter: 1, draftId: "d2" } }), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "历史").trigger("click")
    const oldVersion = wrapper.findAll(".writing-version-history-item").find((item) => item.text().includes("v1"))
    await oldVersion.findAll("button").find((button) => button.text() === "基于此版本创建").trigger("click")
    await flushPromises()
    expect(wrapper.get("#btn-autosave").text()).toBe("发布为新版本")
    await wrapper.get("#btn-autosave").trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.autosave).not.toHaveBeenCalled()
    expect(globalThis.api.writing.publish).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      restore_source_version: 1,
      expected_version: 2,
      expected_updated_at: "u2",
    }))
    wrapper.unmount()
  })

  it("从 Vue 警报页打开由 Vue 托管的完整冲突详情", async () => {
    const check = { id: "check-1", chapter_index: 1, items: [{ id: "i1", severity: "high", status: "open", evidence_summary: "证据" }] }
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [check] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "警报").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看最近校验").trigger("click")
    const dialog = wrapper.get('[aria-label="剧情设定冲突检查"]')
    expect(dialog.text()).toContain("证据")
    expect(globalThis.showModalHtml).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("从 Vue 选项对话框提交带当前版本与待处理范围的冲突检查", async () => {
    globalThis.api.writing.createConflictCheck.mockResolvedValue({ id: "check-new", chapter_index: 1, items: [] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#btn-conflict-check").trigger("click")
    await wrapper.get('[aria-label="剧情设定冲突检查选项"] input[type="checkbox"]').setValue(true)
    await wrapper.findAll("button").find((button) => button.text() === "开始检查").trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.createConflictCheck).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      draft_id: "d1",
      version_number: 1,
      content: "正文",
      include_candidates: true,
    }))
    expect(wrapper.find('[aria-label="剧情设定冲突检查"]').exists()).toBe(true)
    expect(globalThis.showModalHtml).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("冲突详情的状态、来源和采用建议均端到端经过 Vue", async () => {
    const check = {
      id: "check-1",
      chapter_index: 1,
      items: [{
        id: "item-1",
        severity: "medium",
        kind: "continuity_soft_risk",
        status: "open",
        source_module: "memory",
        evidence_summary: "记忆与正文不一致",
        location_json: { open_target: { kind: "memory_chapter", chapter_index: 4, character_id: "char-1" } },
        ai_suggestion: { suggested_text: "建议改写" },
      }],
    }
    globalThis.api.writing.updateConflictItem.mockResolvedValue({ id: "item-1", status: "resolved" })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.vm.$.setupState.vm.openConflictDialog(check)
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-action="open-conflict-source"]').trigger("click")
    expect(wrapper.get('[aria-label="冲突来源详情"]').text()).toContain("第 4 章")
    expect(wrapper.get('[aria-label="冲突来源详情"]').text()).toContain("char-1")

    await wrapper.get('[data-action="resolve-conflict"]').trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.updateConflictItem).toHaveBeenCalledWith("item-1", "p1", { status: "resolved" })
    expect(wrapper.get('[data-conflict-item-id="item-1"]').text()).toContain("已处理")

    await wrapper.get('[data-action="apply-conflict-suggestion"]').trigger("click")
    expect(wrapper.get("#writing-editor").element.value).toContain("建议改写")
    expect(globalThis.showModalHtml).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("自动提取从 Vue 授权表单提交并进入受管 workflow", async () => {
    globalThis.api.imports.startStage.mockResolvedValue({ task_id: "extract-1" })
    globalThis.api.tasks.get.mockResolvedValue({ status: "done", progress: 1, task_type: "scene_auto_extraction", result: {} })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "从正文提取 Scene").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()
    expect(globalThis.api.imports.startStage).toHaveBeenCalledWith("scenes", "p1", 1, 1, false, false, expect.objectContaining({
      authorization_confirmed: true,
      adoption_policy: "user_authorized_pipeline",
    }))
    expect(wrapper.text()).toContain("从正文提取 Scene")
    wrapper.unmount()
  })

  it("完整深度导入从写作台授权入口提交并进入受管 workflow", async () => {
    globalThis.api.imports.deepImport.mockResolvedValue({ task_id: "deep-1" })
    globalThis.api.tasks.get.mockResolvedValue({ status: "running", progress: 0.1, task_type: "deep_import", result: {} })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "启动深度导入").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(globalThis.api.imports.deepImport).toHaveBeenCalledWith("p1", 1, 1, false, false, expect.objectContaining({
      authorization_confirmed: true,
      adoption_policy: "user_authorized_pipeline",
    }))
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "deep-1", workflowType: "deep_import", projectId: "p1" }),
    ])
    expect(wrapper.text()).toContain("深度导入")
    wrapper.unmount()
  })

  it("已有运行中任务时不会再次提交完整深度导入", async () => {
    globalThis.api.tasks.get.mockImplementation(() => new Promise(() => {}))
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    wrapper.vm.$.setupState.vm.deepImportState.taskId = "running-deep-import"
    wrapper.vm.$.setupState.vm.deepImportState.progress = {
      status: "running",
      workflowType: "deep_import",
    }
    await wrapper.findAll("button").find((button) => button.text() === "启动深度导入").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(globalThis.api.imports.deepImport).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith(
      "已有自动提取任务正在运行，请等待完成或先取消当前任务",
      "warning",
    )
    wrapper.unmount()
  })

  it("服务端复用其他自动提取任务时连接原 task 与原 workflow 类型", async () => {
    globalThis.api.imports.deepImport.mockResolvedValue({
      task_id: "existing-stage-1",
      workflow_type: "scene_auto_extraction",
      stage: "scenes",
      reused_task: true,
    })
    globalThis.api.tasks.get.mockImplementation(() => new Promise(() => {}))
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "启动深度导入").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(wrapper.vm.$.setupState.vm.deepImportState).toEqual(expect.objectContaining({
      taskId: "existing-stage-1",
      progress: expect.objectContaining({
        workflowType: "scene_auto_extraction",
        label: "从正文提取 Scene",
      }),
    }))
    expect(toastMock).toHaveBeenCalledWith("已连接到现有“从正文提取 Scene”任务", "success")
    wrapper.unmount()
  })

  it("深导地图下一步从 Vue 入口调用快速创建窄 seam", async () => {
    const quickCreate = vi.spyOn(mapQuickCreateView, "open").mockResolvedValue(true)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    wrapper.vm.$.setupState.vm.deepImportState.progress = {
      status: "done",
      message: "完成",
      mapNextStep: { action: "quick-create", count: 2 },
    }
    await wrapper.vm.$nextTick()
    await wrapper.findAll("button").find((button) => button.text().includes("一键创建地图")).trigger("click")
    expect(quickCreate).toHaveBeenCalledWith(expect.objectContaining({ projectId: "p1", onCreated: expect.any(Function) }))
    wrapper.unmount()
  })

  it("取消深导任务继续使用应用内二次确认", async () => {
    let confirmHandler
    confirmActionMock.mockImplementation((_message, handler) => { confirmHandler = handler })
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:scene_auto_extraction:deep-cancel-1",
      taskId: "deep-cancel-1",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "writing",
    }]))
    globalThis.api.tasks.get.mockResolvedValue({
      task_id: "deep-cancel-1",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0.2,
      available_actions: ["cancel"],
      result: { message: "正在提取" },
    })
    globalThis.api.tasks.cancel.mockResolvedValue({ status: "cancelled" })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.vm.$.setupState.vm.deepImportState.taskId).toBe("deep-cancel-1"))

    await wrapper.findAll("button").find((button) => button.text() === "取消任务").trigger("click")
    expect(confirmActionMock).toHaveBeenCalledWith(
      expect.stringContaining("确认取消当前任务"),
      expect.any(Function),
      "确认取消",
    )
    expect(globalThis.api.tasks.cancel).not.toHaveBeenCalled()

    await confirmHandler()
    expect(globalThis.api.tasks.cancel).toHaveBeenCalledWith("deep-cancel-1", "p1")
    wrapper.unmount()
  })

  it("通过 CustomEvent 同步 topbar 字数、保存状态和卸载清理", async () => {
    const events = []
    const listener = (event) => events.push(event.detail)
    const today = new Date().toISOString().slice(0, 10)
    localStorage.setItem(`novel_daily_wc_${today}_p1`, "10")
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("作者输入")
    expect(events.at(-1)).toEqual({ chapterIndex: 1, chapterWords: 4, todayWords: 14, saveState: "unsaved" })
    expect(wrapper.find('[data-action="toggle-outline-float"]').exists()).toBe(true)
    wrapper.unmount()
    expect(events.at(-1)).toEqual({ chapterIndex: null, chapterWords: 0, todayWords: 0, saveState: "saved" })
    window.removeEventListener("writing:dashboard-update", listener)
  })
})
