import { beforeEach, describe, expect, it, vi } from "vitest"
import { latestModal } from "./helpers.js"

beforeEach(() => {
  vi.clearAllMocks()
})

describe("feedback test helpers", () => {
  it("reads the latest modal with named fields", () => {
    showModal("确认发布", "<p>正文</p>", [{ text: "继续发布" }])

    expect(latestModal()).toMatchObject({
      title: "确认发布",
      body: "<p>正文</p>",
      buttons: [{ text: "继续发布" }],
    })
  })
})
