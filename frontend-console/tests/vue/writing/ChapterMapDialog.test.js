import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ChapterMapDialog from "../../../vue/views/writing/components/ChapterMapDialog.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const link = (overrides = {}) => ({
  node_id: "map-1", node_title: "廷根城", level: "city", feature_id: "feature-1",
  feature_label: "旅馆", entity_id: "place-1", chapter_indices: [1], ...overrides,
})

describe("ChapterMapDialog", () => {
  let findMapLinks
  let navigate
  let state
  const wrappers = []
  function render(props = {}) {
    const wrapper = mount(ChapterMapDialog, { props: { open: true, projectId: "p1", chapter: 1, ...props }, attachTo: document.body })
    wrappers.push(wrapper)
    return wrapper
  }
  beforeEach(() => {
    findMapLinks = vi.fn().mockResolvedValue({ items: [], truncated: false })
    navigate = vi.fn()
    state = { currentProjectId: "p1" }
    setBridgeOverrides({ api: { world: { findMapLinks } }, router: { navigate }, state })
  })
  afterEach(() => {
    wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
    resetBridgeOverrides()
  })

  it("关闭时不请求，打开后按当前章查找并用地图名区分同名地点", async () => {
    findMapLinks.mockResolvedValue({ items: [link(), link({ node_id: "map-2", node_title: "北区街道 <img>" })], truncated: false })
    const wrapper = render({ open: false })
    expect(findMapLinks).not.toHaveBeenCalled()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(findMapLinks).toHaveBeenCalledWith("p1", { chapter_index: 1 })
    expect(wrapper.findAll(".chapter-map-result")).toHaveLength(2)
    expect(wrapper.text()).toContain("北区街道 <img>")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("feature-1")
    await wrapper.findAll(".chapter-map-result")[1].trigger("click")
    const [view, subtab, force, query] = navigate.mock.calls[0]
    expect([view, subtab, force]).toEqual(["map", null, true])
    expect(Object.fromEntries(query)).toEqual({ novel_id: "p1", node_id: "map-2", feature_id: "feature-1", from_chapter: "1" })
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("本章空态允许显式扩大范围，搜索仍保留作者输入", async () => {
    const wrapper = render()
    await flushPromises()
    expect(wrapper.text()).toContain("本章暂未关联地图地点")
    await wrapper.get("input[type=search]").setValue("码头")
    await wrapper.get("form").trigger("submit")
    await flushPromises()
    expect(findMapLinks).toHaveBeenLastCalledWith("p1", { chapter_index: 1, q: "码头" })
    await wrapper.get("input[type=checkbox]").setValue(true)
    await flushPromises()
    expect(findMapLinks).toHaveBeenLastCalledWith("p1", { q: "码头" })
    expect(wrapper.get("input[type=search]").element.value).toBe("码头")
    await wrapper.findAll("button").find((button) => button.text() === "打开地图").trigger("click")
    expect(Object.fromEntries(navigate.mock.calls[0][3])).toEqual({ novel_id: "p1", from_chapter: "1" })
  })

  it("明确地点引用只按 entity 查询，不把章节约束误加成 AND", async () => {
    const wrapper = render({ entityId: "place-1" })
    await flushPromises()
    expect(findMapLinks).toHaveBeenCalledWith("p1", { entity_id: "place-1" })
    expect(wrapper.find("input[type=checkbox]").exists()).toBe(false)
    expect(wrapper.text()).toContain("这个地点暂未关联地图")
  })

  it('整部作品未输入名称时提示输入，而不声称没有地图', async () => {
    const wrapper = render(); await flushPromises()
    findMapLinks.mockClear()
    await wrapper.get('input[type=checkbox]').setValue(true); await flushPromises()
    expect(findMapLinks).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入地点或地图名称')
  })

  it("失败保持浮层和搜索输入，可重试；截断零匹配不声称作品没有地图", async () => {
    findMapLinks.mockRejectedValueOnce(new Error("private request detail"))
    const wrapper = render()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain("正文仍保留")
    expect(wrapper.text()).not.toContain("private request detail")
    await wrapper.get("input[type=search]").setValue("旅馆")
    findMapLinks.mockResolvedValueOnce({ items: [], truncated: true })
    await wrapper.findAll("button").find((button) => button.text() === "重试").trigger("click")
    await flushPromises()
    expect(findMapLinks).toHaveBeenLastCalledWith("p1", { chapter_index: 1, q: "旅馆" })
    expect(wrapper.text()).toContain("只显示部分地图地点")
    expect(wrapper.text()).toContain("本次查找暂未匹配")
    expect(wrapper.text()).not.toContain("暂未找到已保存")
  })

  it("切换章节后忽略旧响应，关闭和切换项目后不执行旧地点导航", async () => {
    let resolveOld
    findMapLinks.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    const wrapper = render()
    expect(wrapper.get('[role="status"]').text()).toContain("正在查找")
    findMapLinks.mockResolvedValue({ items: [link({ feature_label: "第二章码头" })], truncated: false })
    await wrapper.setProps({ chapter: 2 })
    await flushPromises()
    resolveOld({ items: [link({ feature_label: "旧章旅馆" })], truncated: false })
    await flushPromises()
    expect(wrapper.text()).toContain("第二章码头")
    expect(wrapper.text()).not.toContain("旧章旅馆")
    state.currentProjectId = "p2"
    await wrapper.get(".chapter-map-result").trigger("click")
    expect(navigate).not.toHaveBeenCalled()
    await wrapper.setProps({ open: false })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it("按 Escape 关闭并恢复入口焦点，Tab 留在浮层", async () => {
    const origin = document.createElement("button")
    document.body.append(origin)
    origin.focus()
    const wrapper = render({ open: false })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get("input[type=search]").element)
    const last = wrapper.findAll("button").at(-1)
    last.element.focus()
    await last.trigger("keydown", { key: "Tab" })
    expect(document.activeElement).toBe(wrapper.get('[aria-label="关闭地图查找"]').element)
    await wrapper.get('[role="dialog"]').trigger("keydown", { key: "Escape" })
    expect(wrapper.emitted("close")).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(origin)
    origin.remove()
  })
})
