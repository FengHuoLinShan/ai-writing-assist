/**
 * WorldObjectsTab 测试 — 渲染契约、筛选导航、热点概览、提取抽屉、批次分组、批量。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import WorldObjectsTab from "../../../vue/views/world/components/WorldObjectsTab.vue"
import { autoExtractManager } from "../../../vue/views/world/workflowManagers.js"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { getBulkSelection } from "../../../vue/views/world/logic/worldBulkSelection.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const ENTITIES = [
  { id: "e1", name: "沉钟港", entity_type: "location", status: "canonical", source: "manual", summary: "旧港", importance: 0.5 },
  { id: "e2", name: "林澈", entity_type: "character", status: "candidate", source: "deep_import", summary: "巡港人", needs_review: true },
]

let navigateMock
let toastMock

function mountTab(propOverrides = {}) {
  return mount(WorldObjectsTab, {
    props: {
      projectId: "p-obj",
      entities: ENTITIES,
      entitiesTotal: 2,
      entityTypes: [
        { value: "location", label: "地点" },
        { value: "character", label: "人物" },
      ],
      ...propOverrides,
    },
  })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  autoExtractManager.stop()
  autoExtractManager.state.taskId = null
  autoExtractManager.state.status = "就绪"
  autoExtractManager.state.meta = null
  autoExtractManager.state.progress = null
  navigateMock = vi.fn()
  toastMock = vi.fn()
  setBridgeOverrides({
    state: { currentProjectId: "p-obj", currentView: "world" },
    router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
    toast: toastMock,
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("表格渲染契约", () => {
  it("行/复选框/状态/来源/注意列与 vanilla 一致", () => {
    const wrapper = mountTab()
    const rows = wrapper.findAll("tbody tr[data-id]")
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes("data-id")).toBe("e1")
    expect(rows[0].find('input[data-action="bulk-toggle-one"][data-scope="world-objects"][data-id="e1"]').exists()).toBe(true)
    expect(rows[0].text()).toContain("沉钟港")
    expect(rows[0].text()).toContain("手动")
    expect(rows[1].find('[data-label="注意"]').classes()).toContain("world-table-cell--warning")
    expect(rows[1].find('[data-action="mark-entity-reviewed"]').exists()).toBe(true)
    expect(rows[1].find('[data-action="edit-entity"]').text()).toBe("编辑后采用")
    expect(wrapper.find('input[data-action="bulk-toggle-all"][data-scope="world-objects"]').exists()).toBe(true)
  })

  it("行内菜单使用对象名称且保留既有 data-action", async () => {
    const wrapper = mountTab()
    const row = wrapper.find('tbody tr[data-id="e1"]')
    const trigger = row.get(".action-menu-btn")
    expect(trigger.attributes("aria-label")).toBe("沉钟港的更多操作")
    await trigger.trigger("click")
    expect(row.find('[data-action="delete-entity"]').attributes("data-id")).toBe("e1")
  })

  it("空态渲染新建入口；错误态 role=alert", () => {
    const empty = mountTab({ entities: [], entitiesTotal: 0 })
    expect(empty.text()).toContain("还没有世界对象")
    expect(empty.find('[data-action="new"]').exists()).toBe(true)

    const failed = mountTab({ entities: [], entitiesTotal: 0, entitiesLoadError: "网络错误" })
    expect(failed.find('.empty-state[role="alert"]').exists()).toBe(true)
    expect(failed.text()).toContain("网络错误")
  })

  it("卡片模式渲染 world-object-card", () => {
    const wrapper = mountTab({ objectViewMode: "card" })
    expect(wrapper.findAll(".world-object-card[data-id]")).toHaveLength(2)
  })
})

describe("筛选", () => {
  it("应用：读取表单 → skip 归零 → navigate 写 query", async () => {
    const wrapper = mountTab()
    await wrapper.find("#filter-entity-type").setValue("location")
    await wrapper.find("#filter-q").setValue("港")
    await wrapper.find('[data-action="apply-filters"]').trigger("click")
    expect(navigateMock).toHaveBeenCalledTimes(1)
    const [view, subView, replace, query] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "objects"])
    expect(query.get("entity_type")).toBe("location")
    expect(query.get("q")).toBe("港")
    expect(query.has("page")).toBe(false)
  })

  it("重置：恢复默认筛选", async () => {
    const wrapper = mountTab({ objectFilters: { entity_type: "location", display_state: "review", q: "港", source: "", workflow_id: "", needs_review: "", auto_ingested: "", focus: "", skip: 40, limit: 20 } })
    await wrapper.find('[data-action="reset-filters"]').trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("entity_type")).toBeNull()
    expect(query.get("display_state")).toBe("active")
  })

  it("筛选面板开合持久化到 localStorage", async () => {
    const wrapper = mountTab()
    const toggle = wrapper.find('[data-action="toggle-filter-panel"][data-filter-key="objects"]')
    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(wrapper.find("#filter-q").isVisible()).toBe(false)
    await toggle.trigger("click")
    expect(toggle.attributes("aria-expanded")).toBe("true")
    expect(JSON.parse(localStorage.getItem("novel_world_filter_panels:p-obj")).objects).toBe(true)
  })
})

describe("热点概览", () => {
  it("facet 点击切换 focus 并 navigate", async () => {
    const wrapper = mountTab({
      rankingFacets: { important: 1, hot: 2, other: 3, by_type: [{ entity_type: "location", count: 2 }] },
      rankingContext: { status: "unavailable" },
    })
    const facet = wrapper.find('[data-action="set-hot-focus"][data-focus="hot"]')
    expect(facet.find("strong").text()).toBe("2")
    await facet.trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("focus")).toBe("hot")
  })

  it("已激活 facet 再点取消 focus", async () => {
    const wrapper = mountTab({ objectFilters: { entity_type: "", display_state: "active", q: "", source: "", workflow_id: "", needs_review: "", auto_ingested: "", focus: "hot", skip: 0, limit: 20 } })
    await wrapper.find('[data-action="set-hot-focus"][data-focus="hot"]').trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("focus")).toBeNull()
  })

  it("normal 模式不渲染热点概览", () => {
    const wrapper = mountTab({ discoveryMode: "normal" })
    expect(wrapper.find(".world-hot-overview").exists()).toBe(false)
  })
})

describe("自动提取抽屉", () => {
  it("默认收起；autoExtractOpen 时渲染面板并可提交", async () => {
    const startStage = vi.fn(async () => ({ task_id: "task-extract-1", status: "running" }))
    setBridgeOverrides({
      api: { imports: { startStage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    worldSession.autoExtractOpen = true
    const wrapper = mountTab()
    const panel = wrapper.find(".world-extract-panel")
    expect(panel.exists()).toBe(true)
    expect(wrapper.find("#w-extract-status").text()).toContain("就绪")
    await wrapper.find('[data-action="submit-extract"]').trigger("click")
    await vi.waitFor(() => expect(startStage).toHaveBeenCalledWith("world_objects", "p-obj", 1, 10, false, false, expect.anything()))
  })

  it("有 progress 时渲染进度卡而非状态行", () => {
    autoExtractManager.state.progress = {
      taskId: "task-1", label: "世界对象与别名/关系自动提取", statusLabel: "运行中",
      percent: 40, hasPercent: true,
    }
    worldSession.autoExtractOpen = true
    const wrapper = mountTab()
    expect(wrapper.find("details.workflow-progress").exists()).toBe(true)
    expect(wrapper.find("#w-extract-status").exists()).toBe(false)
  })
})

describe("批次分组（normal 模式）", () => {
  it("自动入库组与其他对象组拆分渲染", () => {
    const wrapper = mountTab({
      discoveryMode: "normal",
      batches: [{ batch_id: "b1", ingested_at: "2026-07-17T10:00:00Z", entities: [{ id: "e2" }] }],
    })
    const groups = wrapper.findAll(".world-batch-group")
    expect(groups).toHaveLength(2)
    expect(groups[0].text()).toContain("自动入库")
    expect(groups[0].find("tr[data-id='e2']").exists()).toBe(true)
    expect(groups[1].text()).toContain("其他对象")
    expect(groups[1].find("tr[data-id='e1']").exists()).toBe(true)
    expect(groups[0].find(".badge-new").exists()).toBe(true)
  })
})

describe("分页与批量", () => {
  it("total > limit 时渲染分页并 navigate", async () => {
    const wrapper = mountTab({ entitiesTotal: 50 })
    const next = wrapper.find('[data-action="next-page"]')
    expect(next.exists()).toBe(true)
    await next.trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("page")).toBe("2")
  })

  it("批量选择驱动工具条计数", async () => {
    const wrapper = mountTab()
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
    await wrapper.find('input[data-action="bulk-toggle-one"][data-id="e1"]').setValue(true)
    expect(getBulkSelection("world-objects").has("e1")).toBe(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")
  })
})
