import { describe, it, expect } from "vitest"

describe("setup smoke test", () => {
  it("globals are available", () => {
    expect(globalThis._state).toBeDefined()
    expect(globalThis.esc).toBeDefined()
    expect(globalThis.router).toBeDefined()
    expect(globalThis.api).toBeDefined()
    expect(globalThis.toast).toBeDefined()
    expect(globalThis.showModal).toBeDefined()
    expect(globalThis.document).toBeDefined()
  })
})
