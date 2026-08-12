/**
 * WorldAliasesTab 测试 — 渲染契约、别名分组、分页、批量操作。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

import WorldAliasesTab from "../../../vue/views/world/components/WorldAliasesTab.vue"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const ALIASES = [
  { entity_id: "e1", alias: "小名", alias_type: "nickname", entity_name: "主角", status: "canonical", source: "manual", confidence: 1.0 },
  { entity_id: "e1", alias: "代号", alias_type: "alias", entity_name: "主角", status: "canonical", source: "import", confidence: 0.9 },
  { entity_id: "e2", alias: "旧港", alias_type: "name", entity_name: "沉钟港", status: "canonical", source: "manual", confidence: 0.85 },
]

function mountTab(propOverrides = {}) {
  return mount(WorldAliasesTab, {
    props: {
      projectId: "p-alias",
      aliases: ALIASES,
      aliasesTotal: 3,
      aliasesLoadError: null,
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
        deleteAlias: vi.fn(async () => ({})),
        updateAlias: vi.fn(async () => ({})),
      },
    },
    state: { currentProjectId: "p-alias", currentView: "world" },
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
    const wrapper = mountTab({ aliases: [], aliasesTotal: 0 })
    expect(wrapper.text()).toContain("管理世界对象的别名、称号和化名")
    expect(wrapper.find(".empty-state").exists()).toBe(true)
  })

  it("别名表结构：列头、行数据、data-id, rowspan", () => {
    const wrapper = mountTab()
    const table = wrapper.find("table.data-table")
    expect(table.exists()).toBe(true)
    const rows = wrapper.findAll("tbody tr[data-id]")
    // 3 个别名 = 3 行
    expect(rows).toHaveLength(3)
    // data-id 格式为 entity_id::alias
    expect(rows[0].attributes("data-id")).toBe("e1::小名")
    expect(rows[1].attributes("data-id")).toBe("e1::代号")
    expect(rows[2].attributes("data-id")).toBe("e2::旧港")
    // rowspan: 主角 2 个别名共享 rowspan=2
    const cellWithRowspan = table.findAll('td[rowspan="2"]')
    expect(cellWithRowspan).toHaveLength(1)
    expect(cellWithRowspan[0].text()).toContain("主角")
    expect(cellWithRowspan[0].text()).toContain("2 个别名")
    // 别名文本与类型
    expect(rows[0].text()).toContain("小名")
    expect(rows[0].text()).toContain("昵称")
    expect(rows[1].text()).toContain("代号")
    expect(rows[1].text()).toContain("化名")
    expect(rows[2].text()).toContain("旧港")
    expect(rows[2].text()).toContain("名称")
  })

  it("删除按钮携带 data-entity-id 和 data-alias", () => {
    const wrapper = mountTab()
    const deleteBtn = wrapper.find('tr[data-id="e1::小名"] [data-action="delete-alias"]')
    expect(deleteBtn.attributes("data-entity-id")).toBe("e1")
    expect(deleteBtn.attributes("data-alias")).toBe("小名")
  })

  it("managed_by_suggestion 的别名不显示删除按钮，显示提示文字", () => {
    const aliasesWithManaged = [
      ...ALIASES,
      { entity_id: "e1", alias: "受管的", alias_type: "name", entity_name: "主角", status: "canonical", managed_by_suggestion: true },
    ]
    const wrapper = mountTab({ aliases: aliasesWithManaged })
    const rows = wrapper.findAll("tbody tr[data-id]")
    const managedRow = rows.find((r) => r.attributes("data-id") === "e1::受管的")
    expect(managedRow).toBeTruthy()
    expect(managedRow.text()).toContain("随对象建议处理")
    expect(managedRow.find('[data-action="delete-alias"]').exists()).toBe(false)
  })
})

describe("错误态", () => {
  it("aliasesLoadError 渲染", () => {
    const wrapper = mountTab({ aliases: [], aliasesTotal: 0, aliasesLoadError: "加载别名失败。" })
    expect(wrapper.find(".empty-state").text()).toContain("加载别名失败。")
  })
})

describe("分页", () => {
  it("总条数 > limit 时渲染 WorldPager", () => {
    const wrapper = mountTab({ aliases: ALIASES, aliasesTotal: 25 })
    expect(wrapper.findComponent({ name: "WorldPager" }).exists()).toBe(true)
  })

  it("翻页更新 session 并调用 router.refresh", async () => {
    const wrapper = mountTab({ aliases: ALIASES, aliasesTotal: 25 })
    const pager = wrapper.findComponent({ name: "WorldPager" })
    expect(worldSession.aliasListFilters.skip).toBe(0)
    pager.vm.$emit("change", 1)
    await wrapper.vm.$nextTick()
    expect(worldSession.aliasListFilters.skip).toBe(20)
  })
})

describe("批量操作", () => {
  it("WorldBulkToolbar 存在并传递 scope", () => {
    const wrapper = mountTab()
    const toolbar = wrapper.findComponent({ name: "WorldBulkToolbar" })
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.props("scope")).toBe("world-aliases")
  })

  it("列表换页后剔除不再可见的选择", async () => {
    const wrapper = mountTab()
    await wrapper.find('input[data-id="e1::小名"]').setValue(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")

    await wrapper.setProps({ aliases: [ALIASES[2]], aliasesTotal: 1 })
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
  })
})
