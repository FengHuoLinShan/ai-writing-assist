import { describe, it, expect, beforeEach, vi } from "vitest"

import "../app.js"

describe("setup smoke test", () => {
  beforeEach(() => {
    // Reset init guard so each test exercises initialization
    if (globalThis.App) {
      globalThis.App._initialized = false
    }
  })

  it("globals are available", () => {
    expect(globalThis.state).toBeDefined()
    expect(globalThis.esc).toBeDefined()
    expect(globalThis.router).toBeDefined()
    expect(globalThis.api).toBeDefined()
    expect(globalThis.toast).toBeDefined()
    expect(globalThis.showModal).toBeDefined()
    expect(globalThis.document).toBeDefined()
  })

  it("exposes App on window and initializes without errors", () => {
    expect(globalThis.App).toBeDefined()
    expect(() => globalThis.App.init()).not.toThrow()
    expect(globalThis.App._initialized).toBe(true)
  })

  it("clears the previous health interval when init is called again", () => {
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval").mockImplementation(() => {})
    globalThis.App._initialized = false
    globalThis.App._healthInterval = 1234

    globalThis.App.init()

    expect(clearIntervalSpy).toHaveBeenCalledWith(1234)
    expect(globalThis.App._healthInterval).not.toBeNull()
    clearIntervalSpy.mockRestore()
  })
})
