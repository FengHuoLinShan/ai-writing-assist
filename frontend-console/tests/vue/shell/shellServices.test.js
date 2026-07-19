import { describe, expect, it, vi } from "vitest"
import { createShellServices } from "../../../vue/shell/shellServices.js"

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
})
