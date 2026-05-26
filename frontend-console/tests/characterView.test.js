import { describe, it, expect, vi, beforeEach } from "vitest"
import characterView from "../views/characterView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("characterView", () => {
  it("render 返回子标签导航", async () => {
    _state.currentSubView = "list"
    const html = await characterView.render()
    expect(html).toContain("人物列表")
    expect(html).toContain("人物档案")
  })
})
