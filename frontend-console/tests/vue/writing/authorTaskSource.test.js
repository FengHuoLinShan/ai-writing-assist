import { describe, expect, it, vi } from "vitest"

import {
  authorTaskPanelQuery,
  authorTaskSourceFromQuery,
  openAuthorTaskSource,
} from "../../../vue/views/writing/home/authorTaskSource.js"

describe("作者任务来源路由", () => {
  it("只解码封闭来源并带入预填标题", () => {
    const query = authorTaskPanelQuery({ kind: "world_entity", id: "e1", title: "核对沉钟港" })
    expect(query.toString()).not.toContain("http")
    expect(authorTaskSourceFromQuery(query)).toEqual({
      kind: "world_entity", id: "e1", taskTitle: "核对沉钟港",
    })
    expect(authorTaskSourceFromQuery(new URLSearchParams("task_source_kind=url&task_source_id=https://example.com"))).toBeNull()
  })

  it.each([
    ["world_page", "world", "bible", "page_id"],
    ["world_entity", "world", "bible", "entity_id"],
    ["writing_chapter", "writing", null, "chapter_index"],
    ["outline_scene", "outline", "scenes", "scene_id"],
  ])("将 %s 返回所属领域", (kind, view, subView, key) => {
    const router = { navigate: vi.fn() }
    expect(openAuthorTaskSource({ kind, id: "source-1", label: "来源", available: true }, router)).toBe(true)
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual([view, subView, true])
    expect(router.navigate.mock.calls[0][3].get(key)).toBe("source-1")
  })

  it("失效来源不导航", () => {
    const router = { navigate: vi.fn() }
    expect(openAuthorTaskSource({ kind: "world_page", id: "gone", available: false }, router)).toBe(false)
    expect(router.navigate).not.toHaveBeenCalled()
  })
})
