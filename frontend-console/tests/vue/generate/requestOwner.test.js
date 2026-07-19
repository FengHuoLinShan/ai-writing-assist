import { describe, expect, it } from "vitest"
import { createGenerateRequestOwner } from "../../../vue/views/generate/requestOwner.js"

describe("generate request ownership", () => {
  it("aborts every owned request and rejects late writes after dispose", () => {
    const owner = createGenerateRequestOwner({ projectId: "p1", sessionKey: "session-1" })
    const first = owner.begin(); const second = owner.begin()
    expect(owner.isActive(first)).toBe(true)
    owner.dispose()
    expect(first.controller.signal.aborted).toBe(true)
    expect(second.controller.signal.aborted).toBe(true)
    expect(owner.isActive(first)).toBe(false)
  })

  it("invalidates an old generation while allowing a new owned request", () => {
    const owner = createGenerateRequestOwner({ projectId: "p1", sessionKey: "session-1" })
    const old = owner.begin(); owner.invalidate(); const current = owner.begin()
    expect(owner.isActive(old)).toBe(false)
    expect(owner.isActive(current)).toBe(true)
  })
})
