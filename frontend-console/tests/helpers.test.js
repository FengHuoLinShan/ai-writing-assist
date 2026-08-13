import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  clickModalButtonByText,
  expectNoOverlaps,
  expectNoTechnicalIds,
  latestModal,
  renderHtml,
} from "./helpers.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
})

describe("feedback test helpers", () => {
  it("renders HTML into a detached container for scoped assertions", () => {
    const container = renderHtml("<section><button>保存</button></section>")

    expect(container.querySelector("button")?.textContent).toBe("保存")
  })

  it("reads and clicks the latest modal action by visible text", async () => {
    const handler = vi.fn()
    showModal("确认发布", "<p>正文</p>", [
      { text: "取消", handler: vi.fn() },
      { text: "继续发布", handler },
    ])

    expect(latestModal()).toMatchObject({
      title: "确认发布",
      body: "<p>正文</p>",
    })

    await clickModalButtonByText("继续发布")

    expect(handler).toHaveBeenCalledOnce()
  })

  it("reports leaked technical ids and overlapping boxes with useful messages", () => {
    const container = renderHtml("<p>用户看到 technical-id-1</p>")

    expect(() => expectNoTechnicalIds(container, ["technical-id-1"]))
      .toThrow(/technical-id-1/)

    expect(() => expectNoOverlaps([
      { label: "洛阳", box: { x: 0, y: 0, width: 20, height: 20 } },
      { label: "内城", box: { x: 10, y: 10, width: 20, height: 20 } },
    ])).toThrow(/洛阳.*内城/s)
  })
})
