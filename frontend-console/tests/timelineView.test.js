import { describe, it, expect, vi, beforeEach } from "vitest"
import timelineView from "../views/timelineView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("timelineView", () => {
  describe("onEnter", () => {
    it("加载事件列表", async () => {
      state.currentProjectId = "p1"
      api.timeline.listEvents.mockResolvedValue({ items: [{ id: "e1", title: "事件1" }] })

      await timelineView.onEnter()

      expect(timelineView._events).toHaveLength(1)
    })
  })

  describe("render", () => {
    it("无项目时显示提示", async () => {
      state.currentProjectId = null
      const html = await timelineView.render()
      expect(html).toContain("请先选择项目")
    })

    it("有项目时包含新建按钮", async () => {
      state.currentProjectId = "p1"
      const html = await timelineView.render()
      expect(html).toContain("data-action")
    })
  })

  describe("showCreateForm", () => {
    it("调用 showModal", () => {
      timelineView.showCreateForm()
      expect(globalThis.showModal).toHaveBeenCalled()
      const title = vi.mocked(globalThis.showModal).mock.calls[0][0]
      expect(title).toBe("新建时间线事件")
    })
  })

  describe("deleteEvent", () => {
    it("确认后调用 API", async () => {
      state.currentProjectId = "p1"
      api.timeline.updateEvent.mockResolvedValue({})

      timelineView.deleteEvent("e1")
      const [, handler] = vi.mocked(globalThis.confirmAction).mock.calls[0]
      await handler()

      expect(api.timeline.updateEvent).toHaveBeenCalledWith("p1", "e1", { status: "deprecated" })
    })
  })
})
