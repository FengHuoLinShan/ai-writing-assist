/**
 * worldSession 测试 — 进入协调（完整进入重置 vs query-only 保留）与筛选面板持久化。
 */
import { describe, it, expect, beforeEach } from "vitest"
import {
  loadFilterPanelState,
  markWorldLeft,
  reconcileWorldEntry,
  resetWorldSession,
  saveFilterPanelState,
  worldSession,
} from "../../../vue/views/world/worldSession.js"

beforeEach(() => {
  localStorage.clear()
  resetWorldSession()
})

describe("reconcileWorldEntry", () => {
  it("首次进入按完整进入处理", () => {
    expect(reconcileWorldEntry("p1", "objects")).toBe(true)
  })

  it("query-only 重挂载（同项目同子标签）保留草稿与批量选择", () => {
    reconcileWorldEntry("p1", "review-aliases")
    worldSession.aliasReviewDrafts = { "e1::别名": { action: "accept" } }
    worldSession.bulkSelections = { "world-aliases": new Set(["k1"]) }

    expect(reconcileWorldEntry("p1", "review-aliases")).toBe(false)
    expect(worldSession.aliasReviewDrafts["e1::别名"]).toEqual({ action: "accept" })
    expect(worldSession.bulkSelections["world-aliases"].has("k1")).toBe(true)
  })

  it("子标签切换按完整进入重置", () => {
    reconcileWorldEntry("p1", "objects")
    worldSession.bulkSelections = { "world-objects": new Set(["e1"]) }
    expect(reconcileWorldEntry("p1", "review-objects")).toBe(true)
    expect(worldSession.bulkSelections).toEqual({})
  })

  it("项目切换按完整进入重置", () => {
    reconcileWorldEntry("p1", "objects")
    worldSession.relationReviewDrafts = { g1: { action: "merge" } }
    worldSession.reviewReceipt = { title: "旧项目结果" }
    worldSession.bible = { activePageId: "page-p1", activeDraftId: "draft-p1", editorBaseline: { title: "旧项目" }, editorBaselineKey: "page-p1" }
    expect(reconcileWorldEntry("p2", "objects")).toBe(true)
    expect(worldSession.relationReviewDrafts).toEqual({})
    expect(worldSession.reviewReceipt).toBeNull()
    expect(worldSession.bible).toEqual({ activePageId: null, activeDraftId: null, editorBaseline: null, editorBaselineKey: null })
  })

  it("同项目重新进入保留 bible 上次页面", () => {
    reconcileWorldEntry("p1", "bible")
    worldSession.bible.activePageId = "page-1"
    markWorldLeft()
    reconcileWorldEntry("p1", "bible")
    expect(worldSession.bible.activePageId).toBe("page-1")
  })

  it("markWorldLeft 后再次进入按完整进入重置（vanilla onEnter 语义）", () => {
    reconcileWorldEntry("p1", "objects")
    worldSession.aliasReviewErrors = { k1: "冲突" }
    markWorldLeft()
    expect(reconcileWorldEntry("p1", "objects")).toBe(true)
    expect(worldSession.aliasReviewErrors).toEqual({})
  })

  it("relations/aliases 分页会话在完整进入时也不重置（vanilla 模块单例语义）", () => {
    reconcileWorldEntry("p1", "relations")
    worldSession.relationListFilters = { skip: 40, limit: 20 }
    markWorldLeft()
    reconcileWorldEntry("p1", "relations")
    expect(worldSession.relationListFilters.skip).toBe(40)
  })
})

describe("筛选面板持久化", () => {
  it("保存后按项目键恢复，非法 JSON 清除", () => {
    loadFilterPanelState("p1")
    worldSession.filterPanelsOpen.objects = true
    saveFilterPanelState("p1")

    worldSession.filterPanelsOpen = { objects: false, "review-objects": true, "review-aliases": false, "review-relations": false }
    loadFilterPanelState("p1")
    expect(worldSession.filterPanelsOpen.objects).toBe(true)
    expect(worldSession.filterPanelsOpen["review-objects"]).toBe(false)

    localStorage.setItem("novel_world_filter_panels:p1", "{bad json")
    loadFilterPanelState("p1")
    expect(localStorage.getItem("novel_world_filter_panels:p1")).toBeNull()
    expect(worldSession.filterPanelsOpen.objects).toBe(false)
  })

  it("无项目时不读写", () => {
    expect(() => saveFilterPanelState(null)).not.toThrow()
    loadFilterPanelState(null)
    expect(worldSession.filterPanelsOpen.objects).toBe(false)
  })
})
