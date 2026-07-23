import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  ACCOUNT_INVALIDATED_EVENT,
  clearAccountScopedBrowserStorage,
  forceAccountSafeReload,
  scopeBrowserStorageToAccount,
} from "../../shared/accountStorage.js"

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe("account-scoped browser storage", () => {
  it("clears account and project data while preserving theme and unrelated origin data", () => {
    const localKeys = [
      "novel_accountId",
      "novel_currentProjectId",
      "novel_active_workflows_v1",
      "draft_backup_project-1_1",
      "generate_world_workspace_state_v2_project-1_project_core_entity",
      "writing_scene_cockpit_order:project-1",
      "worldBible:project-1:lastPage",
      "worldBibleProjection:project-1:page-1:context_brief",
      "_errorLog:project-1",
    ]
    const sessionKeys = [
      "novel_app_access_token",
      "workspace-rail:project-1:writing:assistant",
      "workflow-progress-card:task-1",
      "workflow-progress-details:task-1",
    ]
    for (const key of localKeys) localStorage.setItem(key, "private")
    for (const key of sessionKeys) sessionStorage.setItem(key, "private")
    localStorage.setItem("novel_theme", "dark")
    localStorage.setItem("other-app-state", "keep")
    sessionStorage.setItem("other-app-session", "keep")

    const removed = clearAccountScopedBrowserStorage()

    expect(removed).toEqual({ local: localKeys.length, session: sessionKeys.length })
    for (const key of localKeys) expect(localStorage.getItem(key)).toBeNull()
    for (const key of sessionKeys) expect(sessionStorage.getItem(key)).toBeNull()
    expect(localStorage.getItem("novel_theme")).toBe("dark")
    expect(localStorage.getItem("other-app-state")).toBe("keep")
    expect(sessionStorage.getItem("other-app-session")).toBe("keep")
  })

  it("treats a missing account marker as an unsafe legacy scope before writing the new marker", () => {
    localStorage.setItem("draft_backup_project-1_1", "private")
    sessionStorage.setItem("workspace-rail:project-1:writing:assistant", "closed")

    expect(scopeBrowserStorageToAccount("account-new")).toBe(true)
    expect(localStorage.getItem("draft_backup_project-1_1")).toBeNull()
    expect(sessionStorage.getItem("workspace-rail:project-1:writing:assistant")).toBeNull()
    expect(localStorage.getItem("novel_accountId")).toBe("account-new")
  })

  it("clears a previous account scope but preserves an established matching account scope", () => {
    localStorage.setItem("novel_accountId", "account-old")
    localStorage.setItem("novel_active_workflows_v1", "private")

    expect(scopeBrowserStorageToAccount("account-new")).toBe(true)
    expect(localStorage.getItem("novel_active_workflows_v1")).toBeNull()
    expect(localStorage.getItem("novel_accountId")).toBe("account-new")

    localStorage.setItem("draft_backup_project-2_1", "same-account-draft")
    expect(scopeBrowserStorageToAccount("account-new")).toBe(false)
    expect(localStorage.getItem("draft_backup_project-2_1")).toBe("same-account-draft")
  })

  it("preserves the new marker during cross-tab invalidation and lets the App own reload", () => {
    localStorage.setItem("novel_accountId", "account-new")
    localStorage.setItem("draft_backup_project-old_1", "private")
    localStorage.setItem("novel_theme", "dark")
    sessionStorage.setItem("workspace-rail:project-old:writing:assistant", "closed")
    const reload = vi.fn()
    const handler = vi.fn((event) => event.preventDefault())
    window.addEventListener(ACCOUNT_INVALIDATED_EVENT, handler)

    try {
      const result = forceAccountSafeReload({
        reason: "account-marker-changed",
        preserveAccountMarker: true,
        reload,
      })

      expect(result.handled).toBe(true)
      expect(handler).toHaveBeenCalledTimes(1)
      expect(reload).not.toHaveBeenCalled()
      expect(localStorage.getItem("novel_accountId")).toBe("account-new")
      expect(localStorage.getItem("draft_backup_project-old_1")).toBeNull()
      expect(sessionStorage.getItem("workspace-rail:project-old:writing:assistant")).toBeNull()
      expect(localStorage.getItem("novel_theme")).toBe("dark")
    } finally {
      window.removeEventListener(ACCOUNT_INVALIDATED_EVENT, handler)
    }
  })
})
