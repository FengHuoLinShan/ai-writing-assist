import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { sceneAutoExtractManager } from "../../../vue/views/scene/sceneAutoExtractManager.js"
import { resetSceneSession } from "../../../vue/views/scene/sceneModel.js"
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
    world: { listEntities: vi.fn(), getEntity: vi.fn() },
  }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    resetSceneSession("p1")
    window.innerWidth = 1024
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes")
    vi.clearAllMocks()
    sceneAutoExtractManager.resetMemory()
    api.outline.getSceneWorkbench.mockResolvedValue(payload)
    api.outline.listFusionSuggestions.mockResolvedValue({ items: [], total: 0 })
    api.outline.updateScene.mockResolvedValue({ id: "s1" })
    api.outline.reviewSceneWorkbench.mockResolvedValue({ status: "reviewed" })
    api.outline.reviewSceneSourceMappings.mockResolvedValue({ status: "reviewed" })
    api.world.listEntities.mockResolvedValue({ items: [] })
    api.world.getEntity.mockResolvedValue({ id: "c1", name: "沈岚", entity_type: "character", status: "canonical", summary: "王城密探" })
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

    expect(wrapper.find(".outline-scene-layout > .outline-toolbar").exists()).toBe(true)
    expect(wrapper.findAll(".outline-scene-layout .subnav")).toHaveLength(1)
    expect(wrapper.find('[aria-label="场景筛选"]').exists()).toBe(true)
    expect(wrapper.findAll(".scene-workbench-row")).toHaveLength(2)
    expect(wrapper.find('.scene-workbench-row[data-id="s1"] .scene-workbench-row__title').text())
      .toBe("<img src=x onerror=alert(1)>")
    expect(wrapper.find('.scene-workbench-row[data-id="s1"] img').exists()).toBe(false)
  })

  it("默认折叠筛选，在摘要显示已启用条件和未应用修改", async () => {
    createWrapper({ sceneFilters: { status: "draft" } })
    const panel = wrapper.get(".scene-workbench-filters")
    expect(panel.attributes("open")).toBeUndefined()
    expect(panel.get(":scope > summary").text()).toContain("搜索与筛选")
    expect(panel.get(":scope > summary").text()).toContain("已启用 1 项")

    panel.element.open = true
    await wrapper.get("#scene-filter-q").setValue("尚未应用")
    expect(panel.get(":scope > summary").text()).toContain("有未应用修改")
  })

  it("成功应用后收起筛选并把焦点还给摘要", async () => {
    createWrapper()
    const panel = wrapper.get(".scene-workbench-filters")
    panel.element.open = true
    await wrapper.get("#scene-filter-q").setValue("潜入")
    await wrapper.get('[data-action="apply-scene-filters"]').trigger("click")
    await flushPromises()

    expect(panel.attributes("open")).toBeUndefined()
    expect(panel.get(":scope > summary").element).toBe(document.activeElement)
    expect(panel.get(":scope > summary").text()).toContain("已启用 1 项")
    expect(panel.get(":scope > summary").text()).not.toContain("未应用修改")
  })

  it("未应用筛选草稿在工作台重挂载后仍保留", async () => {
    createWrapper()
    const panel = wrapper.get(".scene-workbench-filters")
    panel.element.open = true
    await wrapper.get("#scene-filter-q").setValue("离开后继续")
    wrapper.unmount()
    wrapper = null

    createWrapper()
    expect(wrapper.get(".scene-workbench-filters").get(":scope > summary").text()).toContain("有未应用修改")
    expect(wrapper.get("#scene-filter-q").element.value).toBe("离开后继续")
  })

  it("区分初始空态与筛选无结果，并提供直接下一步", async () => {
    const emptyWorkbench = {
      ...payload,
      total: 0,
      items: [],
      progress: { as_of_chapter: null, current: 0, upcoming: 0, past: 0, unassigned: 0 },
      health: Object.fromEntries(Object.entries(payload.health).map(([key, value]) => [key, { ...value, count: 0 }])),
    }
    api.outline.getSceneWorkbench.mockResolvedValue(emptyWorkbench)
    createWrapper({ workbench: emptyWorkbench })

    expect(wrapper.get(".scene-workbench-empty h2").text()).toBe("还没有场景")
    expect(wrapper.get('[data-action="empty-scene-auto-extract"]').text()).toBe("从正文整理场景")
    expect(wrapper.get('[data-action="empty-ai-create-planned-scene"]').text()).toBe("AI 创作细纲")
    await wrapper.get('[data-action="empty-scene-auto-extract"]').trigger("click")
    expect(latestModal?.title).toBe("从正文整理场景")

    wrapper.unmount()
    wrapper = null
    createWrapper({ workbench: emptyWorkbench, sceneFilters: { q: "不存在的场景" } })
    expect(wrapper.get(".scene-workbench-empty h2").text()).toBe("没有找到符合条件的场景")
    await wrapper.get('[data-action="clear-scene-empty-filters"]').trigger("click")
    await flushPromises()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, expect.not.objectContaining({ q: expect.anything() }))
    expect(wrapper.get(".scene-workbench-empty h2").text()).toBe("还没有场景")
  })

  it("局部刷新时禁用旧列表，失败后保留内容并可重试", async () => {
    let rejectRefresh
    api.outline.getSceneWorkbench.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRefresh = reject }))
    createWrapper()
    const panel = wrapper.get(".scene-workbench-filters")
    panel.element.open = true
    await wrapper.get("#scene-filter-q").setValue("潜入")
    await wrapper.get('[data-action="apply-scene-filters"]').trigger("click")
    await wrapper.vm.$nextTick()

    expect(wrapper.get(".scene-workbench__organize").attributes("aria-busy")).toBe("true")
    expect(wrapper.get(".scene-workbench__content").attributes("inert")).toBe("")
    expect(wrapper.get(".scene-workbench-refresh").text()).toContain("正在更新场景列表")

    rejectRefresh(new Error("网络暂不可用"))
    await flushPromises()
    expect(wrapper.get('.scene-workbench-refresh[role="alert"]').text()).toContain("当前内容仍保留")
    expect(wrapper.findAll(".scene-workbench-row")).toHaveLength(2)
    expect(wrapper.get(".scene-workbench__content").attributes("inert")).toBeUndefined()
    expect(panel.attributes("open")).toBeDefined()

    api.outline.getSceneWorkbench.mockResolvedValueOnce(payload)
    await wrapper.get('[data-action="retry-scene-refresh"]').trigger("click")
    await flushPromises()
    expect(wrapper.find(".scene-workbench-refresh").exists()).toBe(false)
    expect(wrapper.get(".scene-workbench__organize").attributes("aria-busy")).toBe("false")
  })

  it("exposes progress filters as pressed buttons and labels each scene segment", () => {
    const workbench = {
      ...payload,
      items: payload.items.map((item, index) => ({ ...item, segment: index ? "upcoming" : "current" })),
    }
    createWrapper({ workbench, sceneFilters: { segment: "current" } })

    expect(wrapper.get(".scene-workbench-overview").attributes("open")).toBe("")
    const filters = wrapper.findAll('[data-action="filter-progress-segment"]')
    expect(filters).toHaveLength(4)
    expect(filters.map((filter) => filter.attributes("aria-pressed"))).toEqual(["true", "false", "false", "false"])
    expect(filters.map((filter) => filter.attributes("class"))).toEqual(expect.arrayContaining([
      expect.stringContaining("scene-progress-filter--current"),
      expect.stringContaining("scene-progress-filter--upcoming"),
      expect.stringContaining("scene-progress-filter--past"),
      expect.stringContaining("scene-progress-filter--unassigned"),
    ]))
    expect(wrapper.get('.scene-workbench-row[data-id="s1"] .scene-progress-chip').classes()).toContain("scene-progress-chip--current")
  })

  it("窄屏默认收起场景概况并在摘要优先显示当前筛选", () => {
    window.innerWidth = 390
    createWrapper({ sceneFilters: { segment: "upcoming", health: "missing_setup" } })

    const overview = wrapper.get(".scene-workbench-overview")
    expect(overview.attributes("open")).toBeUndefined()
    expect(overview.get(":scope > summary").text()).toContain("后续 1 · 缺设定 1")
    expect(overview.findAll('[data-action="filter-progress-segment"]')).toHaveLength(4)
    expect(overview.findAll('[data-action="filter-health"]')).toHaveLength(4)
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

  it("uses the shared current-aware outline navigation", async () => {
    createWrapper()
    for (const action of ["nav-story-outline", "nav-arcs", "nav-threads", "nav-scenes"]) {
      const item = wrapper.find(`[data-action="${action}"]`)
      expect(item.element.tagName).toBe("BUTTON")
      expect(item.attributes("type")).toBe("button")
      expect(item.attributes("aria-current")).toBe(action === "nav-scenes" ? "page" : undefined)
    }

    router.navigate.mockClear()
    await wrapper.find('[data-action="nav-threads"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("outline", "threads")
  })

  it("keeps one primary scene action and moves low-frequency tools into a disclosure", () => {
    createWrapper()
    const actions = wrapper.get('[aria-label="场景操作"]')
    expect(actions.findAll(".btn-primary")).toHaveLength(1)
    expect(actions.get('[data-action="ai-create-planned-scene"]').text()).toBe("AI 创作细纲")
    expect(actions.get(".scene-workbench-tools summary").text()).toBe("整理工具")
    expect(actions.get('[data-action="scene-auto-extract"]').text()).toBe("从正文整理场景")
    expect(actions.find('[data-role="smart-dedup-action"]').exists()).toBe(true)
    expect(actions.get('[data-mode="hot"]').attributes("aria-pressed")).toBe("true")
    expect(actions.get('[data-mode="normal"]').attributes("aria-pressed")).toBe("false")
  })

  it("把场景 AI 进度与操作统一放在标题下方任务区", () => {
    sceneAutoExtractManager.state.meta = { start_chapter: 2, end_chapter: 6 }
    sceneAutoExtractManager.state.progress = {
      taskId: "scene-extract-progress",
      statusLabel: "整理中",
      percent: 40,
      hasPercent: true,
      terminal: false,
      failed: false,
      done: false,
      cancelled: false,
      availableActions: ["cancel"],
    }
    createWrapper()

    const region = wrapper.get(".outline-task-status")
    expect(region.get(".outline-task-status__title").text()).toBe("AI 任务")
    const card = region.get('[data-role="scene-auto-extract-progress"] .workflow-progress')
    expect(card.text()).toContain("范围：第 2–6 章")
    expect(card.get('[data-action="cancel-scene-auto-extract"]').element.closest(".workflow-progress")).toBe(card.element)
  })

  it("selects and bulk-selects in place without rerouting or resetting scroll", async () => {
    createWrapper()
    const organize = wrapper.find(".scene-workbench__organize").element
    organize.scrollTop = 88
    expect(wrapper.find(".scene-detail-rail").exists()).toBe(false)
    expect(wrapper.find(".scene-fusion-toolbar").exists()).toBe(false)

    await wrapper.find('.scene-workbench-row[data-id="s2"] [data-action="select-workbench-scene"]').trigger("click")
    await wrapper.find('.scene-workbench-row[data-id="s2"] input[data-action="toggle-fusion-selection"]').setValue(true)

    expect(wrapper.find('.scene-workbench-row[data-id="s2"]').classes()).toContain("is-selected")
    expect(wrapper.get(".scene-detail-rail").text()).toContain("撤离")
    expect(window.location.hash).toContain("scene_id=s2")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(organize.scrollTop).toBe(88)
    const toolbar = wrapper.get(".scene-fusion-toolbar")
    expect(toolbar.get('[role="status"]').text()).toContain("1个场景已选")
    expect(toolbar.findAll(".btn-primary")).toHaveLength(1)

    await toolbar.get('[data-action="toggle-visible-fusion-selection"]').trigger("click")
    expect(wrapper.findAll('input[data-action="toggle-fusion-selection"]:checked')).toHaveLength(2)
    await wrapper.get('[data-action="clear-fusion-selection"]').trigger("click")
    expect(wrapper.find(".scene-fusion-toolbar").exists()).toBe(false)
    expect(wrapper.findAll('input[data-action="toggle-fusion-selection"]:checked')).toHaveLength(0)
  })

  it("用分组长表单编辑并从桌面详情安全返回列表", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    createWrapper({ selectedSceneId: "s1" })

    expect(wrapper.findAll(".scene-detail-section legend").map((legend) => legend.text())).toEqual(["基本信息", "创作要点"])
    expect(wrapper.get(".scene-detail-summary h4").text()).toBe("章节与来源")
    const save = wrapper.get('[data-action="save-scene-detail"]')
    const actions = wrapper.get(".scene-detail-actions")
    const more = actions.get(".scene-detail-action-menu .action-menu-btn")
    expect(save.attributes("disabled")).toBeDefined()
    expect(save.text()).toBe("已保存")
    expect(actions.findAll(":scope > .btn-primary")).toHaveLength(1)
    expect(more.text()).toBe("更多")
    expect(more.attributes("aria-label")).toContain("更多结构操作")
    expect(actions.get('[data-action="start-merge-scene"]').text()).toBe("合并场景")
    expect(actions.get('[data-action="start-split-scene"]').text()).toBe("拆分场景")
    expect(actions.get('[data-action="start-merge-scene"]').element.parentElement.classList.contains("action-menu-list")).toBe(true)

    await wrapper.get("#scene-detail-title").setValue("尚未保存的标题")
    expect(save.attributes("disabled")).toBeUndefined()
    expect(save.text()).toBe("保存修改")
    expect(more.attributes("disabled")).toBeDefined()
    expect(more.attributes("aria-label")).toContain("请先保存或放弃当前修改")
    expect(actions.findAll(":scope > button")[1].attributes("disabled")).toBeDefined()
    await wrapper.get('[data-action="close-scene-detail"]').trigger("click")
    expect(confirm).toHaveBeenCalledWith("当前场景有未保存修改，确定放弃并继续吗？")
    expect(wrapper.find(".scene-detail-rail").exists()).toBe(true)

    await wrapper.get("#scene-detail-title").setValue("<img src=x onerror=alert(1)>")
    const opener = wrapper.get('.scene-workbench-row[data-id="s1"] [data-action="select-workbench-scene"]')
    await wrapper.get('[data-action="close-scene-detail"]').trigger("click")
    await flushPromises()
    expect(wrapper.find(".scene-detail-rail").exists()).toBe(false)
    expect(document.activeElement).toBe(opener.element)
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
    expect(wrapper.get('[data-mode="normal"]').attributes("aria-pressed")).toBe("true")
    expect(wrapper.get('[data-mode="hot"]').attributes("aria-pressed")).toBe("false")
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

  it("用人物名称显示视角人物，清空后 wire 仍提交 null", async () => {
    const item = actionItem("edit")
    item.scene.pov_character_id = "c1"
    const workbench = actionPayload([item])
    api.outline.getSceneWorkbench.mockResolvedValue(workbench)
    createWrapper({ workbench, selectedSceneId: "s1" })
    await flushPromises()

    expect(wrapper.get("#scene-detail-pov-character [data-reference-selected]").text()).toContain("沈岚")
    expect(wrapper.get("#scene-detail-pov-character [data-reference-selected]").text()).toContain("王城密探")
    expect(wrapper.find("#scene-detail-pov_character_id").exists()).toBe(false)

    await wrapper.get("#scene-detail-pov-character [data-reference-remove]").trigger("click")
    await wrapper.get('[data-action="save-scene-detail"]').trigger("click")
    await flushPromises()

    expect(api.outline.updateScene).toHaveBeenCalledWith("s1", "p1", expect.objectContaining({
      pov_character_id: null,
    }))
  })

  it("opens the mobile detail as a dialog, focuses the missing field, and restores the row focus", async () => {
    window.innerWidth = 390
    const item = actionItem("missing_setup")
    item.scene.goal = "目标"
    item.scene.core_conflict = null
    const workbench = actionPayload([item])
    createWrapper({ workbench })

    const opener = wrapper.get('[data-action="context-complete-setup"]')
    opener.element.focus()
    await opener.trigger("click")
    await flushPromises()

    const dialog = wrapper.get('.scene-workbench-drawer__dialog')
    expect(dialog.attributes("role")).toBe("dialog")
    expect(dialog.attributes("aria-modal")).toBe("true")
    expect(document.activeElement?.id).toBe("scene-detail-core_conflict")

    await wrapper.get(".scene-workbench-drawer").trigger("keydown", { key: "Escape" })
    await flushPromises()
    expect(wrapper.find(".scene-workbench-drawer").exists()).toBe(false)
    expect(document.activeElement).toBe(opener.element)
  })

  it("keeps an unsaved mobile detail draft until the author confirms leaving", async () => {
    window.innerWidth = 390
    let confirmDiscard
    globalThis.confirmAction.mockImplementation((_message, onConfirm) => { confirmDiscard = onConfirm })
    createWrapper()

    const opener = wrapper.get('.scene-workbench-row[data-id="s1"] [data-action="select-workbench-scene"]')
    opener.element.focus()
    await opener.trigger("click")
    await wrapper.get("#scene-detail-title").setValue("尚未保存的标题")
    const beforeUnload = new Event("beforeunload", { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)
    await wrapper.get('[data-action="close-scene-detail"]').trigger("click")
    await flushPromises()

    expect(globalThis.confirmAction).toHaveBeenCalledWith("放弃尚未保存的场景修改？", expect.any(Function), "放弃修改")
    expect(wrapper.find(".scene-workbench-drawer").exists()).toBe(true)

    confirmDiscard()
    await flushPromises()
    expect(wrapper.find(".scene-workbench-drawer").exists()).toBe(false)
    expect(document.activeElement).toBe(opener.element)
  })

  it("does not discard a desktop detail draft when another scene is selected", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get("#scene-detail-title").setValue("尚未保存的标题")

    await wrapper.get('.scene-workbench-row[data-id="s2"] [data-action="select-workbench-scene"]').trigger("click")

    expect(confirm).toHaveBeenCalledWith("当前场景有未保存修改，确定放弃并继续吗？")
    expect(wrapper.get("#scene-detail-title").element.value).toBe("尚未保存的标题")
    expect(wrapper.get('.scene-workbench-row[data-id="s1"]').classes()).toContain("is-selected")
  })

  it("keeps the detail draft and shows an inline error when saving fails", async () => {
    let rejectSave
    api.outline.updateScene.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get("#scene-detail-title").setValue("失败后保留")

    await wrapper.get('[data-action="save-scene-detail"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-action="save-scene-detail"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-action="save-scene-detail"]').text()).toBe("保存中...")
    expect(wrapper.get("#scene-detail-pov-character").element.closest(".scene-detail-field")?.getAttribute("aria-disabled")).toBe("true")

    rejectSave(new Error("网络暂不可用"))
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe("保存失败：网络暂不可用")
    expect(wrapper.get("#scene-detail-title").element.value).toBe("失败后保留")
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
