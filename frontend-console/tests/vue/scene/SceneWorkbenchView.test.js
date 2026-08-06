import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { sceneAutoExtractManager } from "../../../vue/views/scene/sceneAutoExtractManager.js"
import SceneWorkbenchView from "../../../vue/views/scene/SceneWorkbenchView.vue"

const payload = {
  total: 2,
  skip: 0,
  health: {
    unreviewed: { label: "未复核", count: 1 },
    unassigned: { label: "未关联章节", count: 0 },
    missing_setup: { label: "缺设定", count: 1 },
    needs_organize: { label: "待整理", count: 0, breakdown: {} },
  },
  progress: { as_of_chapter: 2, current: 1, upcoming: 1, past: 0, unassigned: 0 },
  unassigned_chapters: [],
  fusion_suggestions: { pending_count: 0 },
  items: [
    {
      scene: {
        id: "s1", scene_index: 0, title: "<img src=x onerror=alert(1)>",
        status: "draft", source: "manual", narrative_tag: "draft",
        goal: "潜入", core_conflict: "守卫", chapter_ids: ["1"], structure_meta: {},
      },
      health: ["unreviewed"],
      chapter_range: "第 1 章",
      summary: "潜入",
    },
    {
      scene: {
        id: "s2", scene_index: 1, title: "撤离", status: "draft",
        source: "manual", narrative_tag: "transition", goal: "撤离",
        core_conflict: "追兵", chapter_ids: ["2"], structure_meta: {},
      },
      health: [],
      chapter_range: "第 2 章",
      summary: "撤离",
    },
  ],
}

describe("SceneWorkbenchView", () => {
  let wrapper
  const state = {
    currentProjectId: "p1",
    currentProject: { id: "p1", title: "测试项目" },
    currentView: "outline",
    currentSubView: "scenes",
    viewStates: {},
  }
  const router = {
    getCurrentQuery: vi.fn(() => new URLSearchParams()),
    navigate: vi.fn(),
  }
  const api = {
    outline: {
      getSceneWorkbench: vi.fn(),
      listFusionSuggestions: vi.fn(),
      updateScene: vi.fn(),
      reviewSceneWorkbench: vi.fn(),
    },
    tasks: { get: vi.fn(), cancel: vi.fn() },
    imports: { startStage: vi.fn() },
  }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes")
    vi.clearAllMocks()
    sceneAutoExtractManager.resetMemory()
    api.outline.getSceneWorkbench.mockResolvedValue(payload)
    api.outline.listFusionSuggestions.mockResolvedValue({ items: [], total: 0 })
    api.outline.updateScene.mockResolvedValue({ id: "s1" })
    setBridgeOverrides({
      api,
      state,
      router,
      toast: vi.fn(),
      showModalHtml: vi.fn(),
      closeModal: vi.fn(),
      esc: (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;"),
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    sceneAutoExtractManager.resetMemory()
    resetBridgeOverrides()
  })

  function createWrapper(extra = {}) {
    wrapper = mount(SceneWorkbenchView, {
      attachTo: document.body,
      props: {
        projectId: "p1",
        workbench: payload,
        fusionSuggestions: [],
        viewMode: "hot",
        sceneFilters: {},
        ...extra,
      },
    })
    return wrapper
  }

  it("renders the full main workbench with escaped API text and no HTML injection", () => {
    createWrapper()

    expect(wrapper.find(".outline-scene-layout > .subnav").exists()).toBe(true)
    expect(wrapper.find('[aria-label="场景筛选"]').exists()).toBe(true)
    expect(wrapper.findAll(".scene-workbench-row")).toHaveLength(2)
    expect(wrapper.find('.scene-workbench-row[data-id="s1"] .scene-workbench-row__title').text())
      .toBe("<img src=x onerror=alert(1)>")
    expect(wrapper.find('.scene-workbench-row[data-id="s1"] img').exists()).toBe(false)
  })

  it("keeps Scene menu actions behind a readable contextual trigger", async () => {
    createWrapper()
    const row = wrapper.find('.scene-workbench-row[data-id="s2"]')
    const trigger = row.get(".action-menu-btn")
    expect(trigger.attributes("aria-label")).toBe("撤离的更多操作")
    await trigger.trigger("click")
    expect(row.find('[data-action="open-writing-scene"]').attributes("data-id")).toBe("s2")
  })

  it("keeps Scene current marker non-interactive while sibling navigation uses buttons", async () => {
    createWrapper()
    for (const action of ["nav-story-outline", "nav-arcs", "nav-threads"]) {
      const item = wrapper.find(`[data-action="${action}"]`)
      expect(item.element.tagName).toBe("BUTTON")
      expect(item.attributes("type")).toBe("button")
      expect(item.attributes("aria-current")).toBeUndefined()
    }
    const current = wrapper.find('[data-action="nav-scenes"]')
    expect(current.element.tagName).toBe("SPAN")
    expect(current.attributes("aria-current")).toBe("page")

    router.navigate.mockClear()
    await wrapper.find('[data-action="nav-threads"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("outline", "threads")
    await current.trigger("click")
    expect(router.navigate).toHaveBeenCalledTimes(1)
  })

  it("selects and bulk-selects in place without rerouting or resetting scroll", async () => {
    createWrapper()
    const organize = wrapper.find(".scene-workbench__organize").element
    organize.scrollTop = 88

    await wrapper.find('.scene-workbench-row[data-id="s2"] [data-action="select-workbench-scene"]').trigger("click")
    await wrapper.find('.scene-workbench-row[data-id="s2"] input[data-action="toggle-fusion-selection"]').setValue(true)

    expect(wrapper.find('.scene-workbench-row[data-id="s2"]').classes()).toContain("is-selected")
    expect(window.location.hash).toContain("scene_id=s2")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(organize.scrollTop).toBe(88)
    expect(wrapper.find(".scene-fusion-toolbar").text()).toContain("1")
  })

  it("saves the Vue-owned detail draft and refreshes in place", async () => {
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.find("#scene-detail-title").setValue("新标题")
    await wrapper.find('[data-action="save-scene-detail"]').trigger("click")
    await flushPromises()

    expect(api.outline.updateScene).toHaveBeenCalledWith("s1", "p1", expect.objectContaining({
      title: "新标题",
      goal: "潜入",
      core_conflict: "守卫",
    }))
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1", expect.objectContaining({
      view_mode: "hot",
    }))
  })

  it("does not adopt a late auto-extraction task after the view is unmounted", async () => {
    let resolveStart
    let modalButtons = []
    const toast = vi.fn()
    api.imports.startStage.mockImplementation(() => new Promise((resolve) => { resolveStart = resolve }))
    const adopt = vi.spyOn(sceneAutoExtractManager, "adopt")
    setBridgeOverrides({
      api,
      state,
      router,
      toast,
      showModalHtml: vi.fn((_title, body, buttons) => {
        document.getElementById("modal-body").innerHTML = body
        modalButtons = buttons
      }),
      closeModal: vi.fn(),
      esc: (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;"),
    })
    document.body.insertAdjacentHTML("beforeend", '<div id="modal-body"></div>')
    createWrapper()

    await wrapper.get('[data-action="scene-auto-extract"]').trigger("click")
    const pending = modalButtons[0].handler()
    wrapper.unmount()
    wrapper = null
    resolveStart({ task_id: "late-task" })
    await pending

    expect(adopt).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("late-task"), "success")
    adopt.mockRestore()
  })

  it("submits Scene auto-extraction only once on a synchronous double click", async () => {
    let resolveStart
    let modalButtons = []
    api.imports.startStage.mockImplementation(() => new Promise((resolve) => { resolveStart = resolve }))
    setBridgeOverrides({
      api,
      state,
      router,
      toast: vi.fn(),
      showModalHtml: vi.fn((_title, body, buttons) => {
        document.getElementById("modal-body").innerHTML = body
        modalButtons = buttons
      }),
      closeModal: vi.fn(),
      esc: (value) => String(value ?? ""),
    })
    document.body.insertAdjacentHTML("beforeend", '<div id="modal-body"></div>')
    createWrapper()
    await wrapper.get('[data-action="scene-auto-extract"]').trigger("click")

    const first = modalButtons[0].handler()
    const second = modalButtons[0].handler()
    await expect(second).resolves.toBe(false)
    expect(api.imports.startStage).toHaveBeenCalledTimes(1)
    expect(sceneAutoExtractManager.state.submitting).toBe(true)

    resolveStart({ task_id: "scene-double" })
    await expect(first).resolves.toBe(true)
    expect(sceneAutoExtractManager.state.submitting).toBe(false)
  })
})
