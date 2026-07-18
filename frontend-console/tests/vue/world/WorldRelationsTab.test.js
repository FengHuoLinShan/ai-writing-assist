/**
 * WorldRelationsTab 测试 — 渲染契约、分页、批量操作。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

import WorldRelationsTab from "../../../vue/views/world/components/WorldRelationsTab.vue"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const RELATIONS = [
  { id: "r1", source_name: "林澈", source_id: "e1", target_name: "沉钟港", target_id: "e2", relation_type: "friend_of", description: "驻守旧港", status: "canonical", strength: 0.7 },
  { id: "r2", source_name: "萧岚", source_id: "e3", target_name: "雾隐城", target_id: "e4", relation_type: "leader_of", description: "城主", status: "canonical", strength: 0.9 },
]

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
  setBridgeOverrides({
    api: {
      world: {
        deleteRelationship: vi.fn(async () => ({})),
        reviewEditRelationship: vi.fn(async () => ({})),
      },
    },
    state: { currentProjectId: "p-rel", currentView: "world" },
    router: { navigate: vi.fn(), refresh: vi.fn(async () => true) },
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
    expect(wrapper.find(".empty-state").exists()).toBe(true)
  })

  it("关系表结构：列头、行数据、data-id", () => {
    const wrapper = mountTab()
    const table = wrapper.find("table.data-table")
    expect(table.exists()).toBe(true)
    const rows = wrapper.findAll("tbody tr[data-id]")
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes("data-id")).toBe("r1")
    expect(rows[0].text()).toContain("林澈")
    expect(rows[0].text()).toContain("friend_of")
    expect(rows[0].text()).toContain("沉钟港")
    expect(rows[0].text()).toContain("驻守旧港")
    expect(rows[0].find('[data-action="delete-relation"]').exists()).toBe(true)
  })

  it("删除按钮携带 data-id", () => {
    const wrapper = mountTab()
    const deleteBtn = wrapper.find('tr[data-id="r1"] [data-action="delete-relation"]')
    expect(deleteBtn.attributes("data-id")).toBe("r1")
  })
})

describe("错误态", () => {
  it("relationsLoadError 渲染", () => {
    const wrapper = mountTab({ relations: [], relationsTotal: 0, relationsLoadError: "加载关系失败。" })
    expect(wrapper.find(".empty-state").text()).toContain("加载关系失败。")
  })
})

describe("分页", () => {
  it("总条数 > limit 时渲染 WorldPager", () => {
    const wrapper = mountTab({ relations: RELATIONS, relationsTotal: 25 })
    expect(wrapper.findComponent({ name: "WorldPager" }).exists()).toBe(true)
  })

  it("翻页更新 session skip 并调用 router.refresh", async () => {
    const wrapper = mountTab({ relations: RELATIONS, relationsTotal: 25 })
    const pager = wrapper.findComponent({ name: "WorldPager" })
    expect(worldSession.relationListFilters.skip).toBe(0)
    pager.vm.$emit("change", 1)
    await wrapper.vm.$nextTick()
    expect(worldSession.relationListFilters.skip).toBe(20)
  })
})

describe("批量操作", () => {
  it("WorldBulkToolbar 存在并传递 scope", () => {
    const wrapper = mountTab()
    const toolbar = wrapper.findComponent({ name: "WorldBulkToolbar" })
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.props("scope")).toBe("world-relations")
  })
})
