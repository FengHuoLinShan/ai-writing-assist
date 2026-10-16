import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import UnifiedNoticesPanel from "../../../vue/views/writing/components/UnifiedNoticesPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })

const basis = "a".repeat(64)
const notice = (overrides = {}) => ({
  notice_key: "writing.conflict:item-1",
  source_id: "writing.conflict",
  category: "conflict_check",
  severity: "high",
  target: { scene_id: "scene-1", chapter_index: 3 },
  summary: "人物行动顺序需要核对。",
  evidence: [{ chapter_index: 3, note: "当前地图修订与正文来源已核对" }],
  basis_fingerprint: basis,
  stale: true,
  status: "unread",
  row_version: 7,
  actions: [{ kind: "navigate", page: "writing", check_id: "check-1", item_id: "item-1" }],
  ...overrides,
})
const mountPanel = (overrides = {}) => mount(UnifiedNoticesPanel, {
  props: { projectId: "project-1", sceneId: "scene-1", chapterIndex: 3, ...overrides },
})

it("按来源和类别呈现优先级、失败占位及本地未保存说明", async () => {
  const unifiedNotices = vi.fn().mockResolvedValue({
    items: [notice({ stale: false }), notice({
      notice_key: "story.structure:info", source_id: "story.structure", category: "scene_structure",
      severity: "info", summary: "当前场景结构已读。", actions: [],
    })],
    unavailable_sources: [{ source_id: "assistant.forecast", label: "下一步建议", message: "暂时无法读取" }],
    muted_categories: [],
    partial: true,
  })
  setBridgeOverrides({ api: { assistant: { unifiedNotices } } })
  const wrapper = mountPanel({ unsaved: true })
  await flushPromises()

  expect(unifiedNotices).toHaveBeenCalledWith("project-1", expect.objectContaining({
    sceneId: "scene-1", chapterIndex: 3, signal: expect.any(AbortSignal),
  }))
  expect(wrapper.text()).toContain("正文有未保存修改")
  expect(wrapper.text()).toContain("本地正文未保存")
  expect(wrapper.text()).toContain("部分来源暂不可读")
  expect(wrapper.text()).toContain("不能据此判断整个范围已清空")
  expect(wrapper.text()).toContain("下一步建议")
  const groups = wrapper.findAll(".unified-notices__group > details")
  expect(groups[0].element.open).toBe(true)
  expect(groups[1].element.open).toBe(false)
  wrapper.unmount()
})

it("按 basis 与 row_version 写入已读，成功后刷新服务端状态", async () => {
  const unifiedNotices = vi.fn()
    .mockResolvedValueOnce({ items: [notice()], unavailable_sources: [], muted_categories: [], partial: false })
    .mockResolvedValueOnce({ items: [notice({ status: "read" })], unavailable_sources: [], muted_categories: [], partial: false })
  const setUnifiedNoticeDisposition = vi.fn().mockResolvedValue({ status: "read" })
  setBridgeOverrides({ api: { assistant: { unifiedNotices, setUnifiedNoticeDisposition } } })
  const wrapper = mountPanel()
  await flushPromises()
  await wrapper.get(".unified-notices__actions button:nth-child(2)").trigger("click")
  await flushPromises()

  expect(setUnifiedNoticeDisposition).toHaveBeenCalledWith({
    novel_id: "project-1",
    source_id: "writing.conflict",
    notice_key: "writing.conflict:item-1",
    basis_fingerprint: basis,
    scope: { scene_id: "scene-1", chapter_index: 3 },
    expected_row_version: 7,
    action: "read",
  })
  expect(unifiedNotices).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain("已读")
  wrapper.unmount()
})

it("遇到 409 不乐观移除，按新服务端状态刷新", async () => {
  const unifiedNotices = vi.fn()
    .mockResolvedValueOnce({ items: [notice()], unavailable_sources: [], muted_categories: [], partial: false })
    .mockResolvedValueOnce({ items: [notice({ notice_key: "writing.conflict:item-2", summary: "检查项已更新。", row_version: 8 })], unavailable_sources: [], muted_categories: [], partial: false })
  const setUnifiedNoticeDisposition = vi.fn().mockRejectedValue(Object.assign(new Error("提醒已变化"), { status: 409 }))
  setBridgeOverrides({ api: { assistant: { unifiedNotices, setUnifiedNoticeDisposition } } })
  const wrapper = mountPanel()
  await flushPromises()
  await wrapper.get(".unified-notices__actions button:nth-child(2)").trigger("click")
  await flushPromises()

  expect(wrapper.text()).toContain("检查项已更新")
  expect(wrapper.text()).toContain("提醒依据或版本已变化")
  expect(wrapper.text()).not.toContain("人物行动顺序需要核对")
  expect(unifiedNotices).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it("处置请求未结束时不能手动重读，完成后仍可继续操作", async () => {
  let finishDisposition
  const unifiedNotices = vi.fn()
    .mockResolvedValueOnce({ items: [notice()], unavailable_sources: [], muted_categories: [], partial: false })
    .mockResolvedValueOnce({ items: [notice({ status: "read" })], unavailable_sources: [], muted_categories: [], partial: false })
    .mockResolvedValueOnce({ items: [notice({ status: "read" })], unavailable_sources: [], muted_categories: [], partial: false })
  const setUnifiedNoticeDisposition = vi.fn(() => new Promise((resolve) => { finishDisposition = resolve }))
  setBridgeOverrides({ api: { assistant: { unifiedNotices, setUnifiedNoticeDisposition } } })
  const wrapper = mountPanel()
  await flushPromises()
  await wrapper.get(".unified-notices__actions button:nth-child(2)").trigger("click")
  const reload = wrapper.get(".unified-notices__header button")
  expect(reload.attributes("disabled")).toBeDefined()
  await reload.trigger("click")
  expect(unifiedNotices).toHaveBeenCalledTimes(1)

  finishDisposition({ status: "read" })
  await flushPromises()
  expect(wrapper.text()).toContain("已读")
  expect(reload.attributes("disabled")).toBeUndefined()
  await reload.trigger("click")
  await flushPromises()
  expect(unifiedNotices).toHaveBeenCalledTimes(3)
  wrapper.unmount()
})

it("类别静音与恢复各自携带当前 CAS 版本", async () => {
  const unifiedNotices = vi.fn()
    .mockResolvedValueOnce({ items: [notice()], unavailable_sources: [], muted_categories: [], partial: false })
    .mockResolvedValueOnce({ items: [], unavailable_sources: [], muted_categories: [{ source_id: "writing.conflict", category: "conflict_check", row_version: 4 }], partial: false })
    .mockResolvedValueOnce({ items: [notice()], unavailable_sources: [], muted_categories: [], partial: false })
  const setUnifiedNoticeCategoryMute = vi.fn().mockResolvedValue({})
  setBridgeOverrides({ api: { assistant: { unifiedNotices, setUnifiedNoticeCategoryMute } } })
  const wrapper = mountPanel()
  await flushPromises()
  await wrapper.get(".unified-notices__group-actions button").trigger("click")
  await flushPromises()
  expect(setUnifiedNoticeCategoryMute).toHaveBeenNthCalledWith(1, "project-1", "writing.conflict", "conflict_check", 0, true)
  await wrapper.get(".unified-notices__muted button").trigger("click")
  await flushPromises()
  expect(setUnifiedNoticeCategoryMute).toHaveBeenNthCalledWith(2, "project-1", "writing.conflict", "conflict_check", 4, false)
  expect(unifiedNotices).toHaveBeenCalledTimes(3)
  wrapper.unmount()
})

it("demo 只读隐藏处置和静音操作", async () => {
  setBridgeOverrides({ api: { assistant: { unifiedNotices: vi.fn().mockResolvedValue({
    items: [notice()], unavailable_sources: [], muted_categories: [], partial: false,
  }) } } })
  const wrapper = mountPanel({ readOnly: true })
  await flushPromises()
  expect(wrapper.text()).toContain("当前为只读视图")
  expect(wrapper.text()).not.toContain("标为已读")
  expect(wrapper.text()).not.toContain("明天提醒")
  expect(wrapper.text()).not.toContain("静音此类提醒")
  wrapper.unmount()
})

it("Evolution 阅读提醒可打开阅读面板或直达大纲边界确认", async () => {
  const notices = [
    notice({
      source_id: "evolution.reading",
      category: "reading_unread",
      notice_key: "evolution.reading:unread:chapter-3",
      summary: "当前已采用正文中有 1 章尚未完整阅读。",
      actions: [{ kind: "navigate", page: "writing", open_evolution_reading: true, label: "打开演化阅读" }],
    }),
    notice({
      source_id: "evolution.reading",
      category: "reading_review",
      notice_key: "evolution.reading:review-boundary:run-1",
      summary: "演化阅读的场景边界需要作者确认。",
      actions: [{ kind: "navigate", page: "outline", scene_id: "scene-1", label: "去大纲确认边界" }],
    }),
  ]
  setBridgeOverrides({ api: { assistant: { unifiedNotices: vi.fn().mockResolvedValue({
    items: notices, unavailable_sources: [], muted_categories: [], partial: false,
  }) } } })
  const wrapper = mountPanel()
  await flushPromises()

  const openButtons = wrapper.findAll(".unified-notices__actions button").filter((button) => (
    ["打开演化阅读", "去大纲确认边界"].includes(button.text())
  ))
  expect(openButtons.map((button) => button.text()).sort()).toEqual(["打开演化阅读", "去大纲确认边界"].sort())
  await openButtons.find((button) => button.text() === "打开演化阅读").trigger("click")
  expect(wrapper.emitted("open-notice")?.[0]?.[0]).toMatchObject({
    source_id: "evolution.reading",
    category: "reading_unread",
  })
  wrapper.unmount()
})

it("切换项目时丢弃旧项目迟到的响应", async () => {
  let resolveOld
  const unifiedNotices = vi.fn()
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    .mockResolvedValueOnce({ items: [notice({ notice_key: "writing.conflict:new", summary: "新作品提醒。" })], unavailable_sources: [], muted_categories: [], partial: false })
  setBridgeOverrides({ api: { assistant: { unifiedNotices } } })
  const wrapper = mountPanel()
  await wrapper.setProps({ projectId: "project-2" })
  await flushPromises()
  resolveOld({ items: [notice({ summary: "旧作品迟到提醒。" })], unavailable_sources: [], muted_categories: [], partial: false })
  await flushPromises()

  expect(wrapper.text()).toContain("新作品提醒")
  expect(wrapper.text()).not.toContain("旧作品迟到提醒")
  wrapper.unmount()
})
