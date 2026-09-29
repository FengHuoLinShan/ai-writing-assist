/**
 * useEditorialGuard 测试 — 编辑审读失效确认守卫。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import {
  activeEditorialReviews,
  confirmEditorialImpact,
  editorialImpactMessage,
  invalidateEditorialReviewCache,
} from "../../../vue/composables/useEditorialGuard.js"

function review(overrides = {}) {
  return {
    id: "rev-1",
    status: "running",
    scope: { scope: "chapter" },
    sources: [{ chapter_index: 3 }],
    checked_chapters: [],
    unchecked_chapters: [3],
    ...overrides,
  }
}

let apiMock
let confirmMock

beforeEach(() => {
  invalidateEditorialReviewCache()
  confirmMock = vi.fn(() => true)
  apiMock = {
    assistant: {
      editorialPolicy: vi.fn(async () => ({ feature_available: true })),
      editorialReviews: vi.fn(async () => [review()]),
    },
  }
  setBridgeOverrides({ api: apiMock, confirm: confirmMock })
})

afterEach(() => {
  resetBridgeOverrides()
  invalidateEditorialReviewCache()
})

describe("activeEditorialReviews", () => {
  it("过滤出 queued/running 状态的审读", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([
      review({ id: "a", status: "queued" }),
      review({ id: "b", status: "completed" }),
      review({ id: "c", status: "stale" }),
    ])
    const reviews = await activeEditorialReviews("p1")
    expect(reviews.map((item) => item.id)).toEqual(["a"])
  })

  it("功能未开放时返回空数组", async () => {
    apiMock.assistant.editorialPolicy.mockResolvedValue({ feature_available: false })
    const reviews = await activeEditorialReviews("p1")
    expect(reviews).toEqual([])
    expect(apiMock.assistant.editorialReviews).not.toHaveBeenCalled()
  })

  it("policy 请求失败时 fail open 返回空数组", async () => {
    apiMock.assistant.editorialPolicy.mockRejectedValue(new Error("network"))
    const reviews = await activeEditorialReviews("p1")
    expect(reviews).toEqual([])
  })

  it("reviews 请求失败时 fail open 返回空数组", async () => {
    apiMock.assistant.editorialReviews.mockRejectedValue(new Error("network"))
    const reviews = await activeEditorialReviews("p1")
    expect(reviews).toEqual([])
  })

  it("按 chapterIndex 过滤：只保留覆盖该章节的审读", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([
      review({ id: "chapter-3", scope: { scope: "chapter" }, sources: [{ chapter_index: 3 }] }),
      review({ id: "chapter-5", scope: { scope: "chapter" }, sources: [{ chapter_index: 5 }] }),
      review({ id: "book", scope: { scope: "book" }, sources: [] }),
    ])
    const forChapter3 = await activeEditorialReviews("p1", { chapterIndex: 3 })
    expect(forChapter3.map((item) => item.id).sort()).toEqual(["book", "chapter-3"])
  })

  it("同一项目短时间内复用缓存，不重复请求", async () => {
    await activeEditorialReviews("p1")
    await activeEditorialReviews("p1")
    expect(apiMock.assistant.editorialReviews).toHaveBeenCalledTimes(1)
  })
})

describe("confirmEditorialImpact", () => {
  it("没有进行中审读时直接放行，不弹确认框", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([])
    const result = await confirmEditorialImpact("p1", { kind: "world" })
    expect(result).toBe(true)
    expect(confirmMock).not.toHaveBeenCalled()
  })

  it("有进行中审读时弹出确认框，文案包含数量", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([review(), review({ id: "rev-2" })])
    const result = await confirmEditorialImpact("p1", { kind: "world" })
    expect(result).toBe(true)
    expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining("2"))
  })

  it("作者取消时返回 false", async () => {
    confirmMock.mockReturnValue(false)
    const result = await confirmEditorialImpact("p1", { kind: "world" })
    expect(result).toBe(false)
  })

  it("chapter kind 的文案包含章节号", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([review({ sources: [{ chapter_index: 7 }] })])
    await confirmEditorialImpact("p1", { kind: "chapter", chapterIndex: 7 })
    expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining("第 7 章"))
  })

  it("传入 reviews 时跳过网络请求", async () => {
    const result = await confirmEditorialImpact("p1", { kind: "brief", reviews: [review()] })
    expect(result).toBe(true)
    expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining("编辑约定"))
    expect(apiMock.assistant.editorialReviews).not.toHaveBeenCalled()
  })
})

describe("editorialImpactMessage", () => {
  it("未知 kind 回退到 world 文案", () => {
    expect(editorialImpactMessage("unknown", 1)).toContain("世界设定")
  })
})
