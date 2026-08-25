/**
 * OutlineArcsTab 测试 — 渲染、筛选 UI、批量选择交互。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { mount } from "@vue/test-utils"
import { setBridgeOverrides, resetBridgeOverrides } from "../../../vue/bridge/index.js"
import { clearAllBulkSelections, clearOutlineFilterDrafts } from "../../../vue/views/outline/logic/outlineBulkSelection.js"
import OutlineArcsTab from "../../../vue/views/outline/components/OutlineArcsTab.vue"

const SAMPLE_ARCS = [
  { id: "a1", name: "第一卷", title: "第一卷", status: "canonical", start_chapter: 1, end_chapter: 10, arc_goal: "开篇", thread_type: "main" },
  { id: "a2", name: "第二卷", status: "draft", start_chapter: 11, end_chapter: 20, arc_goal: "发展" },
]

let routerCalls
let toastCalls
let confirmAction

beforeEach(() => {
  clearAllBulkSelections()
  clearOutlineFilterDrafts()
  routerCalls = []
  toastCalls = []
  confirmAction = vi.fn()
  setBridgeOverrides({
    api: { outline: {} },
    state: { currentProjectId: "p-test" },
    router: {
      navigate: (...args) => { routerCalls.push(args) },
      refresh: vi.fn(async () => true),
    },
    toast: (...args) => { toastCalls.push(args) },
    confirmAction,
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染", () => {
  it("空态无 arcs 且无错误时显示空态", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: [], arcsTotal: 0 },
    })
    expect(wrapper.text()).toContain("暂无篇章")
  })

  it("错误态优先显示错误消息", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: [], arcsTotal: 0, arcsLoadError: "网络错误" },
    })
    expect(wrapper.text()).toContain("网络错误")
  })

  it("有 arcs 时渲染表格行", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("第一卷")
    expect(rows[1].text()).toContain("第二卷")
  })

  it("标记列渲染结构化 badge", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: {
        projectId: "p1",
        subView: "arcs",
        arcs: [{ ...SAMPLE_ARCS[0], provenance_meta: { source: "deep_import", needs_review: true } }],
        arcsTotal: 1,
      },
    })
    const markCell = wrapper.find('td[data-label="标记"]')
    expect(markCell.text()).toContain("深度导入")
    expect(markCell.text()).not.toContain("[object Object]")
    expect(markCell.find(".badge").exists()).toBe(true)
  })

  it("诊断筛选无结果时给出可重新分析提示", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: {
        projectId: "p1",
        subView: "arcs",
        arcs: [],
        filters: { source: "", status: "", workflow_id: "wf-1", needs_review: "", skip: 0, limit: 50 },
      },
    })
    expect(wrapper.text()).toContain("结构分析不完整或无匹配结果")
  })

  it("章节范围正确显示", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    const cells = wrapper.findAll(".outline-asset-mono")
    expect(cells.length).toBeGreaterThanOrEqual(2)
    expect(cells[0].text()).toBe("1-10")
  })
})

describe("筛选", () => {
  it("默认折叠筛选并在摘要显示已启用条件数", () => {
    const wrapper = mount(OutlineArcsTab, {
      props: {
        projectId: "p1",
        subView: "arcs",
        arcs: SAMPLE_ARCS,
        arcsTotal: 2,
        filters: { status: "deprecated", source: "", workflow_id: "batch-1", needs_review: "true", skip: 0, limit: 50 },
      },
    })
    const filters = wrapper.get(".outline-structure-filters")
    expect(filters.attributes("open")).toBeUndefined()
    expect(filters.get(":scope > summary").text()).toContain("筛选篇章")
    expect(filters.get(":scope > summary").text()).toContain("已启用 3 项")
  })

  it("应用筛选触发 router.navigate、收起面板并把焦点还给摘要", async () => {
    const wrapper = mount(OutlineArcsTab, {
      attachTo: document.body,
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    const filters = wrapper.get(".outline-structure-filters")
    filters.element.open = true
    await wrapper.find('[data-action="apply-outline-structure-filters"]').trigger("click")
    expect(routerCalls.length).toBeGreaterThanOrEqual(1)
    expect(routerCalls[0][0]).toBe("outline")
    expect(routerCalls[0][1]).toBe("arcs")
    expect(routerCalls[0][2]).toBe(true)
    expect(filters.element.open).toBe(false)
    expect(filters.get(":scope > summary").element).toBe(document.activeElement)
    wrapper.unmount()
  })

  it("重置筛选触发 router.navigate", async () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    await wrapper.find('[data-action="reset-outline-structure-filters"]').trigger("click")
    expect(routerCalls.length).toBeGreaterThanOrEqual(1)
  })

  it("分页只使用已应用条件，重挂载后保留未应用草稿", async () => {
    const props = {
      projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 120,
      filters: { status: "", source: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 },
    }
    const wrapper = mount(OutlineArcsTab, { props })
    await wrapper.find("#outline-filter-status").setValue("candidate")
    await wrapper.find('[data-action="next-outline-structure-page"]').trigger("click")
    const query = routerCalls.at(-1)[3]
    expect(query.get("status")).toBeNull()
    expect(query.get("page")).toBe("2")
    wrapper.unmount()

    const remounted = mount(OutlineArcsTab, {
      props: { ...props, filters: { ...props.filters, skip: 50 } },
    })
    expect(remounted.find("#outline-filter-status").element.value).toBe("candidate")
  })
})

describe("批量选择", () => {
  it("行内操作菜单保留删除动作并提供篇章上下文名称", async () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    const row = wrapper.findAll("tbody tr")[0]
    const trigger = row.get(".action-menu-btn")
    expect(trigger.attributes("aria-label")).toBe("第一卷的更多操作")
    await trigger.trigger("click")
    expect(row.find('[data-action="delete-arc"]').exists()).toBe(true)
  })

  it("选择单项后 toolbar 出现", async () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    const checkbox = wrapper.find('input[data-action="bulk-toggle-one"]')
    expect(checkbox.exists()).toBe(true)
    await checkbox.setValue(true)
    // toolbar should now be visible
    expect(wrapper.find(".bulk-toolbar").exists()).toBe(true)
  })

  it("列表换页后剔除不再可见的选择", async () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    await wrapper.find('input[data-id="a1"]').setValue(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")

    await wrapper.setProps({ arcs: [SAMPLE_ARCS[1]], arcsTotal: 1 })
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
  })

  it("批量操作确认数量只包含已选中的篇章", async () => {
    const wrapper = mount(OutlineArcsTab, {
      props: { projectId: "p1", subView: "arcs", arcs: SAMPLE_ARCS, arcsTotal: 2 },
    })
    await wrapper.find('input[data-action="bulk-toggle-one"]').setValue(true)
    await wrapper.find('[data-bulk-action="delete-arcs"]').trigger("click")

    expect(confirmAction).toHaveBeenCalledOnce()
    expect(confirmAction.mock.calls[0][0]).toContain("选中的 1 项")
  })
})
