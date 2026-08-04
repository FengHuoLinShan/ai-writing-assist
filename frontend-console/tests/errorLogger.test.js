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

function addWorkspace() {
  const workspace = document.createElement("main")
  workspace.id = "workspace"
  workspace.tabIndex = -1
  document.body.appendChild(workspace)
  return workspace
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

  it("redacts validation input using the sensitive field location", () => {
    const marker = "provider-key-without-known-prefix"
    window.errorLog._lastApiError = {
      method: "PUT",
      url: "/projects/project-a/llm-settings",
      status: 422,
      response: JSON.stringify({
        detail: [{
          type: "string_too_long",
          loc: ["body", "api_key"],
          msg: "String should have at most 4096 characters",
          input: marker,
        }],
      }),
    }

    recordToastError("数据格式校验失败")

    const stored = localStorage.getItem("_errorLog:global")
    const uploaded = JSON.stringify(api.reportFrontendError.mock.calls[0][0])
    expect(stored).toContain("[REDACTED]")
    expect(uploaded).toContain("[REDACTED]")
    expect(stored).not.toContain(marker)
    expect(uploaded).not.toContain(marker)
  })

  it("drops malformed response diagnostics instead of retaining unknown input", () => {
    const marker = "provider-key-in-truncated-json"
    window.errorLog._lastApiError = {
      method: "PUT",
      url: "/projects/project-a/llm-settings",
      status: 422,
      response: `{"detail":[{"loc":["body","api_key"],"input":"${marker}`,
    }

    recordToastError("数据格式校验失败")

    const entry = window.errorLog.getAll()[0]
    const uploaded = JSON.stringify(api.reportFrontendError.mock.calls[0][0])
    expect(entry.request.response).toBe("[REDACTED]")
    expect(JSON.stringify(entry)).not.toContain(marker)
    expect(uploaded).not.toContain(marker)
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

  it("closes for a project change without taking focus from the incoming workspace", () => {
    state.currentProjectId = "project-a"
    recordToastError("A")
    state.currentProjectId = "project-b"
    recordToastError("B")
    state.currentProjectId = "project-a"
    document.getElementById("error-log-badge")?.click()

    const incomingWorkspace = document.createElement("button")
    incomingWorkspace.type = "button"
    incomingWorkspace.textContent = "新页面工作区"
    document.body.appendChild(incomingWorkspace)
    incomingWorkspace.focus()
    state.currentProjectId = "project-b"

    const badge = document.getElementById("error-log-badge")
    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(badge?.style.display).toBe("block")
    expect(badge?.textContent).toBe("⚠ 1")
    expect(document.activeElement).toBe(incomingWorkspace)
  })

  it("uses an accessible native badge and restores its focus after closing the non-modal dialog", () => {
    recordToastError("键盘可达错误")
    const badge = document.getElementById("error-log-badge")

    expect(badge?.tagName).toBe("BUTTON")
    expect(badge?.getAttribute("type")).toBe("button")
    expect(badge?.getAttribute("title")).toBe("打开本地错误日志，查看排障详情")
    expect(badge?.getAttribute("aria-label")).toBe("打开错误日志，当前 1 条")
    expect(badge?.getAttribute("aria-haspopup")).toBe("dialog")
    expect(badge?.getAttribute("aria-controls")).toBe("error-log-panel")
    expect(badge?.getAttribute("aria-expanded")).toBe("false")

    badge?.click()
    const panel = document.getElementById("error-log-panel")
    const closeButton = panel?.querySelector("button:last-child")
    expect(panel?.getAttribute("role")).toBe("dialog")
    expect(panel?.getAttribute("aria-labelledby")).toBe("error-log-panel-title")
    expect(panel?.hasAttribute("aria-modal")).toBe(false)
    expect(document.activeElement).toBe(closeButton)
    expect(badge?.getAttribute("aria-expanded")).toBe("true")
    panel?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))

    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(document.activeElement).toBe(badge)
    expect(badge?.getAttribute("aria-expanded")).toBe("false")

    badge?.click()
    const reopenedCloseButton = document.querySelector("#error-log-panel button:last-child")
    reopenedCloseButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(document.activeElement).toBe(badge)
  })

  it("does not expose right-click as a destructive clear shortcut", () => {
    recordToastError("保留的错误")
    const badge = document.getElementById("error-log-badge")
    badge?.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }))

    expect(window.errorLog.getAll().map((entry) => entry.message)).toEqual(["保留的错误"])
    expect(document.getElementById("error-log-panel")).toBeNull()
  })

  it("requires confirmation to clear only the active bucket and handles confirmation Escape", () => {
    const workspace = addWorkspace()
    state.currentProjectId = "project-a"
    recordToastError("A")
    state.currentProjectId = "project-b"
    recordToastError("B")
    state.currentProjectId = "project-a"

    const badge = document.getElementById("error-log-badge")
    badge?.click()
    const panel = document.getElementById("error-log-panel")
    const clearButton = [...(panel?.querySelectorAll("button") || [])]
      .find((button) => button.textContent === "清空")
    clearButton?.click()

    const confirmation = document.getElementById("error-log-clear-confirmation")
    const confirmButton = [...(confirmation?.querySelectorAll("button") || [])]
      .find((button) => button.textContent === "确认清空")
    expect(readBucket("project-a").map((entry) => entry.message)).toEqual(["A"])
    expect(confirmation?.textContent).toContain("当前项目的错误日志中的 1 条")
    expect(document.activeElement).toBe(confirmButton)

    confirmButton?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(document.getElementById("error-log-clear-confirmation")).toBeNull()
    expect(document.activeElement).toBe(clearButton)

    clearButton?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(document.activeElement).toBe(badge)

    badge?.click()
    const reopenedPanel = document.getElementById("error-log-panel")
    const reopenedClearButton = [...(reopenedPanel?.querySelectorAll("button") || [])]
      .find((button) => button.textContent === "清空")
    reopenedClearButton?.click()
    const cancelButton = [...(document.getElementById("error-log-clear-confirmation")?.querySelectorAll("button") || [])]
      .find((button) => button.textContent === "取消")
    cancelButton?.click()
    expect(document.getElementById("error-log-clear-confirmation")).toBeNull()
    expect(document.activeElement).toBe(reopenedClearButton)

    reopenedClearButton?.click()
    const finalConfirmButton = [...(document.getElementById("error-log-clear-confirmation")?.querySelectorAll("button") || [])]
      .find((button) => button.textContent === "确认清空")
    finalConfirmButton?.click()

    expect(readBucket("project-a")).toEqual([])
    expect(readBucket("project-b").map((entry) => entry.message)).toEqual(["B"])
    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(badge?.style.display).toBe("none")
    expect(document.activeElement).toBe(workspace)
  })

  it("closes an open panel safely when the public clear API is called", () => {
    const workspace = addWorkspace()
    recordToastError("程序化清空")
    const badge = document.getElementById("error-log-badge")
    badge?.click()

    window.errorLog.clear()

    expect(window.errorLog.getAll()).toEqual([])
    expect(document.getElementById("error-log-panel")).toBeNull()
    expect(badge?.style.display).toBe("none")
    expect(document.activeElement).toBe(workspace)
  })

  it("renders hostile logged text as text rather than DOM", () => {
    const message = '<img src=x onerror="alert(1)">'
    recordToastError(message)
    document.getElementById("error-log-badge")?.click()

    const panel = document.getElementById("error-log-panel")
    expect(panel?.textContent).toContain(message)
    expect(panel?.querySelector("img")).toBeNull()
    expect(panel?.querySelector("script")).toBeNull()
  })
})
