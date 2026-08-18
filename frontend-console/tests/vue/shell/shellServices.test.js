import { beforeEach, describe, expect, it, vi } from "vitest"
import { createShellServices } from "../../../vue/shell/shellServices.js"

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe("shell workspace service seam", () => {
  it("routes writing shortcuts through explicit route-host actions, not renderer private methods", () => {
    const host = document.createElement("div")
    const save = document.createElement("button")
    save.id = "btn-autosave"
    const toggle = document.createElement("button")
    toggle.dataset.action = "toggle-outline-float"
    const onSave = vi.fn(); const onToggle = vi.fn()
    save.addEventListener("click", onSave); toggle.addEventListener("click", onToggle)
    host.append(save, toggle)
    const services = createShellServices({ state: {}, router: {}, commands: {}, api: {} })

    expect(services.workspace.autosave(host)).toBe(true)
    expect(services.workspace.toggleOutlineFloat(host)).toBe(true)
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it("provides cancelable scoped events when a route has no action button", () => {
    const host = document.createElement("div")
    host.addEventListener("shell:save-request", (event) => event.preventDefault())
    const services = createShellServices({ state: {}, router: {}, commands: {}, api: {} })
    expect(services.workspace.autosave(host)).toBe(true)
  })

  it("clears account-scoped browser data after a successful logout and preserves theme", async () => {
    const logout = vi.fn(async () => ({ logged_out: true }))
    const clearCache = vi.fn()
    const reload = vi.fn()
    localStorage.setItem("novel_accountId", "account-1")
    localStorage.setItem("draft_backup_project-1_1", "private")
    localStorage.setItem("generate_world_workspace_state_v2_project-1_project_core_entity", "private")
    localStorage.setItem("novel_active_workflows_v1", "private")
    localStorage.setItem("novel_theme", "dark")
    localStorage.setItem("writing_resume_pointer:v1:project-1", "private")
    sessionStorage.setItem("workspace-rail:project-1:writing:assistant", "closed")
    sessionStorage.setItem("workflow-progress-card:task-1", "open")
    const services = createShellServices({
      state: {},
      router: {},
      commands: {},
      api: { auth: { logout }, clearCache },
      reload,
    })

    await services.account.logout()

    expect(logout).toHaveBeenCalledTimes(1)
    expect(clearCache).toHaveBeenCalledTimes(1)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("novel_accountId")).toBeNull()
    expect(localStorage.getItem("draft_backup_project-1_1")).toBeNull()
    expect(localStorage.getItem("generate_world_workspace_state_v2_project-1_project_core_entity")).toBeNull()
    expect(localStorage.getItem("novel_active_workflows_v1")).toBeNull()
    expect(sessionStorage.getItem("workspace-rail:project-1:writing:assistant")).toBeNull()
    expect(sessionStorage.getItem("workflow-progress-card:task-1")).toBeNull()
    expect(localStorage.getItem("novel_theme")).toBe("dark")
    expect(localStorage.getItem("writing_resume_pointer:v1:project-1")).toBeNull()
  })

  it("clears and reloads locally even when the logout request fails", async () => {
    const logout = vi.fn(async () => { throw Object.assign(new Error("expired"), { status: 401 }) })
    const clearCache = vi.fn()
    const reload = vi.fn()
    localStorage.setItem("novel_accountId", "account-1")
    localStorage.setItem("draft_backup_project-1_1", "private")
    localStorage.setItem("novel_theme", "warm")
    sessionStorage.setItem("workflow-progress-details:task-1", "open")
    const services = createShellServices({
      state: {},
      router: {},
      commands: {},
      api: { auth: { logout }, clearCache },
      reload,
    })

    await expect(services.account.logout()).rejects.toMatchObject({ status: 401 })

    expect(clearCache).toHaveBeenCalledTimes(1)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("novel_accountId")).toBeNull()
    expect(localStorage.getItem("draft_backup_project-1_1")).toBeNull()
    expect(sessionStorage.getItem("workflow-progress-details:task-1")).toBeNull()
    expect(localStorage.getItem("novel_theme")).toBe("warm")
  })
})
