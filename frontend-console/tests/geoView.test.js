import { describe, it, expect, vi, beforeEach } from "vitest"
import geoView from "../views/geoView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("geoView", () => {
  it("render 返回子标签导航", async () => {
    _state.currentSubView = "tree"
    const html = await geoView.render()
    expect(html).toContain("地点树")
    expect(html).toContain("历史时期")
  })
})
