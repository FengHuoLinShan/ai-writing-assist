/**
 * outlineStructure 测试 — codec 纯函数：filter↔URL 编解码、status options。
 */
import { describe, it, expect } from "vitest"
import {
  STRUCTURE_FILTER_DEFAULTS,
  structureFiltersFromQuery,
  structureQueryFromState,
  structureFilterParams,
  structureStatusOptions,
  loadAllOutlineItems,
} from "../../../vue/views/outline/logic/outlineStructure.js"

describe("structureFiltersFromQuery", () => {
  it("空 query 回落默认（skip=0, limit=50）", () => {
    const filters = structureFiltersFromQuery("threads", new URLSearchParams())
    expect(filters).toEqual({ ...STRUCTURE_FILTER_DEFAULTS, skip: 0 })
  })
  it("page 解码为 skip（第 3 页 × 50 = skip 100）", () => {
    const filters = structureFiltersFromQuery("threads", new URLSearchParams("page=3"))
    expect(filters.skip).toBe(100)
  })
  it("读取已知 key，忽略未知 key", () => {
    const filters = structureFiltersFromQuery("threads", new URLSearchParams("status=draft&source=manual&unknown=xxx"))
    expect(filters.status).toBe("draft")
    expect(filters.source).toBe("manual")
    expect(filters.unknown).toBeUndefined()
  })
  it("非 threads/arcs/foreshadowing/reveals 子标签返回默认", () => {
    const filters = structureFiltersFromQuery("scenes", new URLSearchParams("status=draft"))
    expect(filters).toEqual({ ...STRUCTURE_FILTER_DEFAULTS, skip: 0 })
  })
  it("workflow_id 和 needs_review 读取", () => {
    const filters = structureFiltersFromQuery("threads", new URLSearchParams("workflow_id=wf-1&needs_review=true"))
    expect(filters.workflow_id).toBe("wf-1")
    expect(filters.needs_review).toBe("true")
  })
})

describe("structureQueryFromState", () => {
  it("非 threads/arcs/foreshadowing/reveals 返回空 query", () => {
    const q = structureQueryFromState("scenes", STRUCTURE_FILTER_DEFAULTS)
    expect(q.toString()).toBe("")
  })
  it("空值不写入，page=1 不写", () => {
    const q = structureQueryFromState("threads", { ...STRUCTURE_FILTER_DEFAULTS, skip: 0 })
    expect(q.toString()).toBe("")
  })
  it("page > 1 才写入 page 参数", () => {
    const q = structureQueryFromState("threads", { ...STRUCTURE_FILTER_DEFAULTS, skip: 50 })
    expect(q.get("page")).toBe("2")
  })
  it("status/source/workflow_id/needs_review 写入", () => {
    const q = structureQueryFromState("threads", {
      ...STRUCTURE_FILTER_DEFAULTS,
      status: "draft",
      source: "manual",
      workflow_id: "wf-1",
      needs_review: "true",
      skip: 0,
    })
    expect(q.get("status")).toBe("draft")
    expect(q.get("source")).toBe("manual")
    expect(q.get("workflow_id")).toBe("wf-1")
    expect(q.get("needs_review")).toBe("true")
    expect(q.has("page")).toBe(false)
  })
  it("往返一致：一页 + 非空筛选", () => {
    const original = { ...STRUCTURE_FILTER_DEFAULTS, status: "canonical", source: "deep_import", skip: 0 }
    const roundTrip = structureFiltersFromQuery("arcs", structureQueryFromState("arcs", original))
    expect(roundTrip.status).toBe("canonical")
    expect(roundTrip.source).toBe("deep_import")
    expect(roundTrip.skip).toBe(0)
  })
  it("往返一致：带分页", () => {
    const original = { ...STRUCTURE_FILTER_DEFAULTS, status: "draft", skip: 100 }
    const roundTrip = structureFiltersFromQuery("threads", structureQueryFromState("threads", original))
    expect(roundTrip.status).toBe("draft")
    expect(roundTrip.skip).toBe(100)
  })
})

describe("structureFilterParams", () => {
  it("空筛选返回只有 skip/limit", () => {
    const p = structureFilterParams("threads", { ...STRUCTURE_FILTER_DEFAULTS, skip: 20 })
    expect(p).toEqual({ skip: 20, limit: 50 })
  })
  it("非 structure 子标签返回空对象", () => {
    const p = structureFilterParams("scenes", STRUCTURE_FILTER_DEFAULTS)
    expect(p).toEqual({})
  })
  it("status/source/workflow_id 条件写入", () => {
    const p = structureFilterParams("threads", {
      ...STRUCTURE_FILTER_DEFAULTS,
      status: "draft",
      source: "manual",
      workflow_id: "wf-1",
    })
    expect(p.status).toBe("draft")
    expect(p.source).toBe("manual")
    expect(p.workflow_id).toBe("wf-1")
  })
  it("needs_review 字符串转 boolean", () => {
    const pTrue = structureFilterParams("threads", { ...STRUCTURE_FILTER_DEFAULTS, needs_review: "true" })
    expect(pTrue.needs_review).toBe(true)
    const pFalse = structureFilterParams("threads", { ...STRUCTURE_FILTER_DEFAULTS, needs_review: "false" })
    expect(pFalse.needs_review).toBe(false)
  })
})

describe("structureStatusOptions", () => {
  it("threads/arcs 返回通用状态", () => {
    const opts = structureStatusOptions("threads")
    expect(opts).toEqual([
      ["canonical", "已采用"],
      ["draft", "工作稿"],
      ["candidate", "待处理"],
      ["deprecated", "历史"],
    ])
  })
  it("foreshadowing 返回伏笔专用状态", () => {
    const opts = structureStatusOptions("foreshadowing")
    expect(opts.some(([v]) => v === "planted")).toBe(true)
    expect(opts.some(([v]) => v === "triggered")).toBe(true)
  })
  it("reveals 返回揭示专用状态", () => {
    const opts = structureStatusOptions("reveals")
    expect(opts.some(([v]) => v === "planned")).toBe(true)
    expect(opts.some(([v]) => v === "revealed")).toBe(true)
  })
})

describe("loadAllOutlineItems", () => {
  it("单页结果直接返回", async () => {
    const fetchPage = async () => ({ items: [{ id: "a" }, { id: "b" }], total: 2 })
    const result = await loadAllOutlineItems(fetchPage)
    expect(result.items).toHaveLength(2)
    expect(result.total).toBe(2)
  })
  it("多页翻页", async () => {
    let callCount = 0
    const fetchPage = async (params) => {
      callCount++
      if (callCount === 1) return { items: Array.from({ length: 50 }, (_, i) => ({ id: `p1-${i}` })), total: 120 }
      if (callCount === 2) return { items: Array.from({ length: 50 }, (_, i) => ({ id: `p2-${i}` })), total: 120 }
      return { items: Array.from({ length: 20 }, (_, i) => ({ id: `p3-${i}` })), total: 120 }
    }
    const result = await loadAllOutlineItems(fetchPage)
    expect(callCount).toBe(3)
    expect(result.items).toHaveLength(120)
    expect(result.total).toBe(120)
  })
  it("无 total 时按 items 长度终止（首页即完）", async () => {
    let callCount = 0
    const fetchPage = async () => {
      callCount++
      return { items: Array.from({ length: 20 }, (_, i) => ({ id: `${callCount}-${i}` })) }
    }
    const result = await loadAllOutlineItems(fetchPage, {})
    expect(callCount).toBe(1)
    expect(result.items).toHaveLength(20)
  })
})
