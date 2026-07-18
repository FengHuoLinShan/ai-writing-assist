/**
 * 检索 payload / 结果处理纯逻辑测试 — 对应原 ragView.test.js 的相关用例。
 */
import { describe, it, expect } from "vitest"
import {
  advancedFilterSummary,
  buildEvidencePayload,
  highlightParts,
  hitKindLabel,
  normalizeEvidenceHit,
  resultCountLabel,
  searchErrorReason,
} from "../../../vue/views/rag/logic/searchPayload.js"

function makeForm(overrides = {}) {
  return {
    query: "旧塔",
    searchKind: "smart",
    contentMode: "canonical",
    visibilityMode: "author",
    chapterFrom: "",
    chapterTo: "",
    cutoffChapter: "",
    cutoffSceneId: "",
    cutoffOffset: "",
    characterId: "",
    scopes: ["manuscript"],
    includePending: false,
    ...overrides,
  }
}

describe("buildEvidencePayload", () => {
  it("默认作者视角产出完整 payload", () => {
    const { payload, error } = buildEvidencePayload(makeForm(), "p1")
    expect(error).toBeUndefined()
    expect(payload).toMatchObject({
      novel_id: "p1",
      query: "旧塔",
      search_kind: "smart",
      content_mode: "canonical",
      scopes: ["manuscript"],
      include_pending_objects: false,
      top_k: 100,
    })
    expect(payload.visibility).toEqual({
      mode: "author",
      cutoff_chapter: null,
      cutoff_scene_id: null,
      cutoff_offset: null,
      character_id: null,
    })
  })

  it("读者/角色视角缺截止章被拒绝", () => {
    expect(buildEvidencePayload(makeForm({ visibilityMode: "reader" }), "p1").error)
      .toBe("读者/角色视角必须设置可见截止章")
    expect(buildEvidencePayload(makeForm({ visibilityMode: "character" }), "p1").error)
      .toBe("读者/角色视角必须设置可见截止章")
  })

  it("角色视角缺人物被拒绝", () => {
    const { error } = buildEvidencePayload(makeForm({ visibilityMode: "character", cutoffChapter: "4" }), "p1")
    expect(error).toBe("角色视角必须选择人物")
  })

  it("数值字段解析与非法回退", () => {
    const { payload } = buildEvidencePayload(makeForm({
      chapterFrom: "2",
      chapterTo: "x",
      cutoffOffset: "120",
      cutoffChapter: "4",
    }), "p1")
    expect(payload.chapter_from).toBe(2)
    expect(payload.chapter_to).toBeNull()
    expect(payload.visibility.cutoff_offset).toBe(120)
    expect(payload.visibility.cutoff_chapter).toBe(4)
  })

  it("空 scopes 回退正文", () => {
    expect(buildEvidencePayload(makeForm({ scopes: [] }), "p1").payload.scopes).toEqual(["manuscript"])
  })
})

describe("normalizeEvidenceHit", () => {
  it("字段回退与类型归一", () => {
    expect(normalizeEvidenceHit({ source_type: "chapter_text", chapter_index: 3 })).toMatchObject({
      kind: "manuscript",
      title: "第 3 章",
      match_count: 1,
      match_basis: "chunk",
      index_fresh: true,
    })
    expect(normalizeEvidenceHit({ snippet: "x", match_count: 5, match_basis: "occurrence" })).toMatchObject({
      match_count: 5,
      match_basis: "occurrence",
    })
    expect(normalizeEvidenceHit({ index_fresh: false }).index_fresh).toBe(false)
  })
})

describe("advancedFilterSummary", () => {
  it("章节区间 / 视角 / 截止点 / 范围摘要", () => {
    const summary = advancedFilterSummary({
      chapterFrom: 2,
      chapterTo: 5,
      visibilityMode: "character",
      characterId: "c1",
      cutoffChapter: 4,
      scopes: ["manuscript", "world"],
      includePending: true,
    }, {
      characters: [{ id: "c1", name: "林晚" }],
      scenes: [],
    })
    expect(summary).toContain("第 2–5 章")
    expect(summary).toContain("角色视角：林晚")
    expect(summary).toContain("可见至第 4 章")
    expect(summary).toContain("范围：正文、世界对象")
    expect(summary).toContain("含待处理对象")
  })

  it("默认作者视角且无筛选时为空", () => {
    expect(advancedFilterSummary({ visibilityMode: "author", scopes: ["manuscript"] })).toEqual([])
  })
})

describe("searchErrorReason", () => {
  it("按错误类型给出文案", () => {
    expect(searchErrorReason(new Error("证据检索接口不可用"))).toContain("未经校验")
    expect(searchErrorReason(new Error("请求超时"))).toContain("等待时间过长")
    expect(searchErrorReason(Object.assign(new Error("boom"), { status: 503 }))).toContain("暂时不可用")
    expect(searchErrorReason(new Error("other"))).toContain("未能完成")
  })
})

describe("highlightParts", () => {
  it("命中时拆分三段，未命中原文返回", () => {
    expect(highlightParts("旧塔的铜铃在夜里响起", "铜铃")).toEqual({
      before: "旧塔的",
      mark: "铜铃",
      after: "在夜里响起",
    })
    expect(highlightParts("abcdef", "xyz").mark).toBe("")
    expect(highlightParts("abcdef", "").mark).toBe("")
  })

  it("超长截断 500 字", () => {
    const long = "x".repeat(600)
    expect(highlightParts(long, "").before.length).toBe(500)
  })
})

describe("hitKindLabel / resultCountLabel", () => {
  it("类型标签", () => {
    expect(hitKindLabel("manuscript")).toBe("正文")
    expect(hitKindLabel("custom")).toBe("custom")
  })

  it("全章节结果与混合结果的计数文案", () => {
    const chapterHits = [{ chapter_index: 1 }, { chapter_index: 2 }]
    expect(resultCountLabel(58, chapterHits, 20)).toBe("找到 58 个章节结果 · 已显示 20")
    expect(resultCountLabel(3, [{ chapter_index: 1 }, {}], 2)).toBe("找到 3 条结果 · 已显示 2")
  })
})
