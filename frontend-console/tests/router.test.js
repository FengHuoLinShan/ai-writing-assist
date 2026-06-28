/**
 * Router regression tests
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../router.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
})

describe("renderCurrentView error handling", () => {
  it("escapes renderer error messages in the fallback UI", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    const maliciousMessage = "<img src=x onerror=alert('router')>"
    const evilView = {
      async render() {
        throw new Error(maliciousMessage)
      },
    }

    state.currentView = "evil-test-view"
    window.router.registerView("evil-test-view", evilView)

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    await window.router.renderCurrentView()
    errorSpy.mockRestore()

    expect(content.querySelector("img")).toBeNull()
    expect(content.textContent).toContain(maliciousMessage)
  })
})
