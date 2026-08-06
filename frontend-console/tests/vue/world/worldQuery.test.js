/**
 * worldQuery 测试 — 筛选与 URL query 编解码（对应 vanilla worldView.js 同名方法）。
 */
import { describe, it, expect } from "vitest"
import {
  WORLD_FILTER_DEFAULTS,
  WORLD_ALIAS_FILTER_DEFAULTS,
  WORLD_ALIAS_QUERY_KEYS,
  WORLD_CANDIDATE_FILTER_DEFAULTS,
  WORLD_OBJECT_QUERY_KEYS,
  candidateFiltersFromQuery,
  candidateQueryFromState,
  filtersEqual,
  hasAdvancedObjectFilters,
  normalizeReviewSubView,
  objectFiltersFromQuery,
  objectQueryFromState,
  queryPageSkip,
  reviewFiltersFromQuery,
  reviewQueryFromState,
} from "../../../vue/views/world/logic/worldQuery.js"

describe("normalizeReviewSubView", () => {
  it("candidates legacy 映射为 review-objects", () => {
    expect(normalizeReviewSubView("candidates")).toBe("review-objects")
  })
  it("review 三兄弟原样保留，其他返回空串", () => {
    expect(normalizeReviewSubView("review-aliases")).toBe("review-aliases")
    expect(normalizeReviewSubView("review-relations")).toBe("review-relations")
    expect(normalizeReviewSubView("objects")).toBe("")
    expect(normalizeReviewSubView("bible")).toBe("")
    expect(normalizeReviewSubView("")).toBe("")
  })
})

describe("objectFiltersFromQuery", () => {
  it("空 query 回落默认（display_state=active, limit=20, skip=0）", () => {
    const filters = objectFiltersFromQuery(new URLSearchParams())
    expect(filters).toEqual({ ...WORLD_FILTER_DEFAULTS, skip: 0 })
  })
  it("page 解码为 skip（第 3 页 × 20 = skip 40）", () => {
    const filters = objectFiltersFromQuery(new URLSearchParams("page=3"))
    expect(filters.skip).toBe(40)
  })
  it("legacy status=canonical 映射 display_state=active（无 display_state 时）", () => {
    const filters = objectFiltersFromQuery(new URLSearchParams("status=canonical"))
    expect(filters.display_state).toBe("active")
  })
  it("legacy status=merged 映射 archived；未知值映射 review", () => {
    expect(objectFiltersFromQuery(new URLSearchParams("status=merged")).display_state).toBe("archived")
    expect(objectFiltersFromQuery(new URLSearchParams("status=candidate")).display_state).toBe("review")
  })
  it("display_state 显式存在时 legacy status 不生效", () => {
    const filters = objectFiltersFromQuery(new URLSearchParams("status=merged&display_state=review"))
    expect(filters.display_state).toBe("review")
  })
})

describe("reviewFiltersFromQuery", () => {
  it("page_size 只认 50，其他值回落 20", () => {
    const q50 = reviewFiltersFromQuery(WORLD_ALIAS_FILTER_DEFAULTS, WORLD_ALIAS_QUERY_KEYS, new URLSearchParams("page_size=50"))
    expect(q50.limit).toBe(50)
    const q30 = reviewFiltersFromQuery(WORLD_ALIAS_FILTER_DEFAULTS, WORLD_ALIAS_QUERY_KEYS, new URLSearchParams("page_size=30"))
    expect(q30.limit).toBe(20)
  })
  it("skip 按实际 limit 计算（page=2 & page_size=50 → skip 50）", () => {
    const filters = reviewFiltersFromQuery(WORLD_ALIAS_FILTER_DEFAULTS, WORLD_ALIAS_QUERY_KEYS, new URLSearchParams("page=2&page_size=50"))
    expect(filters.skip).toBe(50)
  })
})

describe("filtersEqual", () => {
  it("skip/limit 数字比较，其余字符串比较", () => {
    const a = { ...WORLD_FILTER_DEFAULTS }
    const b = { ...WORLD_FILTER_DEFAULTS, skip: 0, q: "" }
    expect(filtersEqual(a, b, WORLD_OBJECT_QUERY_KEYS)).toBe(true)
    expect(filtersEqual(a, { ...b, skip: 20 }, WORLD_OBJECT_QUERY_KEYS)).toBe(false)
    expect(filtersEqual(a, { ...b, q: "港" }, WORLD_OBJECT_QUERY_KEYS)).toBe(false)
  })
})

describe("hasAdvancedObjectFilters", () => {
  it("source/workflow_id/needs_review/auto_ingested 任一非空即真", () => {
    expect(hasAdvancedObjectFilters({ ...WORLD_FILTER_DEFAULTS })).toBe(false)
    expect(hasAdvancedObjectFilters({ ...WORLD_FILTER_DEFAULTS, workflow_id: "wf-1" })).toBe(true)
  })
})

describe("query builders（编码与 vanilla 对齐）", () => {
  it("objectQueryFromState：空值不写、page>1 才写、card/mode 标记", () => {
    const query = objectQueryFromState({ ...WORLD_FILTER_DEFAULTS, q: "港", skip: 40 }, "card", "hot")
    expect(query.get("q")).toBe("港")
    expect(query.get("page")).toBe("3")
    expect(query.get("view")).toBe("card")
    expect(query.get("mode")).toBe("hot")
    expect(query.has("source")).toBe(false)

    const first = objectQueryFromState({ ...WORLD_FILTER_DEFAULTS }, "table", "normal")
    expect(first.has("page")).toBe(false)
    expect(first.get("view")).toBe("table")
  })
  it("candidateQueryFromState / reviewQueryFromState：page_size=50 回写", () => {
    const cq = candidateQueryFromState({ ...WORLD_CANDIDATE_FILTER_DEFAULTS, skip: 0 })
    expect(cq.has("page")).toBe(false)
    const rq = reviewQueryFromState({ ...WORLD_ALIAS_FILTER_DEFAULTS, limit: 50, skip: 50 }, WORLD_ALIAS_QUERY_KEYS)
    expect(rq.get("page")).toBe("2")
    expect(rq.get("page_size")).toBe("50")
  })
  it("object 编解码往返一致", () => {
    const filters = { ...WORLD_FILTER_DEFAULTS, entity_type: "location", q: "港", skip: 20 }
    const roundTrip = objectFiltersFromQuery(objectQueryFromState(filters, "table", "hot"))
    expect(roundTrip.entity_type).toBe("location")
    expect(roundTrip.q).toBe("港")
    expect(roundTrip.skip).toBe(20)
  })
})

describe("queryPageSkip", () => {
  it("非法 page 回落第 1 页", () => {
    expect(queryPageSkip(new URLSearchParams("page=abc"), 20)).toBe(0)
    expect(queryPageSkip(new URLSearchParams("page=-2"), 20)).toBe(0)
  })
})
