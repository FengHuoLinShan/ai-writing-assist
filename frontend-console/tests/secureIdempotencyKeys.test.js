import { afterEach, describe, expect, it, vi } from "vitest"

import { interactionOperationKey } from "../vue/views/interaction/interactionSession.js"
import { idempotencyKey } from "../vue/views/outline/story/storyOutlineData.js"

afterEach(() => vi.unstubAllGlobals())

describe("secure frontend idempotency keys", () => {
  it("uses randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" })
    expect(interactionOperationKey("message"))
      .toBe("message-00000000-0000-4000-8000-000000000001")
    expect(idempotencyKey())
      .toBe("story-outline-00000000-0000-4000-8000-000000000001")
  })

  it("falls back to cryptographic bytes and fails closed without Web Crypto", () => {
    const getRandomValues = vi.fn((bytes) => bytes.fill(10))
    vi.stubGlobal("crypto", { getRandomValues })
    expect(interactionOperationKey("message")).toBe(`message-${"0a".repeat(16)}`)
    expect(idempotencyKey()).toBe(`story-outline-${"0a".repeat(16)}`)
    expect(getRandomValues).toHaveBeenCalledTimes(2)

    vi.stubGlobal("crypto", {})
    expect(() => interactionOperationKey()).toThrow("当前浏览器无法安全生成操作标识")
    expect(() => idempotencyKey()).toThrow("当前浏览器无法安全生成操作标识")
  })
})
