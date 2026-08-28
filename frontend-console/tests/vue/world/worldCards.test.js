import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

import {
  buildWorldCards,
  worldCardFiltersFromQuery,
  worldCardQuery,
} from "../../../vue/views/world/bible/worldCards.js"

describe("unified world cards", () => {
  it("keeps Page and Entity lifecycles tagged while restoring drafts", () => {
    const cards = buildWorldCards({
      pages: [{ id: "p1", title: "旧标题", page_type: "rule", status: "canonical", free_text: "旧正文" }],
      drafts: [
        { id: "d1", page_id: "p1", title: "规则工作稿", page_type: "rule", free_text: "未发布修改", updated_at: "2026-08-26T00:00:00Z" },
        { id: "d2", page_id: null, title: "空白资料", page_type: "custom", free_text: "待整理", updated_at: "2026-08-27T00:00:00Z" },
      ],
      entities: [{ id: "e1", name: "雾港", entity_type: "location", summary: "北境港口", display_state: "active" }],
      filters: { kind: "all" },
    })

    expect(cards.map((card) => card.key)).toEqual(["draft:d2", "page:p1", "entity:e1"])
    expect(cards[1]).toMatchObject({ kind: "page", draftId: "d1", title: "规则工作稿", state: "working", stateLabel: "工作稿" })
    expect(cards[2]).toMatchObject({ kind: "entity", id: "e1", typeKey: "location", stateLabel: "已采用" })
  })

  it("uses one bounded query for URL-backed kind, type, and text filters", () => {
    const filters = worldCardFiltersFromQuery(new URLSearchParams("kind=entity&type=location&q=%20%E9%9B%BE%E6%B8%AF%20"))
    expect(filters).toMatchObject({ kind: "entity", type: "location", q: "雾港", state: "", layout: "cards" })
    expect(worldCardQuery(filters).toString()).toBe("q=%E9%9B%BE%E6%B8%AF&kind=entity&type=location")
    expect(buildWorldCards({
      pages: [{ id: "p1", title: "雾港史", page_type: "location", status: "canonical" }],
      entities: [
        { id: "e1", name: "雾港", entity_type: "location", summary: "港口" },
      ],
      filters,
    }).map((card) => card.key)).toEqual(["entity:e1"])
    expect(worldCardFiltersFromQuery(new URLSearchParams("type=custom"))).toMatchObject({
      kind: "all", type: "", q: "", state: "", layout: "cards",
    })
  })

  it("在 URL 中恢复工作稿目录与列表视图", () => {
    const filters = worldCardFiltersFromQuery(new URLSearchParams("state=working&layout=list"))
    expect(filters).toMatchObject({ state: "working", layout: "list" })
    expect(worldCardQuery(filters).toString()).toContain("state=working&layout=list")
    expect(buildWorldCards({
      pages: [{ id: "p1", title: "已发布", status: "canonical" }],
      drafts: [{ id: "d1", title: "工作稿", status: "draft" }],
      entities: [{ id: "e1", name: "人物", display_state: "active" }],
      filters,
    }).map((card) => card.key)).toEqual(["draft:d1"])
  })

  it("保留服务端按别名命中的对象，资料页则搜索完整内容", () => {
    const longPrefix = "无".repeat(260)
    const cards = buildWorldCards({
      pages: [
        { id: "p1", title: "港口档案", status: "canonical", free_text: longPrefix, sections_json: [{ title: "隐藏章节", body_markdown: "钟楼密约" }] },
        { id: "p2", title: "王庭档案", status: "canonical", free_text: "无关内容" },
      ],
      // “旧港”可能只命中服务端别名，不一定出现在返回摘要里。
      entities: [{ id: "e1", name: "沉钟港", entity_type: "location", summary: "北境港口", display_state: "active" }],
      filters: { kind: "all", q: "旧港" },
    })
    expect(cards.map((card) => card.key)).toEqual(["entity:e1"])

    expect(buildWorldCards({
      pages: [{ id: "p1", title: "港口档案", status: "canonical", free_text: longPrefix, sections_json: [{ title: "隐藏章节", body_markdown: "钟楼密约" }] }],
      filters: { kind: "page", q: "钟楼密约" },
    }).map((card) => card.key)).toEqual(["page:p1"])
  })

  it("按页面真实状态显示工作稿、待处理和已采用", () => {
    const cards = buildWorldCards({
      pages: [
        { id: "draft-page", title: "旧式草稿页", status: "draft" },
        { id: "candidate-page", title: "待处理页", status: "candidate" },
        { id: "active-page", title: "已采用页", status: "canonical" },
      ],
    })

    expect(Object.fromEntries(cards.map((card) => [card.id, card.stateLabel]))).toEqual({
      "draft-page": "工作稿",
      "candidate-page": "待处理",
      "active-page": "已采用",
    })
  })

  it("390px 下筛选与空态操作单列展开且保持 44px 触控高度", () => {
    const styles = readFileSync(resolve(import.meta.dirname, "../../../styles.css"), "utf8")
    expect(styles).toMatch(/@media \(max-width: 390px\)[\s\S]*\.world-card-filters\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s)
    expect(styles).toMatch(/@media \(max-width: 390px\)[\s\S]*\.world-card-empty-actions \.btn\s*\{[^}]*min-height:\s*44px/s)
  })
})
