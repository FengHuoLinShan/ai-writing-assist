/**
 * WorldRelationsTab 测试 — 渲染契约、分页、批量操作。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

import WorldRelationsTab from "../../../vue/views/world/components/WorldRelationsTab.vue"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const RELATIONS = [
  { id: "r1", source_name: "林澈", source_id: "e1", target_name: "沉钟港", target_id: "e2", relation_kind: "social", relation_type: "friend_of", description: "驻守旧港", status: "canonical", strength: 0.7 },
  { id: "r2", source_name: "萧岚", source_id: "e3", target_name: "雾隐城", target_id: "e4", relation_kind: "social", relation_type: "leader_of", description: "城主", status: "canonical", strength: 0.9 },
]

let router

function mountTab(propOverrides = {}) {
  return mount(WorldRelationsTab, {
    props: {
      projectId: "p-rel",
      relations: RELATIONS,
      relationsTotal: 2,
      relationsLoadError: null,
      ...propOverrides,
    },
  })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  router = { navigate: vi.fn(), refresh: vi.fn(async () => true) }
  setBridgeOverrides({
    api: {
      world: {
        deleteRelationship: vi.fn(async () => ({})),
        reviewEditRelationship: vi.fn(async () => ({})),
      },
    },
    state: { currentProjectId: "p-rel", currentView: "world" },
    router,
    toast: vi.fn(),
    showModalHtml: vi.fn(),
    confirmAction: vi.fn((_message, onConfirm, _confirmText) => {}),
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染", () => {
  it("描述文本与空态", () => {
    const wrapper = mountTab({ relations: [], relationsTotal: 0 })
    expect(wrapper.text()).toContain("管理世界对象与人物之间的关系")
    expect(wrapper.get('[role="search"]').attributes("aria-label")).toBe("查找已采用关系")
    expect(wrapper.find(".empty-state").exists()).toBe(true)
  })

  it("搜索无结果时保留搜索入口和恢复提示", () => {
    worldSession.relationListFilters.q = "不存在"
    const wrapper = mountTab({ relations: [], relationsTotal: 0 })
    expect(wrapper.get("#world-relation-search").element.value).toBe("不存在")
    expect(wrapper.find(".empty-state").text()).toContain("没有找到匹配的关系")
    expect(wrapper.find(".empty-state").text()).toContain("清除搜索")
  })

  it("关系表结构：列头、行数据、data-id", () => {
    const wrapper = mountTab()
    const table = wrapper.find("table.data-table")
    expect(table.exists()).toBe(true)
    expect(table.classes()).toContain("table-card-list")
    const rows = wrapper.findAll("tbody tr[data-id]")
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes("data-id")).toBe("r1")
    expect(rows[0].text()).toContain("林澈")
    expect(rows[0].text()).toContain("社会/组织")
    expect(rows[0].text()).toContain("朋友")
    expect(rows[0].text()).not.toContain("friend_of")
    expect(rows[0].text()).toContain("沉钟港")
    expect(rows[0].text()).toContain("驻守旧港")
    expect(rows[0].find('[data-action="edit-relation"]').exists()).toBe(true)
    expect(rows[0].find('[data-action="delete-relation"]').exists()).toBe(true)
    expect(rows[0].findAll("td[data-label]").map((cell) => cell.attributes("data-label"))).toEqual([
      "源对象", "关系分类与类型", "目标对象", "状态", "描述", "来源与证据", "操作",
    ])
  })

  it("内部标识默认收进诊断信息", () => {
    const wrapper = mountTab({
      relations: [{
        ...RELATIONS[0],
        workflow_id: "750d04f2-private-workflow",
        scene_id: "scene-private-id",
        source_chapter_id: "chapter-private-id",
      }],
      relationsTotal: 1,
    })

    expect(wrapper.find(".world-canonical-evidence").text()).not.toContain("private")
    expect(wrapper.find(".world-canonical-diagnostics summary").text()).toBe("诊断信息")
    expect(wrapper.find(".world-canonical-diagnostics").text()).toContain("750d04f2-private-workflow")
  })

  it("删除按钮携带 data-id", () => {
    const wrapper = mountTab()
    const deleteBtn = wrapper.find('tr[data-id="r1"] [data-action="delete-relation"]')
    expect(deleteBtn.attributes("data-id")).toBe("r1")
  })

  it("历史数据缺少分类时显示待分类和精确详细类型", () => {
    const wrapper = mountTab({ relations: [{ ...RELATIONS[0], relation_kind: "", relation_type: "legacy_link" }] })
    expect(wrapper.text()).toContain("待分类")
    expect(wrapper.text()).toContain("legacy_link（自定义）")
  })
})

describe("错误态", () => {
  it("relationsLoadError 提供可感知错误与重试", async () => {
    const wrapper = mountTab({ relations: [], relationsTotal: 0, relationsLoadError: "加载关系失败。" })
    expect(wrapper.find('[role="alert"]').text()).toContain("加载关系失败。")
    await wrapper.get('[role="alert"] button').trigger("click")
    expect(router.refresh).toHaveBeenCalledOnce()
  })
})

describe("分页", () => {
  it("总条数 > limit 时渲染 WorldPager", () => {
    const wrapper = mountTab({ relations: RELATIONS, relationsTotal: 25 })
    expect(wrapper.findComponent({ name: "WorldPager" }).exists()).toBe(true)
  })

  it("翻页更新 session skip 并写入 URL", async () => {
    worldSession.relationListFilters.q = "沉钟港"
    const wrapper = mountTab({ relations: RELATIONS, relationsTotal: 25 })
    const pager = wrapper.findComponent({ name: "WorldPager" })
    expect(worldSession.relationListFilters.skip).toBe(0)
    pager.vm.$emit("change", 1)
    await wrapper.vm.$nextTick()
    expect(worldSession.relationListFilters.skip).toBe(20)
    expect(router.navigate.mock.calls[0][3].get("q")).toBe("沉钟港")
    expect(router.navigate.mock.calls[0][3].get("page")).toBe("2")
  })
})

describe("搜索", () => {
  it("提交和清除搜索时重置页码并更新 URL", async () => {
    worldSession.relationListFilters.skip = 20
    const wrapper = mountTab()
    await wrapper.get("#world-relation-search").setValue("  雨夜结盟  ")
    await wrapper.get('[role="search"]').trigger("submit")

    expect(worldSession.relationListFilters).toEqual({ q: "雨夜结盟", skip: 0, limit: 20 })
    expect(router.navigate.mock.calls[0][3].get("q")).toBe("雨夜结盟")
    expect(router.navigate.mock.calls[0][3].has("page")).toBe(false)

    await wrapper.get('[role="search"] button[type="button"]').trigger("click")
    expect(worldSession.relationListFilters.q).toBe("")
    expect(router.navigate.mock.calls[1][3].toString()).toBe("")
  })
})

describe("批量操作", () => {
  it("WorldBulkToolbar 存在并传递 scope", () => {
    const wrapper = mountTab()
    const toolbar = wrapper.findComponent({ name: "WorldBulkToolbar" })
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.props("scope")).toBe("world-relations")
  })

  it("列表换页后剔除不再可见的选择", async () => {
    const wrapper = mountTab()
    await wrapper.find('input[data-id="r1"]').setValue(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")

    await wrapper.setProps({ relations: [RELATIONS[1]], relationsTotal: 1 })
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
  })
})
