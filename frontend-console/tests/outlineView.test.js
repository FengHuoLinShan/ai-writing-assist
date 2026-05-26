import { describe, it, expect, vi, beforeEach } from "vitest"
import outlineView from "../views/outlineView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("outlineView", () => {
  it("render 返回子标签导航", async () => {
    _state.currentSubView = "threads"
    const html = await outlineView.render()
    expect(html).toContain("剧情线")
    expect(html).toContain("篇章纲")
  })
})
