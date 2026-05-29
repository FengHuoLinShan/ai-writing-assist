import { describe, it, expect, vi, beforeEach } from "vitest"
import memoryView from "../views/memoryView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("memoryView", () => {
  describe("onEnter", () => {
    it("加载记录和提案", async () => {
      state.currentProjectId = "p1"
      api.memory.listRecords.mockResolvedValue({ items: [{ id: "r1", title: "记忆1" }] })
      api.memory.listProposals.mockResolvedValue({ items: [{ id: "pr1", summary: "提案1" }] })

      await memoryView.onEnter()

      expect(memoryView._records).toHaveLength(1)
      expect(memoryView._proposals).toHaveLength(1)
    })

    it("无项目时不加载", async () => {
      state.currentProjectId = null
      await memoryView.onEnter()
      expect(memoryView._records).toEqual([])
      expect(memoryView._proposals).toEqual([])
    })
  })

  describe("render", () => {
    it("records 子视图包含 subnav", async () => {
      state.currentSubView = "records"
      const html = await memoryView.render()
      expect(html).toContain("记忆记录")
      expect(html).toContain("更新候选")
    })
  })

  describe("confirmProposal", () => {
    it("调用 API 并导航", async () => {
      state.currentProjectId = "p1"
      api.memory.confirmProposal.mockResolvedValue({})

      await memoryView.confirmProposal("pr1")

      expect(api.memory.confirmProposal).toHaveBeenCalledWith("p1", "pr1", {})
      expect(router.navigate).toHaveBeenCalledWith("memory", "proposals")
    })
  })

  describe("rejectProposal", () => {
    it("调用 confirmAction 确认后拒绝", async () => {
      state.currentProjectId = "p1"
      api.memory.rejectProposal.mockResolvedValue({})

      memoryView.rejectProposal("pr1")

      expect(globalThis.confirmAction).toHaveBeenCalled()
      const [, handler] = vi.mocked(globalThis.confirmAction).mock.calls[0]
      await handler()
      expect(api.memory.rejectProposal).toHaveBeenCalledWith("p1", "pr1", "user")
    })
  })
})
