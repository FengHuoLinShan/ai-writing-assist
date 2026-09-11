import { describe, expect, it } from "vitest"
import { isVersionActive } from "../../vue/views/writing/versionState.js"

describe("isVersionActive", () => {
  it("prefers display state and preserves legacy status fallback", () => {
    expect(isVersionActive({ display_state: "active", status: "candidate" })).toBe(true)
    expect(isVersionActive({ display_state: "history", status: "published" })).toBe(false)
    expect(isVersionActive({ status: "published" })).toBe(true)
    expect(isVersionActive({ status: "deprecated" })).toBe(false)
  })
})
