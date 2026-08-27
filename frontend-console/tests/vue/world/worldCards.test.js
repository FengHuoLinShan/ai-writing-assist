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
    expect(cards[1]).toMatchObject({ kind: "page", draftId: "d1", title: "规则工作稿", state: "working" })
    expect(cards[2]).toMatchObject({ kind: "entity", id: "e1", typeKey: "location" })
  })

  it("uses one bounded query for URL-backed kind, type, and text filters", () => {
    const filters = worldCardFiltersFromQuery(new URLSearchParams("kind=entity&type=location&q=%20%E9%9B%BE%E6%B8%AF%20"))
    expect(filters).toEqual({ kind: "entity", type: "location", q: "雾港" })
    expect(worldCardQuery(filters).toString()).toBe("q=%E9%9B%BE%E6%B8%AF&kind=entity&type=location")
    expect(buildWorldCards({
      pages: [{ id: "p1", title: "雾港史", page_type: "location", status: "canonical" }],
      entities: [
        { id: "e1", name: "雾港", entity_type: "location", summary: "港口" },
        { id: "e2", name: "王庭", entity_type: "faction", summary: "组织" },
      ],
      filters,
    }).map((card) => card.key)).toEqual(["entity:e1"])
    expect(worldCardFiltersFromQuery(new URLSearchParams("type=custom"))).toEqual({
      kind: "all", type: "", q: "",
    })
  })
})
