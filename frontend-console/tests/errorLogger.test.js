import { beforeEach, describe, expect, it, vi } from "vitest"

await import("../stateSlices.js")
await import("../state.js")
globalThis.state = window.appState

localStorage.clear()
localStorage.setItem("_errorLog", JSON.stringify([
  { id: 7, level: "error", message: "legacy global error" },
]))

await import("../errorLogger.js")

function readBucket(scopeId) {
  return JSON.parse(localStorage.getItem(`_errorLog:${scopeId}`) || "[]")
}

function recordToastError(message) {
  state.toast = null
  state.toast = { type: "error", message }
}

it("migrates the legacy global error log bucket once", () => {
  expect(localStorage.getItem("_errorLog")).toBeNull()
  expect(readBucket("global")).toEqual([
    { id: 7, level: "error", message: "legacy global error" },
  ])
})

describe("errorLogger scoped buckets", () => {
  beforeEach(() => {
    document.body.replaceChildren()
    localStorage.clear()
    sessionStorage.clear()
    globalThis.showToastNotification = vi.fn()
    state.currentProjectId = null
    state.currentProject = null
    state.currentView = "project"
    state.currentSubView = null
    state.toast = null
    state.error = null
    window.errorLog._lastApiError = null
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true }))
    api.reportFrontendError.mockClear()
    api.reportFrontendError.mockResolvedValue(null)
  })

  it("stores project A and B errors in separate buckets with per-bucket ids", () => {
    state.currentProjectId = "project-a"
    recordToastError("A first")
    recordToastError("A second")

    expect(window.errorLog.latestId).toBe(2)
    expect(window.errorLog.getAll().map((entry) => entry.message)).toEqual([
      "A first",
      "A second",
    ])

    state.currentProjectId = "project-b"
    recordToastError("B first")

    expect(readBucket("project-a").map((entry) => entry.projectId)).toEqual([
      "project-a",
      "project-a",
    ])
    expect(window.errorLog.getAll().map((entry) => entry.message)).toEqual(["B first"])
    expect(window.errorLog.latestId).toBe(1)
    expect(window.errorLog.getById(1)?.message).toBe("B first")
    expect(window.errorLog.getById(2)).toBeNull()

    const payload = api.reportFrontendError.mock.calls.at(-1)[0]
    expect(payload.projectId).toBeUndefined()
    expect(payload.frontendId).toBe(1)
  })

  it("delegates backend mirroring to the authenticated API transport", () => {
    recordToastError("closed deployment error")

    expect(api.reportFrontendError).toHaveBeenCalledOnce()
    expect(api.reportFrontendError.mock.calls[0][0]).toMatchObject({
      level: "error",
      message: "closed deployment error",
    })
    expect(fetch).not.toHaveBeenCalled()
  })

  it("omits request bodies and redacts credentials before storage and upload", () => {
    window.errorLog._lastApiError = {
      method: "PUT",
      url: "/settings/project?api_key=query-secret",
      status: 422,
      response: {
        detail: "Bearer response-secret",
        client_secret: "nested-secret",
        safe_code: "invalid_provider",
      },
      headers: { Authorization: "Bearer header-secret" },
      body: JSON.stringify({ api_key: "body-secret", model: "demo" }),
    }

    recordToastError("authorization=toast-secret")

    const entry = window.errorLog.getAll()[0]
    expect(entry.request).toMatchObject({
      method: "PUT",
      status: 422,
    })
    expect(entry.request).not.toHaveProperty("body")
    expect(entry.request).not.toHaveProperty("headers")
    expect(entry.request.response.safe_code).toBe("invalid_provider")

    const stored = localStorage.getItem("_errorLog:global")
    const uploaded = JSON.stringify(api.reportFrontendError.mock.calls[0][0])
    for (const secret of [
      "query-secret",
      "response-secret",
      "nested-secret",
      "header-secret",
      "body-secret",
      "toast-secret",
    ]) {
      expect(stored).not.toContain(secret)
      expect(uploaded).not.toContain(secret)
    }
  })

  it("clears only the current project bucket", () => {
    state.currentProjectId = "project-a"
    recordToastError("A")
    state.currentProjectId = "project-b"
    recordToastError("B")

    window.errorLog.clear()

    expect(readBucket("project-a").map((entry) => entry.message)).toEqual(["A"])
    expect(readBucket("project-b")).toEqual([])
    expect(window.errorLog.getAll()).toEqual([])
    expect(window.errorLog.latestId).toBeNull()
  })

  it("refreshes the badge and closes the panel when the project changes", () => {
    state.currentProjectId = "project-a"
    recordToastError("A")

    const badge = document.getElementById("error-log-badge")
    expect(badge?.textContent).toBe("⚠ 1")
    badge?.click()
    expect(document.getElementById("error-log-panel")).not.toBeNull()

    state.currentProjectId = "project-b"

    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(document.getElementById("error-log-badge")?.style.display).toBe("none")

    state.currentProjectId = "project-a"

    expect(document.getElementById("error-log-badge")?.style.display).toBe("block")
    expect(document.getElementById("error-log-badge")?.textContent).toBe("⚠ 1")
  })
})
