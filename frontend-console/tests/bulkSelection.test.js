import { describe, expect, it } from "vitest"
import {
  bulkResultMessage,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  runBulkAction,
  selectedItemsFrom,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"

describe("bulkSelection helper", () => {
  it("tracks single and page selection per scope", () => {
    const view = {}
    toggleBulkSelection(view, "world", "e1", true)
    toggleAllBulkSelection(view, "world", ["e2", "e3"], true)
    toggleBulkSelection(view, "world", "e2", false)

    expect(Array.from(getBulkSelection(view, "world"))).toEqual(["e1", "e3"])
    expect(getBulkSelection(view, "outline").size).toBe(0)
  })

  it("reconciles selected ids to the visible page", () => {
    const view = {}
    toggleAllBulkSelection(view, "world", ["e1", "e2", "e3"], true)

    reconcileBulkSelection(view, "world", ["e2", "e4"])

    expect(Array.from(getBulkSelection(view, "world"))).toEqual(["e2"])
  })

  it("filters selected items by ids", () => {
    const items = [{ id: "a", name: "A" }, { id: "b", name: "B" }]
    const selected = new Set(["b"])

    expect(selectedItemsFrom(items, selected)).toEqual([{ id: "b", name: "B" }])
  })

  it("runs bulk actions with success and failed summaries", async () => {
    const items = [{ id: "ok", name: "成功" }, { id: "bad", name: "失败" }]
    const result = await runBulkAction(items, async (item) => {
      if (item.id === "bad") throw new Error("no")
    })

    expect(result.success).toHaveLength(1)
    expect(result.failed).toHaveLength(1)
    expect(bulkResultMessage(result, "删除")).toContain("失败")
    expect(bulkResultMessage(result, "删除")).toContain("失败")
  })

  it("clears a scope", () => {
    const view = {}
    toggleBulkSelection(view, "world", "e1", true)
    clearBulkSelection(view, "world")

    expect(getBulkSelection(view, "world").size).toBe(0)
  })
})
