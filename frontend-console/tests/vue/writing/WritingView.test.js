import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WritingView from "../../../vue/views/writing/WritingView.vue"
import { getAppState, resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"
import {
  clearWritingSession,
  getWritingSession,
  rememberWritingLocation,
} from "../../../vue/views/writing/writingSession.js"
import { projectSettingsSession } from "../../../vue/views/settings/projectSettingsSession.js"

function deferred() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

function props(overrides = {}) {
  return {
    projectId: "p1",
    chapterList: [1],
    chapters: { 1: { chapter_index: 1, title: "<img src=x>", word_count: 2, status: "draft" } },
    scenes: [{ id: "s1", title: "Scene <script>", status: "draft", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 20 }] }],
    chapterLoadError: null,
    authorPreferences: { dailyGoal: 1000, editorFont: "serif", defaultFocusMode: false },
    requestedLocation: { chapter: 1, draftId: "d1" },
    ...overrides,
  }
}

async function expandWritingCopilot(wrapper) {
  const toggle = wrapper.find('[aria-label="展开写作副驾驶"]')
  if (toggle.exists()) {
    await toggle.trigger("click")
    await flushPromises()
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
    await expandWritingCopilot(wrapper)
    expect(wrapper.find("#writing-editor").exists()).toBe(true)
    expect(wrapper.find("#writing-tree-container img").exists()).toBe(false)
    expect(wrapper.find("#writing-tree-container").text()).toContain("<img src=x>")
    expect(wrapper.find("#writing-tree-container").text()).not.toContain("Scene <script>")
    expect(wrapper.find("#writing-panel-container").text()).toContain("Scene <script>")
    expect(wrapper.find("script").exists()).toBe(false)
    wrapper.unmount()
  })

  it("可从当前章节就地建立作者任务", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    const button = wrapper.findAll(".writing-toolbar button").find((item) => item.text() === "添加到计划中的任务")

    await button.trigger("click")

    const call = globalThis.router.navigate.mock.calls.at(-1)
    expect(call.slice(0, 3)).toEqual(["writing", null, true])
    expect(call[3].get("panel")).toBe("tasks")
    expect(call[3].get("task_source_kind")).toBe("writing_chapter")
    expect(call[3].get("task_source_id")).toBe("1")
    expect(call[3].get("task_title")).toBe("<img src=x>")
    wrapper.unmount()
  })

  it("可从写作台返回写作首页", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    await wrapper.get('[data-action="open-writing-home"]').trigger("click")

    const call = globalThis.router.navigate.mock.calls.at(-1)
    expect(call.slice(0, 3)).toEqual(["writing", null, true])
    expect(call[3].get("home")).toBe("1")
    wrapper.unmount()
  })

  it("页头写作视图菜单同步状态，并可由动作、Escape 和外部点击收起", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    const menu = wrapper.get("details.writing-page-menu")
    const summary = menu.get("summary")

    expect(summary.attributes("aria-controls")).toBe("writing-page-menu-body")
    expect(summary.attributes("aria-expanded")).toBe("false")
    await summary.trigger("click")
    expect(menu.attributes("open")).toBeDefined()
    expect(summary.attributes("aria-expanded")).toBe("true")

    await wrapper.get("[data-action='toggle-outline-float']").trigger("keydown", { key: "Escape" })
    expect(menu.attributes("open")).toBeUndefined()
    expect(summary.attributes("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(summary.element)

    await summary.trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "打开故事结构").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("outline", null)
    expect(menu.attributes("open")).toBeUndefined()
    expect(document.activeElement).toBe(summary.element)

    await summary.trigger("click")
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(menu.attributes("open")).toBeUndefined()
    expect(wrapper.findAll("button").some((button) => button.text() === "进入专注")).toBe(false)
    expect(wrapper.findAll('[data-action="open-owner-ai-drawer"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-action="writing-ai-menu"]')).toHaveLength(1)
    expect(wrapper.findAll(".btn-primary")).toHaveLength(1)
    wrapper.unmount()
  })

  it("专注状态按项目恢复，进入后聚焦正文并可用 Escape 退出", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    const entry = wrapper.get(".writing-statusbar__focus")
    entry.element.focus()
    await entry.trigger("click")
    await flushPromises()

    expect(document.body.classList.contains("focus-mode-active")).toBe(true)
    expect(wrapper.get(".writing-focus-header").text()).toContain("退出专注 Esc")
    expect(document.activeElement).toBe(wrapper.get("#writing-editor").element)
    expect(getWritingSession("p1").focusMode).toBe(true)
    wrapper.unmount()

    const reloaded = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    expect(reloaded.find(".writing-focus-header").exists()).toBe(true)
    expect(document.activeElement).toBe(reloaded.get("#writing-editor").element)

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    await flushPromises()
    expect(reloaded.find(".writing-focus-header").exists()).toBe(false)
    expect(document.body.classList.contains("focus-mode-active")).toBe(false)
    expect(document.activeElement).toBe(reloaded.get(".writing-statusbar__focus").element)
    expect(getWritingSession("p1").focusMode).toBe(false)
    reloaded.unmount()
  })

  it("默认专注等待章节成功打开，不会先隐藏章节入口", async () => {
    const wrapper = mount(WritingView, {
      props: props({
        requestedLocation: null,
        authorPreferences: { dailyGoal: null, editorFont: "system", defaultFocusMode: true },
      }),
      attachTo: document.body,
    })
    await flushPromises()
    expect(wrapper.find(".writing-focus-header").exists()).toBe(false)
    expect(wrapper.find(".writing-tree-rail").isVisible()).toBe(true)

    await wrapper.get('[aria-label^="打开第 1 章"]').trigger("click")
    await flushPromises()
    expect(wrapper.find(".writing-focus-header").exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.get("#writing-editor").element)
    wrapper.unmount()
  })

  it("同章点击第二个 Scene 后保留显式写作位置", async () => {
    const wrapper = mount(WritingView, {
      props: props({
        scenes: [
          { id: "s1", title: "入口", status: "draft", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 1 }] },
          { id: "s2", title: "密道", status: "draft", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 1, end_pos: 2 }] },
        ],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await expandWritingCopilot(wrapper)

    const secondScene = wrapper.findAll(".scene-cockpit-switcher__item").find((button) => button.text().includes("密道"))
    await secondScene.trigger("click")
    await flushPromises()

    expect(wrapper.find(".scene-cockpit-switcher__item.active").text()).toContain("密道")
    expect(getAppState().viewStates.writing).toMatchObject({
      projectId: "p1",
      currentChapter: 1,
      currentSceneId: "s2",
    })
    const editor = wrapper.get("#writing-editor")
    editor.element.focus()
    editor.element.setSelectionRange(0, 0)
    await editor.trigger("click")
    expect(wrapper.find(".scene-cockpit-switcher__item.active").text()).toContain("密道")
    wrapper.unmount()
  })

  it("本章 Scene 兼容章节关联与 chunk，只显示有效态并稳定排序", async () => {
    const wrapper = mount(WritingView, {
      props: props({
        scenes: [
          { id: "z", title: "第二场", scene_index: 2, status: "draft", chapter_ids: ["1"] },
          { id: "b", title: "同序 B", scene_index: 1, status: "canonical", scene_chunks: [{ chapter_index: 1 }] },
          { id: "a", title: "同序 A", scene_index: 1, status: "draft", chapter_ids: ["1"] },
          { id: "candidate", title: "待处理", scene_index: 0, status: "candidate", chapter_ids: ["1"] },
          { id: "history", title: "历史", scene_index: 0, status: "deprecated", chapter_ids: ["1"] },
        ],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await expandWritingCopilot(wrapper)

    expect(wrapper.findAll(".scene-cockpit-switcher__item").map((item) => item.text())).toEqual([
      "同序 A", "同序 B", "第二场",
    ])
    expect(wrapper.get(".scene-cockpit-switcher").text()).not.toContain("待处理")
    expect(wrapper.get(".scene-cockpit-switcher").text()).not.toContain("历史")
    wrapper.unmount()
  })

  it("关联弹窗连续调用原子接口，并保留已手选 Scene", async () => {
    const linked = { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] }
    const unlinked = { id: "s2", title: "旅店暗号", scene_index: 2, status: "draft", chapter_ids: [] }
    globalThis.api.outline.associateSceneWithChapter.mockResolvedValue({ ...unlinked, chapter_ids: ["1"] })
    globalThis.api.outline.createSceneForChapter.mockResolvedValue({ id: "s3", title: "钟楼会面", scene_index: 3, status: "draft", chapter_ids: ["1"] })
    const wrapper = mount(WritingView, {
      props: props({ scenes: [linked, unlinked] }),
      attachTo: document.body,
    })
    await flushPromises()
    await expandWritingCopilot(wrapper)

    await wrapper.findAll("button").find((button) => button.text().includes("关联 Scene")).trigger("click")
    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    await flushPromises()
    expect(globalThis.api.outline.associateSceneWithChapter).toHaveBeenCalledWith("p1", 1, "s2")
    expect(wrapper.get('[aria-label="旅店暗号已关联"]').exists()).toBe(true)
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)

    await wrapper.findAll("button").find((button) => button.text().includes("新建 Scene")).trigger("click")
    await wrapper.get("#scene-associate-title-input").setValue("  钟楼会面  ")
    await wrapper.get(".scene-associate-create").trigger("submit")
    await flushPromises()
    expect(globalThis.api.outline.createSceneForChapter).toHaveBeenCalledWith("p1", 1, "钟楼会面")
    expect(wrapper.findAll(".scene-cockpit-switcher__item").map((item) => item.text())).toEqual([
      "入口", "旅店暗号", "钟楼会面",
    ])
    expect(wrapper.get(".scene-cockpit-switcher__item.active").text()).toContain("入口")
    wrapper.unmount()
  })

  it("从关联弹窗打开 Scene 工作台时携带当前手选 Scene", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await expandWritingCopilot(wrapper)
    await wrapper.findAll("button").find((button) => button.text().includes("关联 Scene")).trigger("click")
    await wrapper.findAll("button").find((button) => button.text().includes("打开 Scene 工作台")).trigger("click")

    const call = globalThis.router.navigate.mock.calls.at(-1)
    expect(call.slice(0, 3)).toEqual(["outline", "scenes", true])
    expect(call[3]).toBeInstanceOf(URLSearchParams)
    expect(call[3].get("scene_id")).toBe("s1")
    wrapper.unmount()
  })

  it("内层标题直接控制 rail，并按项目记住用户选择", async () => {
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: null }),
      attachTo: document.body,
    })
    await flushPromises()

    const rail = wrapper.get(".writing-tree-rail")
    const key = "workspace-rail:p1:writing:chapters"
    expect(sessionStorage.getItem(key)).toBeNull()
    expect(rail.element.tagName).toBe("ASIDE")
    expect(wrapper.findAll(".workspace-rail__summary")).toHaveLength(0)
    expect(wrapper.get(".chapter-tree-title").text()).toBe("共 1 章")
    expect(wrapper.get(".writing-rail-heading-label--copilot").text()).toBe("写作副驾驶")
    expect(wrapper.text()).not.toContain("写作参考")

    await wrapper.get('[aria-label="收起章节目录"]').trigger("click")
    expect(rail.classes()).toContain("is-collapsed")
    expect(sessionStorage.getItem(key)).toBe("closed")

    await wrapper.get('[aria-label="展开章节目录"]').trigger("click")
    expect(rail.classes()).not.toContain("is-collapsed")
    expect(sessionStorage.getItem(key)).toBe("open")
    wrapper.unmount()
  })

  it("移动速记通过工作区保存为工作稿", async () => {
    const originalWidth = window.innerWidth
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 320 })
    try {
      const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
      await flushPromises()
      expect(wrapper.get("#mobile-note-today-wc").text()).toBe("今日累计 0 字")
      const editor = wrapper.get('#mobile-note-editor')
      await editor.setValue("正文新")
      await vi.waitFor(() => expect(wrapper.get("#mobile-note-today-wc").text()).toBe("今日累计 1 字"))
      await wrapper.findAll("button").find((button) => button.text() === "保存工作稿").trigger("click")
      await flushPromises()

      expect(globalThis.api.writing.autosave).toHaveBeenCalledWith(
        "d1",
        expect.objectContaining({ content: "正文新" }),
        "p1",
      )
      expect(toastMock).toHaveBeenCalledWith("已保存到工作稿", "success")
      wrapper.unmount()
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth })
    }
  })

  it("移动速记只提供本章 Scene 切换，不暴露管理入口", async () => {
    const originalWidth = window.innerWidth
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    try {
      const wrapper = mount(WritingView, {
        props: props({ scenes: [
          { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] },
          { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"] },
        ] }),
        attachTo: document.body,
      })
      await flushPromises()

      const selector = wrapper.get("#mobile-note-scene-selector")
      expect(selector.findAll("option").map((option) => option.text())).toEqual(["入口", "密道"])
      expect(wrapper.get("details.scene-lens--mobile").attributes("open")).toBeUndefined()
      expect(wrapper.text()).not.toContain("关联 Scene")
      await selector.setValue("s2")
      expect(getAppState().viewStates.writing.currentSceneId).toBe("s2")
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
    expect(wrapper.find("#writing-save-status").text()).toBe("尚未保存")
    window.dispatchEvent(new Event("pagehide"))
    expect(localStorage.getItem("draft_backup_p1_1_d1")).toContain("作者新输入")
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

  it("保存失败时留在原章并提供就地重试", async () => {
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
    globalThis.api.writing.autosave.mockRejectedValueOnce(new Error("网络暂时不可用"))
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("第一章未保存正文")
    const vm = wrapper.vm.$.setupState.vm

    expect(await vm.selectChapter(2)).toBe(false)
    await flushPromises()
    expect(vm.selectedChapter.value).toBe(1)
    expect(vm.editorState.chapter).toBe(1)
    expect(globalThis.api.writing.get).not.toHaveBeenCalledWith("d2", "p1")
    expect(wrapper.get('[role="alert"]').text()).toContain("工作稿还没有保存")
    expect(wrapper.get('[role="alert"]').text()).toContain("本地备份仍保留在这台设备上")
    expect(wrapper.get("#writing-save-status").classes()).toContain("writing-save-badge--error")
    expect(wrapper.get("#writing-save-status").text()).toBe("保存失败，本地备份已保留")
    expect(localStorage.getItem("draft_backup_p1_1_d1")).toContain("第一章未保存正文")

    await wrapper.get("#writing-retry-save").trigger("click")
    await flushPromises()
    expect(wrapper.find("#writing-retry-save").exists()).toBe(false)
    expect(wrapper.get("#writing-save-status").text()).toBe("已保存到工作稿")

    expect(await vm.selectChapter(2)).toBe(true)
    await flushPromises()
    expect(vm.selectedChapter.value).toBe(2)
    expect(wrapper.get("#writing-editor").element.value).toBe("正文 2")
    wrapper.unmount()
  })

  it("移动速记本地备份失败时显示丢失风险并由离开守卫二次确认", async () => {
    const previousWidth = window.innerWidth
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    let guard = null
    const originalSetItem = localStorage.setItem.bind(localStorage)
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (String(key).startsWith("draft_backup_")) {
        throw new DOMException("quota", "QuotaExceededError")
      }
      return originalSetItem(key, value)
    })
    globalThis.api.writing.autosave.mockRejectedValueOnce(new Error("网络暂时不可用"))
    confirmMock.mockReturnValueOnce(false).mockReturnValueOnce(true)
    const wrapper = mount(WritingView, {
      props: props(),
      attachTo: document.body,
      global: {
        provide: {
          [ISLAND_LEAVE_GUARD]: (fn) => { guard = fn },
        },
      },
    })
    await flushPromises()
    await wrapper.get(".mobile-note-editor").setValue("只留在当前页面的移动正文")

    await wrapper.vm.$.setupState.vm.autosave()
    await flushPromises()

    expect(wrapper.text()).toContain("保存失败，本地备份不可用")
    expect(wrapper.text()).toContain("离开或刷新会丢失未保存修改")
    expect(wrapper.get(".mobile-note-editor").element.value).toBe("只留在当前页面的移动正文")
    expect(guard()).toBe(false)
    expect(confirmMock).toHaveBeenLastCalledWith(
      "当前修改尚未保存，浏览器也无法写入本地备份。离开后这些修改会丢失，仍要离开吗？",
    )
    expect(guard()).toBe(true)

    storage.mockRestore()
    wrapper.unmount()
    Object.defineProperty(window, "innerWidth", { configurable: true, value: previousWidth })
  })

  it("远端保存期间的新输入无法本地备份时立即显示丢失风险", async () => {
    const late = deferred()
    const originalSetItem = localStorage.setItem.bind(localStorage)
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (String(key).startsWith("draft_backup_")) {
        throw new DOMException("quota", "QuotaExceededError")
      }
      return originalSetItem(key, value)
    })
    globalThis.api.writing.autosave.mockReturnValueOnce(late.promise)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("先提交的正文")

    const saving = wrapper.vm.$.setupState.vm.autosave()
    await wrapper.get("#writing-editor").setValue("请求期间继续输入的正文")
    late.resolve({
      id: "d1",
      novel_id: "p1",
      title: "<img src=x>",
      content: "先提交的正文",
      version_number: 2,
      status: "draft",
    })
    await saving
    await flushPromises()

    expect(wrapper.get("#writing-save-status").text()).toBe("本地备份不可用")
    expect(wrapper.get("#writing-save-status").classes()).toContain("writing-save-badge--error")
    expect(wrapper.get('[role="alert"]').text()).toContain("当前修改只保留在这个页面")
    expect(wrapper.get("#writing-editor").element.value).toBe("请求期间继续输入的正文")

    storage.mockRestore()
    wrapper.unmount()
  })

  it("切章加载时隐藏旧正文，失败后可重试同一章", async () => {
    globalThis.api.writing.getVersionHistory.mockImplementation(async (chapter) => ({
      versions: [{ id: `d${chapter}`, version_number: 1, status: "draft" }],
    }))
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      title: `第 ${String(id).slice(1)} 章`,
      content: `正文 ${String(id).slice(1)}`,
      version_number: 1,
      status: "draft",
    }))
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    expect(wrapper.get("#writing-editor").element.value).toBe("正文 1")

    let rejectDraft
    globalThis.api.writing.get.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectDraft = reject }))
    const vm = wrapper.vm.$.setupState.vm
    const switching = vm.selectChapter(2)
    await vi.waitFor(() => expect(globalThis.api.writing.get).toHaveBeenLastCalledWith("d2", "p1"))
    await flushPromises()
    expect(wrapper.get('[role="status"][aria-busy="true"]').text()).toContain("正在打开第 2 章")
    expect(wrapper.find("#writing-editor").exists()).toBe(false)

    rejectDraft(new Error("连接超时"))
    expect(await switching).toBe(false)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain("第 2 章暂时无法打开")
    expect(wrapper.get('[role="alert"]').text()).toContain("上一章的内容仍安全保留")
    expect(vm.editorState.chapter).toBe(1)
    expect(getAppState().viewStates.writing.currentChapter).toBe(1)

    await wrapper.get("#writing-retry-load").trigger("click")
    await flushPromises()
    expect(vm.selectedChapter.value).toBe(2)
    expect(vm.editorState.chapter).toBe(2)
    expect(wrapper.get("#writing-editor").element.value).toBe("正文 2")
    wrapper.unmount()
  })

  it("切章后按章恢复上次手选 Scene", async () => {
    globalThis.api.writing.getVersionHistory.mockImplementation(async (chapter) => ({
      versions: [{ id: `d${chapter}`, version_number: 1, status: "draft" }],
    }))
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      title: `章节 ${id}`,
      content: "正文",
      version_number: 1,
      status: "draft",
    }))
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: { 1: { title: "一" }, 2: { title: "二" } },
        scenes: [
          { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] },
          { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"] },
          { id: "s3", title: "钟楼", scene_index: 3, status: "draft", chapter_ids: ["2"] },
        ],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    const vm = wrapper.vm.$.setupState.vm
    await vm.selectScene("s2")
    await vm.selectChapter(2)
    expect(vm.currentScene.value.id).toBe("s3")
    await vm.selectChapter(1)
    expect(vm.currentScene.value.id).toBe("s2")
    wrapper.unmount()
  })

  it("路由 Scene 已失效时恢复该章上次手选 Scene", async () => {
    const wrapper = mount(WritingView, {
      props: props({
        requestedLocation: null,
        scenes: [
          { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] },
          { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"] },
        ],
      }),
      attachTo: document.body,
    })
    rememberWritingLocation("p1", { currentChapter: 1, currentSceneId: "s2" })
    await wrapper.vm.$.setupState.vm.selectChapter(1, { draftId: "d1", sceneId: "missing" })

    expect(wrapper.vm.$.setupState.vm.selectedSceneId.value).toBe("s2")
    wrapper.unmount()
  })

  it("同章切换 Scene 后丢弃旧上下文的晚到响应", async () => {
    const oldCheck = deferred()
    globalThis.api.writing.listConflictChecks.mockImplementation(({ scene_id: sceneId }) => (
      sceneId === "s1" ? oldCheck.promise : Promise.resolve({ items: [{ id: "check-s2", scene_id: "s2", chapter_index: 1 }] })
    ))
    globalThis.api.world.listEntities.mockImplementation(async ({ scene_id: sceneId, entity_type: type }) => (
      type === "character" ? [{ id: `${sceneId}-person`, name: `${sceneId} 人物` }] : []
    ))
    const wrapper = mount(WritingView, {
      props: props({ scenes: [
        { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] },
        { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"] },
      ] }),
      attachTo: document.body,
    })
    const vm = wrapper.vm.$.setupState.vm
    await vi.waitFor(() => expect(vm.selectedSceneId.value).toBe("s1"))
    vm.conflictDialog.open = true
    vm.conflictDialog.check = { id: "dialog-s1", scene_id: "s1" }
    Object.assign(vm.conflictTask, { taskId: "task-s1", progress: { status: "running" } })
    await vm.selectScene("s2")
    expect(vm.sceneState.people.map((person) => person.name)).toEqual(["s2 人物"])
    expect(vm.conflictState.latest?.id).toBe("check-s2")
    expect(vm.conflictDialog).toMatchObject({ open: false, check: null })
    expect(vm.conflictTask).toMatchObject({ taskId: null, progress: null })

    oldCheck.resolve({ items: [{ id: "check-s1", scene_id: "s1", chapter_index: 1 }] })
    await flushPromises()
    expect(vm.sceneState.people.map((person) => person.name)).toEqual(["s2 人物"])
    expect(vm.conflictState.latest?.id).toBe("check-s2")
    wrapper.unmount()
  })

  it("Scene Lens 仅点击加载，且切场后丢弃旧场晚到响应", async () => {
    const oldLens = deferred()
    globalThis.api.context.sceneLens = vi.fn(({ scene_id: sceneId }) => (
      sceneId === "s1"
        ? oldLens.promise
        : Promise.resolve({ role_visible_knowledge: [], scene_world_state: [], warnings: [] })
    ))
    const wrapper = mount(WritingView, {
      props: props({ scenes: [
        { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"], goal: "进门" },
        { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"], goal: "离开" },
      ] }),
      attachTo: document.body,
    })
    const vm = wrapper.vm.$.setupState.vm
    await vi.waitFor(() => expect(vm.selectedSceneId.value).toBe("s1"))
    expect(globalThis.api.context.sceneLens).not.toHaveBeenCalled()
    const loading = vm.loadSceneLens()
    await vi.waitFor(() => expect(globalThis.api.context.sceneLens).toHaveBeenCalledWith({
      novel_id: "p1",
      scene_id: "s1",
      chapter_index: 1,
    }))
    await vm.selectScene("s2")
    await vm.loadSceneLens()
    oldLens.resolve({ role_visible_knowledge: [{ label: "旧场人物", summary: "晚到", availability: true }], scene_world_state: [], warnings: [] })
    await loading
    expect(vm.sceneLens.sceneId).toBe("s2")
    expect(vm.sceneLens.data?.role_visible_knowledge || []).toEqual([])
    wrapper.unmount()
  })

  it("同章切换版本时保留选择控件和焦点", async () => {
    const history = {
      versions: [
        { id: "d2", version_number: 2, status: "draft" },
        { id: "d1", version_number: 1, status: "draft" },
      ],
    }
    globalThis.api.writing.getVersionHistory.mockResolvedValue(history)
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      content: id === "d2" ? "新正文" : "旧正文",
      version_number: id === "d2" ? 2 : 1,
      status: "draft",
    }))
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: { chapter: 1, draftId: "d2" } }),
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(wrapper.findAll("#version-selector option")).toHaveLength(2))

    let resolveDraft
    let resolveHistory
    globalThis.api.writing.get.mockImplementationOnce(() => new Promise((resolve) => { resolveDraft = resolve }))
    globalThis.api.writing.getVersionHistory.mockImplementationOnce(() => new Promise((resolve) => { resolveHistory = resolve }))
    const selector = wrapper.get("#version-selector")
    selector.element.focus()
    await selector.setValue("d1")

    expect(globalThis.api.writing.get).toHaveBeenLastCalledWith("d1", "p1")
    expect(selector.element.isConnected).toBe(true)
    expect(document.activeElement).toBe(selector.element)
    expect(selector.element.value).toBe("d1")

    resolveDraft({ id: "d1", novel_id: "p1", chapter_index: 1, title: "第一章", content: "旧正文", version_number: 1, status: "draft" })
    resolveHistory(history)
    await flushPromises()
    expect(wrapper.get("#version-selector").element).toBe(selector.element)
    expect(document.activeElement).toBe(selector.element)
    wrapper.unmount()
  })

  it("同章预览其他版本前先保存未落盘正文", async () => {
    const history = { versions: [
      { id: "d2", version_number: 2, status: "draft" },
      { id: "d1", version_number: 1, status: "published" },
    ] }
    globalThis.api.writing.getVersionHistory.mockResolvedValue(history)
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      content: id === "d2" ? "新正文" : "旧正文",
      version_number: id === "d2" ? 2 : 1,
      status: id === "d2" ? "draft" : "published",
    }))
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: { chapter: 1, draftId: "d2" } }),
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("新正文"))
    await wrapper.get("#writing-editor").setValue("还没落盘的修改")
    await wrapper.get("#version-selector").setValue("d1")
    await flushPromises()

    expect(globalThis.api.writing.autosave).toHaveBeenCalledWith("d2", expect.objectContaining({ content: "还没落盘的修改" }), "p1")
    const previewCall = globalThis.api.writing.get.mock.calls.findIndex(([id]) => id === "d1")
    expect(previewCall).toBeGreaterThanOrEqual(0)
    expect(globalThis.api.writing.autosave.mock.invocationCallOrder.at(-1))
      .toBeLessThan(globalThis.api.writing.get.mock.invocationCallOrder[previewCall])
    expect(wrapper.get("#writing-editor").element.value).toBe("旧正文")
    wrapper.unmount()
  })

  it("候选可一步比较当前工作稿并聚焦差异结果", async () => {
    globalThis.api.writing.getVersionHistory.mockResolvedValue({ versions: [
      { id: "candidate", version_number: 2, status: "candidate", display_state: "candidate" },
      { id: "base", version_number: 1, status: "published", display_state: "active" },
    ] })
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      content: id === "candidate" ? "候选正文" : "当前工作稿",
      version_number: id === "candidate" ? 2 : 1,
      status: id === "candidate" ? "candidate" : "published",
      provenance_json: id === "candidate" ? { source: "writing_generate", review_required: false } : null,
    }))
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: { chapter: 1, draftId: "candidate" } }),
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(wrapper.find(".writing-candidate-comparison .btn").exists()).toBe(true))

    await wrapper.get(".writing-candidate-comparison .btn").trigger("click")
    await flushPromises()

    expect(globalThis.api.writing.get).toHaveBeenCalledWith("base", "p1")
    expect(globalThis.api.writing.get).toHaveBeenCalledWith("candidate", "p1")
    expect(wrapper.get('[aria-label="版本历史"]').text()).toContain("当前工作稿")
    expect(wrapper.get('[aria-label="版本历史"]').text()).toContain("候选正文")
    await vi.waitFor(() => expect(document.activeElement).toBe(wrapper.get(".writing-version-diff").element))
    wrapper.unmount()
  })

  it("未选章节时保留项目级提取入口，章节级操作保持禁用", async () => {
    const wrapper = mount(WritingView, { props: props({ requestedLocation: null }), attachTo: document.body })
    await flushPromises()

    expect(wrapper.find("#writing-editor").exists()).toBe(false)
    expect(wrapper.find("#btn-autosave").attributes("disabled")).toBeDefined()
    const extractionButton = wrapper.findAll("button").find((button) => button.text() === "先整理场景骨架（推荐）")
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
    expect(wrapper.findAll("button").some((button) => button.text() === "先整理场景骨架（推荐）")).toBe(false)
    wrapper.unmount()
  })

  it("空工作稿禁用续写建议入口", async () => {
    globalThis.api.writing.get.mockResolvedValue({
      id: "d1",
      novel_id: "p1",
      title: "第一章",
      content: "",
      version_number: 1,
      status: "draft",
    })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    const continuation = wrapper.findAll("button").find((button) => button.text() === "续写建议")
    expect(continuation.attributes("disabled")).toBeDefined()
    wrapper.unmount()
  })

  it("正文生成期间禁用所有生成入口", async () => {
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    wrapper.vm.$.setupState.vm.generationLoading.value = true
    await flushPromises()

    const buttons = wrapper.findAll("button")
    expect(buttons.find((button) => button.text() === "生成中…").attributes("disabled")).toBeDefined()
    expect(buttons.find((button) => button.text() === "AI 正文建议").attributes("disabled")).toBeDefined()
    expect(buttons.find((button) => button.text() === "AI 角色视角建议").attributes("disabled")).toBeDefined()
    wrapper.unmount()
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

    for (const label of ["续写建议", "AI 正文建议", "AI 角色视角建议", "先整理场景骨架（推荐）", "完整整理世界与结构", "整理人物、设定与关系", "整理剧情线", "导出本章"]) {
      expect(wrapper.findAll("button").some((button) => button.text() === label)).toBe(true)
    }

    await wrapper.findAll("button").find((button) => button.text() === "先整理场景骨架（推荐）").trigger("click")
    expect(wrapper.find('[aria-label="自动提取"]').exists()).toBe(true)
    wrapper.vm.$.setupState.vm.autoExtraction.open = false

    await wrapper.find("#btn-conflict-check").trigger("click")
    expect(wrapper.find('[aria-label="剧情设定冲突检查选项"]').exists()).toBe(true)
    wrapper.vm.$.setupState.vm.conflictOptions.open = false

    await wrapper.findAll("button").find((button) => button.text() === "故事结构浮窗").trigger("click")
    await flushPromises()
    expect(wrapper.find("#outline-float-panel").text()).toContain("剧情 <script>")
    expect(wrapper.find("#outline-float-panel script").exists()).toBe(false)

    await wrapper.findAll("button").find((button) => button.text() === "版本历史").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看差异").trigger("click")
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
      expect.stringContaining("还没有前后设定检查记录"),
      expect.any(Function),
      "继续设为正式正文",
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
      expect.stringContaining("2 个未处理的重要问题"),
      expect.any(Function),
      "继续设为正式正文",
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
      "无法读取正式正文前的设定检查：检查服务不可用。本次操作已停止，请稍后重试。",
      "error",
    )
    expect(globalThis.api.writing.publish).not.toHaveBeenCalled()
    expect(globalThis.api.writing.autosave).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("发布生命周期失败只由顶部浮层反馈", async () => {
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", items: [] }] })
    globalThis.api.writing.publish.mockRejectedValue(new Error("发布服务暂时不可用"))
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    await wrapper.get("#btn-publish").trigger("click")
    await flushPromises()

    expect(wrapper.get("#writing-publish-bar-container").text()).toContain("发布服务暂时不可用")
    expect(toastMock).not.toHaveBeenCalledWith("发布服务暂时不可用", "error")
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

  it("发布 payload 使用当前手选 Scene", async () => {
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", items: [], summary_json: { open_high_count: 0 } }] })
    globalThis.api.writing.publish.mockResolvedValue({ new_version: false })
    const wrapper = mount(WritingView, {
      props: props({ scenes: [
        { id: "s1", title: "入口", scene_index: 1, status: "draft", chapter_ids: ["1"] },
        { id: "s2", title: "密道", scene_index: 2, status: "draft", chapter_ids: ["1"] },
      ] }),
      attachTo: document.body,
    })
    const vm = wrapper.vm.$.setupState.vm
    await vi.waitFor(() => expect(vm.selectedSceneId.value).toBe("s1"))
    await vm.selectScene("s2")
    await vm.publish()

    expect(globalThis.api.writing.publish).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s2",
    }))
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
    await wrapper.findAll("button").find((button) => button.text() === "版本历史").trigger("click")
    const oldVersion = wrapper.findAll(".writing-version-history-item").find((item) => item.text().includes("v1"))
    await oldVersion.findAll("button").find((button) => button.text() === "从此版本继续写").trigger("click")
    await flushPromises()
    expect(wrapper.get("#btn-autosave").text()).toBe("保存为新工作稿")
    await wrapper.get("#writing-editor").setValue("基于旧稿修订")
    await wrapper.get("#btn-autosave").trigger("click")
    await flushPromises()
    expect(globalThis.api.writing.autosave).not.toHaveBeenCalled()
    expect(globalThis.api.writing.publish).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      restore_source_version: 1,
      expected_version: 2,
      expected_updated_at: "u2",
      content: "基于旧稿修订",
    }))
    wrapper.unmount()
  })

  it("从 Vue 警报页打开由 Vue 托管的完整冲突详情", async () => {
    const check = { id: "check-1", chapter_index: 1, items: [{ id: "i1", severity: "high", status: "open", evidence_summary: "证据" }] }
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [check] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await expandWritingCopilot(wrapper)
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

  it("冲突检查暂存期间切换章节后不再提交旧章节检查", async () => {
    const late = deferred()
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("等待检查的正文")
    globalThis.api.writing.autosave.mockReturnValueOnce(late.promise)
    const vm = wrapper.vm.$.setupState.vm
    const checking = vm.runConflictCheck()
    await vi.waitFor(() => expect(globalThis.api.writing.autosave).toHaveBeenCalled())
    const switching = vm.selectChapter(2)

    expect(globalThis.api.writing.createConflictCheck).not.toHaveBeenCalled()
    late.resolve({ id: "d1", novel_id: "p1", title: "第一章", content: "等待检查的正文", version_number: 2, status: "draft" })
    await Promise.all([checking, switching])
    await flushPromises()

    expect(vm.selectedChapter.value).toBe(2)
    expect(globalThis.api.writing.createConflictCheck).not.toHaveBeenCalled()
    expect(vm.conflictDialog.open).toBe(false)
    expect(toastMock).not.toHaveBeenCalledWith("冲突检查已完成", "success")
    wrapper.unmount()
  })

  it("今日字数只累计各章首次基线后的正增量，跨章与刷新不重计", async () => {
    const now = new Date()
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
    localStorage.setItem(`novel_daily_wc_${today}_p1`, "10")
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await vi.waitFor(() => expect(events.at(-1)?.todayWords).toBe(10))
    expect(wrapper.get(".wc-daily-goal").text()).toContain("日目标 10 / 1,000")
    await wrapper.get("#writing-editor").setValue("第一章四字")
    await vi.waitFor(() => expect(events.at(-1)).toMatchObject({
      chapterIndex: 1,
      chapterWords: 5,
      todayWords: 13,
    }))

    const vm = wrapper.vm.$.setupState.vm
    await vm.selectChapter(2)
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("二章三字")
    await vi.waitFor(() => expect(events.at(-1)).toMatchObject({
      chapterIndex: 2,
      chapterWords: 4,
    }))

    // 两章首次加载的 2 字都只是基线：今日 = 10 + (5 - 2) + (4 - 2)
    expect(events.at(-1).todayWords).toBe(15)
    expect(wrapper.get(".wc-daily-goal").text()).toContain("日目标 15 / 1,000")
    wrapper.unmount()
    window.removeEventListener("writing:dashboard-update", listener)

    // 刷新后重新进入同一章：不重复累计
    const events2 = []
    const listener2 = (event) => events2.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener2)
    const reloaded = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
        requestedLocation: { chapter: 2, draftId: "d1" },
      }),
      attachTo: document.body,
    })
    await flushPromises()
    await reloaded.get("#writing-editor").setValue("二章三字")
    await vi.waitFor(() => expect(events2.at(-1).todayWords).toBe(15))
    reloaded.unmount()
    window.removeEventListener("writing:dashboard-update", listener2)
  })

  it("切换到更长的其他版本只更新基线，不计为今日输入", async () => {
    const history = { versions: [
      { id: "d2", version_number: 2, status: "draft" },
      { id: "d1", version_number: 1, status: "published" },
    ] }
    globalThis.api.writing.getVersionHistory.mockResolvedValue(history)
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      content: id === "d2" ? "短稿" : "一篇更长的旧稿",
      version_number: id === "d2" ? 2 : 1,
      status: id === "d2" ? "draft" : "published",
    }))
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: { chapter: 1, draftId: "d2" } }),
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("短稿"))
    await wrapper.get("#version-selector").setValue("d1")
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("一篇更长的旧稿"))
    expect(events.at(-1).todayWords).toBe(0)
    await wrapper.vm.$.setupState.vm.switchVersion("d2")
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("短稿"))
    await wrapper.get("#writing-editor").setValue("短稿新")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(1))

    wrapper.unmount()
    window.removeEventListener("writing:dashboard-update", listener)
  })

  it("更长候选只建立独立基线，返回工作稿后继续正常计数", async () => {
    const history = { versions: [
      { id: "candidate", version_number: 2, status: "candidate", display_state: "candidate" },
      { id: "base", version_number: 1, status: "draft", display_state: "active" },
    ] }
    globalThis.api.writing.getVersionHistory.mockResolvedValue(history)
    globalThis.api.writing.get.mockImplementation(async (id) => ({
      id,
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      content: id === "candidate" ? "一篇更长的候选正文" : "短稿",
      version_number: id === "candidate" ? 2 : 1,
      status: id === "candidate" ? "candidate" : "draft",
    }))
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, {
      props: props({ requestedLocation: { chapter: 1, draftId: "base" } }),
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("短稿"))
    const vm = wrapper.vm.$.setupState.vm
    await vm.switchVersion("candidate")
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("一篇更长的候选正文"))
    expect(events.at(-1).todayWords).toBe(0)
    await vm.switchVersion("base")
    await vi.waitFor(() => expect(wrapper.get("#writing-editor").element.value).toBe("短稿"))
    await wrapper.get("#writing-editor").setValue("短稿新")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(1))

    wrapper.unmount()
    window.removeEventListener("writing:dashboard-update", listener)
  })

  it("跨本地午夜后的首次输入以输入前正文为新日基线", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date(2026, 8, 2, 23, 59, 59))
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    vi.setSystemTime(new Date(2026, 8, 3, 0, 0, 1))
    await wrapper.get("#writing-editor").setValue("正文新增")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(2))

    wrapper.unmount()
    window.removeEventListener("writing:dashboard-update", listener)
  })

  it("删字不会让今日字数倒退或在补回时重计", async () => {
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()

    await wrapper.get("#writing-editor").setValue("正文增加")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(2))
    await wrapper.get("#writing-editor").setValue("正")
    await vi.waitFor(() => expect(events.at(-1).chapterWords).toBe(1))
    expect(events.at(-1).todayWords).toBe(2)
    await wrapper.get("#writing-editor").setValue("正文增加一")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(3))

    wrapper.unmount()
    window.removeEventListener("writing:dashboard-update", listener)
  })

  it("损坏或不可用的字数缓存不会串项目或阻断输入", async () => {
    const now = new Date()
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
    localStorage.setItem(`novel_daily_wc_${today}_p1`, "-20")
    localStorage.setItem(`novel_daily_wc_open_${today}_p1`, JSON.stringify({ "1:d1": { highWater: -10 } }))
    localStorage.setItem(`novel_daily_wc_${today}_p2`, "999")
    const events = []
    const listener = (event) => events.push(event.detail)
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    expect(events.at(-1).todayWords).toBe(0)
    await wrapper.get("#writing-editor").setValue("正文增加")
    await vi.waitFor(() => expect(events.at(-1).todayWords).toBe(2))
    wrapper.unmount()
    clearWritingSession()
    localStorage.clear()

    const originalGetItem = localStorage.getItem.bind(localStorage)
    const originalSetItem = localStorage.setItem.bind(localStorage)
    const getSpy = vi.spyOn(localStorage, "getItem").mockImplementation((key) => {
      if (String(key).startsWith("novel_daily_wc_")) throw new Error("storage unavailable")
      return originalGetItem(key)
    })
    const setSpy = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (String(key).startsWith("novel_daily_wc_")) throw new Error("storage unavailable")
      return originalSetItem(key, value)
    })
    const unavailable = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await unavailable.get("#writing-editor").setValue("仍可输入")
    await vi.waitFor(() => expect(events.at(-1)).toMatchObject({ chapterWords: 4, todayWords: 0 }))
    unavailable.unmount()
    getSpy.mockRestore()
    setSpy.mockRestore()
    window.removeEventListener("writing:dashboard-update", listener)
  })

  it("组件卸载后忽略冲突检查的晚到结果", async () => {
    const late = deferred()
    globalThis.api.writing.createConflictCheck.mockReturnValue(late.promise)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    const vm = wrapper.vm.$.setupState.vm
    const checking = vm.runConflictCheck()
    await vi.waitFor(() => expect(globalThis.api.writing.createConflictCheck).toHaveBeenCalled())
    wrapper.unmount()
    late.resolve({ id: "late-check", chapter_index: 1, items: [] })
    await checking

    expect(vm.conflictState.latest).toBeNull()
    expect(vm.conflictDialog.open).toBe(false)
    expect(toastMock).not.toHaveBeenCalledWith("冲突检查已完成", "success")
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

  it("从待处理深链打开当前 Scene 的最新检查并定位事项", async () => {
    const check = {
      id: "check-linked",
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      items: [{
        id: "item-linked",
        severity: "low",
        kind: "required_missing",
        status: "open",
        author_action: "can_improve",
        source_module: "outline",
        evidence_summary: "当前场景未逐字出现必须发生项",
      }],
    }
    globalThis.api.writing.listConflictChecks.mockResolvedValue({ items: [check] })
    const wrapper = mount(WritingView, {
      props: props({
        requestedLocation: {
          chapter: 1,
          draftId: "d1",
          sceneId: "s1",
          openConflict: true,
          conflictItemId: "item-linked",
          source: "url",
        },
      }),
      attachTo: document.body,
    })
    await flushPromises()

    expect(wrapper.get('[aria-label="剧情设定冲突检查"]').exists()).toBe(true)
    expect(wrapper.get('[data-conflict-item-id="item-linked"]').classes()).toContain("is-focused")
    expect(wrapper.get('[data-conflict-item-id="item-linked"]').attributes("aria-current")).toBe("true")
    expect(wrapper.get('[data-conflict-item-id="item-linked"] [data-author-action]').text()).toBe("可以改进")
    wrapper.unmount()
  })

  it("场景提取完成后刷新 Scene，并提供进入场景骨架的下一步", async () => {
    globalThis.api.imports.startStage.mockResolvedValue({ task_id: "extract-1" })
    globalThis.api.tasks.get.mockResolvedValue({ status: "done", progress: 1, task_type: "scene_auto_extraction", result: {} })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    globalThis.api.outline.listScenesOrdered.mockResolvedValue([{ id: "scene-new", title: "新场景", status: "draft", chapter_ids: ["1"], scene_chunks: [] }])
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "先整理场景骨架（推荐）").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()
    expect(globalThis.api.imports.startStage).toHaveBeenCalledWith("scenes", "p1", 1, 1, false, false, expect.objectContaining({
      authorization_confirmed: true,
      adoption_policy: "user_authorized_pipeline",
    }))
    expect(globalThis.api.outline.listScenesOrdered).toHaveBeenCalledWith("p1")
    expect(wrapper.vm.$.setupState.vm.chapterScenes.value.map((scene) => scene.title)).toContain("新场景")
    const openScenes = wrapper.findAll("button").find((button) => button.text() === "查看场景骨架")
    expect(openScenes).toBeDefined()
    await openScenes.trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("outline", "scenes")
    expect(wrapper.text()).toContain("从正文整理场景")
    wrapper.unmount()
  })

  it("世界对象 stage 完成不刷新无关的 Scene", async () => {
    globalThis.api.imports.startStage.mockResolvedValue({ task_id: "world-1" })
    globalThis.api.tasks.get.mockResolvedValue({ status: "done", progress: 1, task_type: "world_object_auto_extraction", result: {} })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.vm.$.setupState.vm.openAutoExtraction("world_objects")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(globalThis.api.outline.listScenesOrdered).not.toHaveBeenCalled()
    expect(wrapper.findAll("button").some((button) => button.text() === "查看场景骨架")).toBe(false)
    wrapper.unmount()
  })

  it("完整深度导入从写作台授权入口提交并进入受管 workflow", async () => {
    globalThis.api.imports.deepImport.mockResolvedValue({ task_id: "deep-1" })
    globalThis.api.tasks.get.mockResolvedValue({ status: "done", progress: 1, task_type: "deep_import", result: {} })
    globalThis.api.writing.listChapters.mockResolvedValue({ chapter_indices: [1] })
    globalThis.api.outline.listScenesOrdered.mockResolvedValue([{ id: "scene-full", title: "完整导入场景", status: "draft", chapter_ids: ["1"], scene_chunks: [] }])
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "完整整理世界与结构").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(globalThis.api.imports.deepImport).toHaveBeenCalledWith("p1", 1, 1, false, false, expect.objectContaining({
      authorization_confirmed: true,
      adoption_policy: "user_authorized_pipeline",
    }))
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "deep-1", workflowType: "deep_import", projectId: "p1" }),
    ])
    expect(globalThis.api.outline.listScenesOrdered).toHaveBeenCalledWith("p1")
    expect(wrapper.vm.$.setupState.vm.chapterScenes.value.map((scene) => scene.title)).toContain("完整导入场景")
    wrapper.unmount()
  })

  it("调整深度导入设置会选择对应 Tab 并导航", async () => {
    projectSettingsSession.tab = "author"
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "调整深度导入设置").trigger("click")
    expect(projectSettingsSession.tab).toBe("deep")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("project-settings")
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
    await wrapper.findAll("button").find((button) => button.text() === "完整整理世界与结构").trigger("click")
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
    await wrapper.findAll("button").find((button) => button.text() === "完整整理世界与结构").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "确认并开始提取").trigger("click")
    await flushPromises()

    expect(wrapper.vm.$.setupState.vm.deepImportState).toEqual(expect.objectContaining({
      taskId: "existing-stage-1",
      progress: expect.objectContaining({
        workflowType: "scene_auto_extraction",
        label: "从正文整理场景",
      }),
    }))
    expect(toastMock).toHaveBeenCalledWith("已连接到现有“从正文整理场景”任务", "success")
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
    const now = new Date()
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
    localStorage.setItem(`novel_daily_wc_${today}_p1`, "10")
    window.addEventListener("writing:dashboard-update", listener)
    const wrapper = mount(WritingView, { props: props(), attachTo: document.body })
    await flushPromises()
    await wrapper.get("#writing-editor").setValue("作者输入")
    await vi.waitFor(() => expect(events.at(-1)).toEqual({
      chapterIndex: 1,
      chapterWords: 4,
      todayWords: 12,
      saveState: "unsaved",
    }))
    expect(wrapper.find('[data-action="toggle-outline-float"]').exists()).toBe(true)
    wrapper.unmount()
    expect(events.at(-1)).toEqual({ chapterIndex: null, chapterWords: 0, todayWords: 0, saveState: "saved" })
    window.removeEventListener("writing:dashboard-update", listener)
  })
  it("晚到的旧场景冲突检查不得提前解锁新场景的检查按钮", async () => {
    const lateA = deferred()
    const lateB = deferred()
    const wrapper = mount(WritingView, {
      props: props({
        chapterList: [1, 2],
        chapters: {
          1: { chapter_index: 1, title: "第一章", status: "draft" },
          2: { chapter_index: 2, title: "第二章", status: "draft" },
        },
        scenes: [],
      }),
      attachTo: document.body,
    })
    await flushPromises()
    const vm = wrapper.vm.$.setupState.vm

    // 章节 1 的检查 A 在途
    globalThis.api.writing.createConflictCheck.mockReturnValueOnce(lateA.promise)
    const first = vm.runConflictCheck()
    await vi.waitFor(() => {
      expect(globalThis.api.writing.createConflictCheck).toHaveBeenCalledTimes(1)
      expect(vm.conflictState.loading).toBe(true)
    })

    // 切到章节 2：loadSceneContext 重置 loading，新章节上发起检查 B
    await vm.selectChapter(2)
    await flushPromises()
    expect(vm.conflictState.loading).toBe(false)
    globalThis.api.writing.createConflictCheck.mockReturnValueOnce(lateB.promise)
    const second = vm.runConflictCheck()
    await vi.waitFor(() => {
      expect(globalThis.api.writing.createConflictCheck).toHaveBeenCalledTimes(2)
      expect(vm.conflictState.loading).toBe(true)
    })

    // 旧章节的检查 A 晚到结束：不得把 B 在途的 loading 提前置 false（双提交窗口）
    lateA.resolve({ id: "check-a", chapter_index: 1, items: [] })
    await first
    await flushPromises()
    expect(vm.conflictState.loading).toBe(true)

    // loading 未被误解锁时，并发提交会被入口守卫拒绝
    await vm.runConflictCheck()
    expect(globalThis.api.writing.createConflictCheck).toHaveBeenCalledTimes(2)

    lateB.resolve({ id: "check-b", chapter_index: 2, items: [] })
    await second
    await flushPromises()
    expect(vm.conflictState.loading).toBe(false)
    wrapper.unmount()
  })
})
