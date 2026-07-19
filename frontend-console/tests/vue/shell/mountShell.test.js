import { afterEach, describe, expect, it } from "vitest"
import { mountShell } from "../../../vue/shell/mountShell.js"
import { createShellTestServices } from "./helpers.js"
import { nextTick } from "vue"

describe("mountShell", () => {
  let mounted = null
  afterEach(() => { mounted?.unmount(); mounted = null; document.body.innerHTML = "" })

  it("mounts static hosts before initializing the existing hash router", async () => {
    document.body.innerHTML = '<div id="app"><p>legacy shell</p></div>'
    const services = createShellTestServices()
    services.router.init.mockImplementation(async () => {
      expect(document.getElementById("workspace-content")?.dataset.imperativeRouteHost).toBe("hash-router")
      document.getElementById("workspace-content").textContent = "router rendered"
    })

    mounted = await mountShell({ services, healthIntervalMs: 60_000 })

    expect(services.router.init).toHaveBeenCalledTimes(1)
    expect(mounted.getRouteHost().textContent).toBe("router rendered")
    mounted.updateWordcountDashboard({ chapterIndex: 1, chapterWords: 22 })
    await nextTick()
    expect(document.getElementById("topbar-chapter-wc").textContent).toBe("22")
  })

  it("unmounts the shell when initial route bootstrap rejects", async () => {
    document.body.innerHTML = '<div id="app"></div>'
    const services = createShellTestServices()
    services.router.init.mockRejectedValue(new Error("route bootstrap failed"))

    await expect(mountShell({ services, healthIntervalMs: 60_000 })).rejects.toThrow("route bootstrap failed")

    expect(document.getElementById("workspace-content")).toBeNull()
    expect(document.getElementById("app")?.childElementCount).toBe(0)
  })
})
