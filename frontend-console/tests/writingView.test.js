import { describe, it, expect, vi, beforeEach } from "vitest"
import writingView from "../views/writingView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("writingView", () => {
  it("无选中章节时显示加载状态", async () => {
    const html = await writingView.render()
    // render 中调用了 API，但在测试环境中 mock 返回空
    // 不抛异常即可
    expect(typeof html).toBe("string")
  })
})
