/**
 * 检索路由状态纯逻辑测试 — 对应原 ragView.test.js 的路由解析用例。
 */
import { describe, it, expect } from "vitest"
import { buildRouteQuery, parseRouteQuery } from "../../../vue/views/rag/logic/routeState.js"

describe("parseRouteQuery", () => {
  it("空 query 返回默认值与空 signature", () => {
    const state = parseRouteQuery(new URLSearchParams())
    expect(state.query).toBe("")
    expect(state.searchKind).toBe("smart")
    expect(state.contentMode).toBe("canonical")
    expect(state.visibilityMode).toBe("author")
    expect(state.scopes).toEqual(["manuscript"])
    expect(state.includePending).toBe(false)
    expect(state.signature).toBe("")
  })

  it("解析全部字段与 scope 集合", () => {
    const query = new URLSearchParams(
      "q=旧塔&kind=literal&content_mode=working&visibility=character&character_id=c1&chapter_from=2&chapter_to=5&cutoff_chapter=4&cutoff_scene_id=s1&cutoff_offset=120&scope=world&scope=manuscript&scope=bogus&include_pending=1",
    )
    const state = parseRouteQuery(query)
    expect(state.query).toBe("旧塔")
    expect(state.searchKind).toBe("literal")
    expect(state.contentMode).toBe("working")
    expect(state.visibilityMode).toBe("character")
    expect(state.characterId).toBe("c1")
    expect(state.chapterFrom).toBe(2)
    expect(state.chapterTo).toBe(5)
    expect(state.cutoffChapter).toBe(4)
    expect(state.cutoffSceneId).toBe("s1")
    expect(state.cutoffOffset).toBe(120)
    expect(state.scopes).toEqual(["world", "manuscript"])
    expect(state.includePending).toBe(true)
  })

  it("非法数值与未知 scope 被拒绝", () => {
    const state = parseRouteQuery(new URLSearchParams("chapter_from=0&chapter_to=-1&cutoff_offset=-3&scope=evil"))
    expect(state.chapterFrom).toBeNull()
    expect(state.chapterTo).toBeNull()
    expect(state.cutoffOffset).toBeNull()
    expect(state.scopes).toEqual(["manuscript"])
  })

  it("signature 为规范化 query 字符串", () => {
    const state = parseRouteQuery(new URLSearchParams("q=a&kind=smart"))
    expect(state.signature).toBe("q=a&kind=smart")
  })
})

describe("buildRouteQuery", () => {
  it("由 payload 构造 query 并与 parse 互逆", () => {
    const payload = {
      search_kind: "literal",
      content_mode: "working",
      visibility: {
        mode: "character",
        cutoff_chapter: 4,
        cutoff_scene_id: "s1",
        cutoff_offset: 120,
        character_id: "c1",
      },
      scopes: ["manuscript", "world"],
      include_pending_objects: true,
      chapter_from: 2,
      chapter_to: 5,
    }
    const route = buildRouteQuery("旧塔", payload)
    expect(route.get("q")).toBe("旧塔")
    expect(route.get("kind")).toBe("literal")
    expect(route.get("content_mode")).toBe("working")
    expect(route.get("visibility")).toBe("character")
    expect(route.get("cutoff_chapter")).toBe("4")
    expect(route.get("cutoff_scene_id")).toBe("s1")
    expect(route.get("cutoff_offset")).toBe("120")
    expect(route.get("character_id")).toBe("c1")
    expect(route.getAll("scope")).toEqual(["manuscript", "world"])
    expect(route.get("include_pending")).toBe("1")

    const parsed = parseRouteQuery(route)
    expect(parsed.query).toBe("旧塔")
    expect(parsed.scopes).toEqual(["manuscript", "world"])
    expect(parsed.includePending).toBe(true)
  })

  it("可选项缺省时不写入 query", () => {
    const route = buildRouteQuery("x", {
      search_kind: "smart",
      content_mode: "canonical",
      visibility: { mode: "author" },
      scopes: ["manuscript"],
      include_pending_objects: false,
    })
    expect(route.has("chapter_from")).toBe(false)
    expect(route.has("cutoff_scene_id")).toBe(false)
    expect(route.has("include_pending")).toBe(false)
  })
})
