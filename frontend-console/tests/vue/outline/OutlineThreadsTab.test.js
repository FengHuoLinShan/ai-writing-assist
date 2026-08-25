/**
 * OutlineThreadsTab 测试 — 剧情线列表、信息推进、筛选、批量选择交互。
 * DOM 契约对齐 vanilla _renderThreads + _renderThreadInformationProgression；
 * 伏笔/揭示列表为 vanilla 未挂载死代码，不在 threads 视图契约内。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { mount } from "@vue/test-utils"
import { nextTick } from "vue"
import { setBridgeOverrides, resetBridgeOverrides } from "../../../vue/bridge/index.js"
import { clearAllBulkSelections, clearOutlineFilterDrafts } from "../../../vue/views/outline/logic/outlineBulkSelection.js"
import OutlineThreadsTab from "../../../vue/views/outline/components/OutlineThreadsTab.vue"

const SAMPLE_THREADS = [
  { id: "t1", name: "主线", status: "canonical", thread_type: "main", summary: "主角成长" },
  { id: "t2", name: "支线", status: "draft", thread_type: "sub", summary: "配角故事" },
]

const SAMPLE_UNASSIGNED_FORESHADOWING = [
  { id: "uf1", name: "未归类伏笔", summary: "未归入剧情线的伏笔", status: "draft" },
]

const SAMPLE_UNASSIGNED_REVEALS = [
  { id: "ur1", secret_summary: "未归类揭示", status: "draft" },
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
    esc: (v) => String(v ?? ""),
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染", () => {
  it("有线程时渲染表格行", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("主线")
    expect(rows[0].find('td[data-label="类型"]').text()).toBe("主线")
    expect(rows[1].find('td[data-label="类型"]').text()).toBe("支线")
  })

  it("无线程且无错误时显示空态", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: [], threadsTotal: 0 },
    })
    expect(wrapper.text()).toContain("暂无剧情线")
  })

  it("深度导入筛选无结果时给出可重新分析提示", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1",
        subView: "threads",
        threads: [],
        filters: { source: "deep_import", status: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 },
      },
    })
    expect(wrapper.text()).toContain("结构分析不完整或无匹配结果")
  })

  it("来源筛选包含“全部来源”，标记列渲染 badge 而非对象字符串", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1",
        subView: "threads",
        threads: [{ ...SAMPLE_THREADS[0], provenance_meta: { source: "deep_import", needs_review: true } }],
      },
    })
    expect(wrapper.find('#outline-filter-source option[value=""]').text()).toBe("全部来源")
    const markCell = wrapper.find('td[data-label="标记"]')
    expect(markCell.text()).toContain("深度导入")
    expect(markCell.text()).not.toContain("[object Object]")
    expect(markCell.find(".badge").exists()).toBe(true)
  })

  it("有错误显示错误态", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: [], threadsTotal: 0, threadsLoadError: "加载失败" },
    })
    expect(wrapper.text()).toContain("加载失败")
  })
})

describe("信息推进", () => {
  it("归入剧情线的伏笔/揭示出现在信息推进区", () => {
    const threads = [
      { id: "t1", name: "主线", status: "canonical", related_thread_ids: ["t1"] },
    ]
    const foreshadowing = [
      { id: "f1", name: "秘密武器", summary: "秘密", status: "planted", related_thread_ids: ["t1"], planned_seed_chapter: 3 },
    ]
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1", subView: "threads",
        threads,
        foreshadowing,
        reveals: [],
      },
    })
    expect(wrapper.text()).toContain("信息推进")
    expect(wrapper.text()).toContain("秘密")
  })

  it("有信息的剧情线默认展开并按信息运动分组，空剧情线保持折叠", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1",
        subView: "threads",
        threads: SAMPLE_THREADS,
        foreshadowing: [{
          id: "f1",
          summary: "先让潮门发光",
          related_thread_ids: ["t1"],
          planned_seed_chapter: 3,
          provenance_meta: { information_movement_id: "movement-1" },
        }],
        reveals: [{
          id: "r1",
          secret_summary: "再揭示潮门在筛选继承者",
          related_thread_ids: ["t1"],
          reveal_stages: [{ chapter_index: 5 }],
          provenance_meta: { information_movement_id: "movement-1" },
        }],
      },
    })

    const details = wrapper.findAll(".outline-preview-section")
    expect(details[0].attributes("open")).toBe("")
    expect(details[1].attributes("open")).toBeUndefined()
    expect(wrapper.findAll(".outline-information-movement")).toHaveLength(1)
    expect(wrapper.find(".outline-information-movement h4").text()).toBe("推进 1")
    expect(wrapper.findAll(".outline-information-node")).toHaveLength(2)
  })

  it("旧揭示深链聚焦并标出包含揭示的剧情线", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      attachTo: document.body,
      props: {
        projectId: "p1",
        subView: "threads",
        threads: SAMPLE_THREADS,
        informationFocus: "reveals",
        reveals: [{
          id: "r1",
          secret_summary: "潮门在筛选继承者",
          related_thread_ids: ["t2"],
          reveal_stages: [{ chapter_index: 5 }],
        }],
      },
    })
    await nextTick()

    const target = wrapper.find('[data-information-focus-match="true"]')
    expect(target.classes()).toContain("is-deep-linked")
    expect(target.attributes("open")).toBe("")
    expect(target.find("summary").element).toBe(document.activeElement)
    wrapper.unmount()
  })

  it("显示未归入剧情线的项", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1", subView: "threads",
        threads: SAMPLE_THREADS,
        unassignedForeshadowing: SAMPLE_UNASSIGNED_FORESHADOWING,
        unassignedReveals: SAMPLE_UNASSIGNED_REVEALS,
      },
    })
    expect(wrapper.text()).toContain("未归入剧情线（2）")
    expect(wrapper.text()).toContain("未归类伏笔")
    expect(wrapper.text()).toContain("未归类揭示")
    expect(wrapper.find('[data-id="uf1"]').attributes("aria-label")).toBe("将 未归类伏笔 归入剧情线")
  })
})

describe("筛选", () => {
  it("默认折叠筛选并在摘要显示已启用条件数", () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: {
        projectId: "p1",
        subView: "threads",
        threads: SAMPLE_THREADS,
        filters: { status: "deprecated", source: "deep_import", workflow_id: "", needs_review: "", skip: 0, limit: 50 },
      },
    })
    const filters = wrapper.get(".outline-structure-filters")
    expect(filters.attributes("open")).toBeUndefined()
    expect(filters.get(":scope > summary").text()).toContain("筛选剧情线")
    expect(filters.get(":scope > summary").text()).toContain("已启用 2 项")
  })

  it("应用筛选触发 navigate、收起面板并把焦点还给摘要", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      attachTo: document.body,
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    const filters = wrapper.get(".outline-structure-filters")
    filters.element.open = true
    await wrapper.find('[data-action="apply-outline-structure-filters"]').trigger("click")
    expect(routerCalls.length).toBeGreaterThanOrEqual(1)
    expect(routerCalls[0][1]).toBe("threads")
    expect(filters.element.open).toBe(false)
    expect(filters.get(":scope > summary").element).toBe(document.activeElement)
    wrapper.unmount()
  })

  it("分页不偷偷应用编辑中筛选，但重挂载保留草稿", async () => {
    const props = {
      projectId: "p1", subView: "threads", threads: SAMPLE_THREADS, threadsTotal: 120,
      filters: { status: "", source: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 },
    }
    const wrapper = mount(OutlineThreadsTab, { props })
    await wrapper.find("#outline-filter-status").setValue("candidate")
    await wrapper.find('[data-action="next-outline-structure-page"]').trigger("click")
    const query = routerCalls.at(-1)[3]
    expect(query.get("status")).toBeNull()
    expect(query.get("page")).toBe("2")
    wrapper.unmount()

    const remounted = mount(OutlineThreadsTab, {
      props: { ...props, filters: { ...props.filters, skip: 50 } },
    })
    expect(remounted.find("#outline-filter-status").element.value).toBe("candidate")
  })
})

describe("批量选择", () => {
  it("有剧情线时批量工具条常驻，选择后更新计数", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    // vanilla renderBulkToolbar：列表非空时工具条常驻，0 选中时按钮禁用
    const toolbar = wrapper.find(".bulk-toolbar")
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.find(".bulk-toolbar__status strong").text()).toBe("0")
    expect(toolbar.find('[data-bulk-action="review-threads"]').attributes("disabled")).toBeDefined()

    const checkbox = wrapper.find('input[data-action="bulk-toggle-one"]')
    await checkbox.setValue(true)
    expect(toolbar.find(".bulk-toolbar__status strong").text()).toBe("1")
    expect(toolbar.find('[data-bulk-action="review-threads"]').attributes("disabled")).toBeUndefined()
  })

  it("列表换页后剔除不再可见的选择", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    await wrapper.find('input[data-id="t1"]').setValue(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")

    await wrapper.setProps({ threads: [SAMPLE_THREADS[1]], threadsTotal: 1 })
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
  })

  it("批量操作只提交已选中的剧情线", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    await wrapper.find('input[data-action="bulk-toggle-one"]').setValue(true)
    await wrapper.find('[data-bulk-action="delete-threads"]').trigger("click")

    expect(confirmAction).toHaveBeenCalledOnce()
    expect(confirmAction.mock.calls[0][0]).toContain("选中的 1 项")
  })

  it("行内操作菜单对齐 renderActionMenu 契约", async () => {
    const wrapper = mount(OutlineThreadsTab, {
      props: { projectId: "p1", subView: "threads", threads: SAMPLE_THREADS },
    })
    const row = wrapper.findAll("tbody tr")[0]
    const menu = row.find(".action-menu")
    const trigger = row.find(".action-menu-btn")
    expect(trigger.exists()).toBe(true)
    expect(trigger.attributes("aria-label")).toBe("主线的更多操作")
    expect(menu.classes()).not.toContain("open")
    await trigger.trigger("click")
    expect(menu.classes()).toContain("open")
    expect(row.find('[data-action="delete-thread"]').exists()).toBe(true)
  })
})
