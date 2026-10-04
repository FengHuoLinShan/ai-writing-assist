import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldChangeHistory from "../../../vue/views/world/components/WorldChangeHistory.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"

function item(overrides = {}) {
  return {
    kind: "entity",
    revision_id: "rev-1",
    target_id: "entity-1",
    target_title: "林澈",
    target_state: "active",
    reason: "manual_update",
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    writing_chapter_index: 4,
    version_number: null,
    changed_fields: ["hidden_truth"],
    change_note: null,
    ...overrides,
  }
}

let api
let navigate

beforeEach(() => {
  resetWorldSession()
  navigate = vi.fn()
  api = { world: { listWorldChangeHistory: vi.fn() } }
  setBridgeOverrides({ api, router: { navigate }, toast: vi.fn() })
})

afterEach(() => {
  resetBridgeOverrides()
  resetWorldSession()
})

function mountOverlay() {
  return mount(WorldChangeHistory, { props: { projectId: "p1", open: true }, attachTo: document.body })
}

describe("WorldChangeHistory 时间线", () => {
  it("合并条目按作者语言展示：时间悬停、类型、原因、进度、改动与备注", async () => {
    api.world.listWorldChangeHistory.mockResolvedValueOnce({
      items: [
        item(),
        item({ kind: "page", revision_id: "rev-2", target_id: "page-1", target_title: "北港风物志", reason: "manual_publish", version_number: 3, changed_fields: null }),
        item({ kind: "map", revision_id: "rev-3", target_id: "node-1", target_title: "雾港地图", reason: null, changed_fields: null, change_note: "改了河道" }),
        item({ kind: "entity", revision_id: "rev-4", target_id: "entity-9", target_title: "旧灯塔", target_state: "removed", reason: "made_up_reason" }),
      ],
      next_cursor: null,
    })
    const wrapper = mountOverlay()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain("分钟前")
    expect(text).toContain("设定")
    expect(text).toContain("世界书")
    expect(text).toContain("地图")
    expect(text).toContain("手动编辑")
    expect(text).toContain("发布了这一版")
    expect(text).toContain("其他改动")
    expect(text).not.toContain("made_up_reason")
    expect(text).toContain("写到第 4 章时")
    expect(text).toContain("改动：作者秘密")
    expect(text).toContain("第 3 版")
    expect(text).toContain("已移除")
    expect(text).toContain("备注：改了河道")
    expect(wrapper.get(".world-change-history__meta [title]").attributes("title")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    wrapper.unmount()
  })

  it("按类型筛选重新查询；游标加载更多追加且保留已加载条目", async () => {
    api.world.listWorldChangeHistory
      .mockResolvedValueOnce({ items: [item()], next_cursor: "cursor-1" })
      .mockResolvedValueOnce({ items: [item({ kind: "page", revision_id: "rev-2", target_id: "page-1", target_title: "北港风物志", reason: "manual_publish", version_number: 2 })], next_cursor: null })
      .mockResolvedValueOnce({ items: [item({ revision_id: "rev-5", target_title: "第二条" })], next_cursor: null })
    const wrapper = mountOverlay()
    await flushPromises()
    expect(api.world.listWorldChangeHistory).toHaveBeenNthCalledWith(1, "p1", { kinds: undefined, cursor: undefined, limit: 30 })

    await wrapper.get("[data-action='change-history-more']").trigger("click")
    await flushPromises()
    expect(api.world.listWorldChangeHistory).toHaveBeenNthCalledWith(2, "p1", { kinds: undefined, cursor: "cursor-1", limit: 30 })
    expect(wrapper.text()).toContain("林澈")
    expect(wrapper.text()).toContain("北港风物志")

    await wrapper.get("[data-filter='page']").trigger("click")
    await flushPromises()
    expect(api.world.listWorldChangeHistory).toHaveBeenNthCalledWith(3, "p1", { kinds: ["page"], cursor: undefined, limit: 30 })
    expect(wrapper.text()).toContain("第二条")
    expect(wrapper.text()).not.toContain("林澈")
    wrapper.unmount()
  })

  it("筛选/条目/游标/滚动位置存入 worldSession，重挂载后恢复", async () => {
    api.world.listWorldChangeHistory.mockResolvedValue({ items: [item()], next_cursor: "cursor-x" })
    const first = mountOverlay()
    await flushPromises()
    await first.get("[data-filter='map']").trigger("click")
    await flushPromises()
    first.find(".world-change-history__list").element.scrollTop = 88
    await first.find(".world-change-history__list").trigger("scroll")
    expect(worldSession.changeHistory.filter).toBe("map")
    expect(worldSession.changeHistory.items.length).toBe(1)
    expect(worldSession.changeHistory.nextCursor).toBe("cursor-x")
    expect(worldSession.changeHistory.scrollTop).toBe(88)
    first.unmount()

    api.world.listWorldChangeHistory.mockClear()
    const second = mountOverlay()
    await flushPromises()
    // 恢复时不重复发查询，直接复用会话条目与滚动位置。
    expect(api.world.listWorldChangeHistory).not.toHaveBeenCalled()
    expect(second.text()).toContain("林澈")
    expect(second.find(".world-change-history__list").element.scrollTop).toBe(88)
    second.unmount()
  })

  it("迟到响应不覆盖新查询：旧筛选请求晚于新筛选返回被丢弃", async () => {
    let resolveSlow
    api.world.listWorldChangeHistory.mockImplementationOnce(() => new Promise((done) => { resolveSlow = done }))
      .mockResolvedValueOnce({ items: [item({ kind: "page", revision_id: "rev-2", target_title: "页面条目" })], next_cursor: null })
    const wrapper = mountOverlay()
    await flushPromises()
    await wrapper.get("[data-filter='page']").trigger("click")
    await flushPromises()
    resolveSlow({ items: [item({ revision_id: "rev-slow", target_title: "迟到的设定条目" })], next_cursor: null })
    await flushPromises()
    expect(wrapper.text()).toContain("页面条目")
    expect(wrapper.text()).not.toContain("迟到的设定条目")
    wrapper.unmount()
  })

  it("加载失败显示错误与重试，不拿旧列表冒充", async () => {
    api.world.listWorldChangeHistory.mockResolvedValueOnce({ items: [item()], next_cursor: null })
    const wrapper = mountOverlay()
    await flushPromises()
    api.world.listWorldChangeHistory.mockRejectedValueOnce(new Error("网络中断"))
    await wrapper.get("[data-filter='entity']").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("网络中断")
    expect(wrapper.get("[data-action='change-history-retry']")).toBeTruthy()
    expect(wrapper.text()).not.toContain("林澈")

    api.world.listWorldChangeHistory.mockResolvedValueOnce({ items: [item()], next_cursor: null })
    await wrapper.get("[data-action='change-history-retry']").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("林澈")
    wrapper.unmount()
  })

  it("空态显示还没有改动记录", async () => {
    api.world.listWorldChangeHistory.mockResolvedValueOnce({ items: [], next_cursor: null })
    const wrapper = mountOverlay()
    await flushPromises()
    expect(wrapper.text()).toContain("还没有改动记录")
    wrapper.unmount()
  })

  it("跳转：设定深链 open=history&revision_id；页面走 history=1；地图带 node_id/revision_id", async () => {
    api.world.listWorldChangeHistory.mockResolvedValueOnce({
      items: [
        item(),
        item({ kind: "page", revision_id: "rev-2", target_id: "page-1", version_number: 7 }),
        item({ kind: "map", revision_id: "rev-3", target_id: "node-1" }),
      ],
      next_cursor: null,
    })
    const wrapper = mountOverlay()
    await flushPromises()
    await wrapper.get("[data-jump='entity:rev-1']").trigger("click")
    expect(navigate).toHaveBeenCalledWith("world", "bible", true, new URLSearchParams({ entity_id: "entity-1", open: "history", revision_id: "rev-1" }))
    await wrapper.get("[data-jump='page:rev-2']").trigger("click")
    expect(navigate).toHaveBeenCalledWith("world", "bible", true, new URLSearchParams({ page_id: "page-1", history: "1", history_version: "7" }))
    await wrapper.get("[data-jump='map:rev-3']").trigger("click")
    expect(navigate).toHaveBeenCalledWith("map", null, true, new URLSearchParams({ node_id: "node-1", revision_id: "rev-3" }))
    wrapper.unmount()
  })

  it("关闭写入会话 open=false 并通知父级", async () => {
    api.world.listWorldChangeHistory.mockResolvedValueOnce({ items: [item()], next_cursor: null })
    const wrapper = mountOverlay()
    await flushPromises()
    await wrapper.get("[data-action='change-history-close']").trigger("click")
    expect(worldSession.changeHistory.open).toBe(false)
    expect(wrapper.emitted("close")).toHaveLength(1)
    wrapper.unmount()
  })
})
