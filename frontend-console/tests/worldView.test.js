import { describe, it, expect, vi, beforeEach } from "vitest"
import worldView from "../views/worldView.js"

beforeEach(() => { vi.clearAllMocks(); worldView._entities = []; worldView._candidates = [] })

describe("worldView", () => {
  it("render 返回子标签导航", async () => {
    _state.currentSubView = "objects"
    const html = await worldView.render()
    expect(html).toContain("对象库")
    expect(html).toContain("候选清洗")
  })
})
