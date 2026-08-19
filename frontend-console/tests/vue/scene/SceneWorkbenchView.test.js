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
  let latestModal
  let toast
  let closeModal
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
      reviewSceneSourceMappings: vi.fn(),
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
    api.outline.reviewSceneWorkbench.mockResolvedValue({ status: "reviewed" })
    api.outline.reviewSceneSourceMappings.mockResolvedValue({ status: "reviewed" })
    latestModal = null
    toast = vi.fn()
    closeModal = vi.fn()
    setBridgeOverrides({
      api,
      state,
      router,
      toast,
      showModalHtml: vi.fn((title, body, buttons) => { latestModal = { title, body, buttons } }),
      closeModal,
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

  function actionItem(key, id = "s1") {
    const item = {
      scene: {
        id, scene_index: 0, title: `场景 ${id}`, status: "canonical", source: "manual",
        narrative_tag: "draft", goal: "目标", core_conflict: "冲突", chapter_ids: ["1"], structure_meta: {},
      },
      health: [],
      health_details: { needs_organize: [] },
      chapter_range: "第 1 章",
    }
    if (key === "review") item.health = ["unreviewed"]
    if (key === "suggestion") {
      item.health = ["needs_organize"]
      item.health_details.needs_organize = [{ code: "pending_scene_fusion_suggestion", suggestion_id: "fusion-1" }]
    }
    if (key === "source_mapping") {
      item.health = ["needs_organize"]
      item.health_details.needs_organize = [{ code: "source_mapping_chapter_only", fingerprint: `fingerprint-${id}` }]
    }
    if (key === "organize") {
      item.health = ["needs_organize"]
      item.health_details.needs_organize = [{ code: "manual_organize" }]
    }
    if (key === "assign") item.health = ["unassigned"]
    if (key === "missing_setup") { item.health = ["missing_setup"]; item.scene.goal = null }
    return item
  }

  function actionPayload(items, extra = {}) {
    return {
      ...payload,
      total: items.length,
      items,
      unassigned_chapters: [],
      ...extra,
    }
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

  it("opens a focused fusion suggestion from a Today deep link", async () => {
    createWrapper({
      focusedSuggestionId: "fusion-1",
      fusionSuggestions: [{ id: "fusion-1", suggestion_kind: "fusion", proposed_action: "keep_separate", source_scene_ids: ["s1"] }],
    })
    await flushPromises()

    expect(latestModal?.title).toBe("保持场景分开")
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

  it.each([
    ["review", "标记已检查", null],
    ["suggestion", "查看融合建议", "保持场景分开"],
    ["source_mapping", "确认章节定位", "确认章节级正文定位"],
    ["organize", "整理映射", "整理场景正文范围"],
    ["assign", "关联章节", "移动 / 关联章节"],
    ["missing_setup", "补全设定", null],
    ["edit", "编辑", null],
  ])("单选 %s 直接进入真实动作", async (key, label, modalTitle) => {
    const item = actionItem(key)
    const workbench = actionPayload([item], key === "assign" ? { unassigned_chapters: [2] } : {})
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    createWrapper({
      workbench,
      fusionSuggestions: key === "suggestion" ? [{ id: "fusion-1", suggestion_kind: "fusion", proposed_action: "keep_separate", source_scene_ids: ["s1"] }] : [],
    })

    await wrapper.get('input[data-action="toggle-fusion-selection"]').setValue(true)
    expect(wrapper.get('[data-action="handle-selected-context-actions"]').text()).toBe(label)
    await wrapper.get('[data-action="handle-selected-context-actions"]').trigger("click")
    await flushPromises()

    if (modalTitle) expect(latestModal?.title).toBe(modalTitle)
    else expect(latestModal).toBeNull()
    if (key === "review") expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", { scene_ids: ["s1"], decision: "review" })
    if (["missing_setup", "edit"].includes(key)) expect(window.location.hash).toContain("scene_id=s1")
    if (key === "organize") expect(latestModal.buttons.map((button) => button.text)).toContain("标记为无需整理")
  })

  it("混合选择按动作分组，成功只移除已处理组", async () => {
    const workbench = actionPayload([actionItem("review", "s1"), actionItem("edit", "s2")])
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    createWrapper({ workbench })
    for (const input of wrapper.findAll('input[data-action="toggle-fusion-selection"]')) await input.setValue(true)

    expect(wrapper.get('[data-action="handle-selected-context-actions"]').text()).toBe("分组处理")
    await wrapper.get('[data-action="handle-selected-context-actions"]').trigger("click")
    expect(latestModal.title).toBe("按待办类型处理")
    expect(latestModal.body).toContain("采用 / 标记已检查")
    expect(latestModal.body).toContain("逐项编辑")

    await latestModal.buttons.find((button) => button.text === "采用 / 标记已检查（1）").handler()
    await flushPromises()
    expect(wrapper.get('.scene-workbench-row[data-id="s1"] input[data-action="toggle-fusion-selection"]').element.checked).toBe(false)
    expect(wrapper.get('.scene-workbench-row[data-id="s2"] input[data-action="toggle-fusion-selection"]').element.checked).toBe(true)
  })

  it("批量动作失败时保留原选择", async () => {
    const workbench = actionPayload([actionItem("source_mapping", "s1"), actionItem("source_mapping", "s2")])
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    api.outline.reviewSceneSourceMappings.mockRejectedValueOnce(new Error("网络异常"))
    createWrapper({ workbench })
    for (const input of wrapper.findAll('input[data-action="toggle-fusion-selection"]')) await input.setValue(true)

    await wrapper.get('[data-action="handle-selected-context-actions"]').trigger("click")
    expect(latestModal.title).toBe("批量确认章节级定位")
    await latestModal.buttons.find((button) => button.text === "确认定位").handler()
    await flushPromises()

    expect(wrapper.findAll('input[data-action="toggle-fusion-selection"]:checked')).toHaveLength(2)
    expect(toast).toHaveBeenCalledWith("网络异常", "error")
  })

  it("结构同类多选可批量标记无需整理", async () => {
    const workbench = actionPayload([actionItem("organize", "s1"), actionItem("organize", "s2")])
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    createWrapper({ workbench })
    for (const input of wrapper.findAll('input[data-action="toggle-fusion-selection"]')) await input.setValue(true)

    await wrapper.get('[data-action="handle-selected-context-actions"]').trigger("click")
    expect(latestModal.title).toBe("批量整理场景")
    await latestModal.buttons.find((button) => button.text === "标记选中项无需整理").handler()
    await flushPromises()

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", { scene_ids: ["s1", "s2"], decision: "ignore_structure" })
    expect(wrapper.findAll('input[data-action="toggle-fusion-selection"]:checked')).toHaveLength(0)
    expect(toast).toHaveBeenCalledWith("已标记为无需整理，可从场景更多菜单恢复", "success")
  })

  it("已忽略场景的更多菜单可恢复整理提醒", async () => {
    const item = actionItem("edit")
    item.scene.structure_meta.organize_ignored = true
    const workbench = actionPayload([item])
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    createWrapper({ workbench })

    await wrapper.get(".action-menu-btn").trigger("click")
    const restore = wrapper.get('[data-action="restore-scene-organize"]')
    expect(restore.text()).toBe("恢复整理提醒")
    await restore.trigger("click")
    await flushPromises()

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", { scene_ids: ["s1"], decision: "restore_structure" })
  })

  it("switches view mode in place without losing the filter draft or scroll context", async () => {
    createWrapper()
    const organize = wrapper.find(".scene-workbench__organize").element
    const normalMode = wrapper.get('[data-action="set-scene-view-mode"][data-mode="normal"]').element
    organize.scrollTop = 88
    normalMode.focus()
    await wrapper.get("#scene-filter-q").setValue("尚未应用的筛选")

    await wrapper.get('[data-action="set-scene-view-mode"][data-mode="normal"]').trigger("click")
    await flushPromises()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, expect.objectContaining({
      view_mode: "normal",
    }))
    expect(api.outline.getSceneWorkbench.mock.calls[0][2]).not.toHaveProperty("q")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(wrapper.get("#scene-filter-q").element.value).toBe("尚未应用的筛选")
    expect(wrapper.find(".scene-workbench__organize").element).toBe(organize)
    expect(organize.scrollTop).toBe(88)
    expect(document.activeElement).toBe(normalMode)
    expect(window.location.hash).toContain("mode=normal")
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
