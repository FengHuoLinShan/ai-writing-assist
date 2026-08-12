import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { createMapModalController } from "../../../vue/views/map/mapModalController.js"

await import("../../../ui/modal.js")

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function renderModalShell() {
  document.body.innerHTML = `
    <div id="modal-overlay" class="hidden">
      <div id="modal-content"><div id="modal-title"></div><div id="modal-body"></div><div id="modal-footer"></div></div>
    </div>`
}

describe("map modal controller ownership", () => {
  let api
  let onCreated
  let toast
  let controller

  beforeEach(() => {
    renderModalShell()
    resetBridgeOverrides()
    api = { world: { createMap: vi.fn() } }
    onCreated = vi.fn(async () => true)
    toast = vi.fn()
    setBridgeOverrides({
      api,
      state: { currentProjectId: "p1", currentView: "map" },
      toast,
      esc: (value) => String(value ?? ""),
      showModalHtml: window.showModalHtml,
    })
    controller = createMapModalController({
      projectId: "p1",
      getMaps: () => [{ id: "m1", name: "九州" }],
      getArchivedMaps: () => [{ id: "a1", name: "旧地图" }],
      onCreated,
    })
  })

  afterEach(() => {
    controller?.dispose()
    window.closeModal({ force: true })
    resetBridgeOverrides()
  })

  it("keeps a replacement modal when an old create request finishes", async () => {
    const request = deferred()
    api.world.createMap.mockReturnValueOnce(request.promise)
    controller.showCreateWorld()
    document.getElementById("map-create-name").value = "新世界"
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "创建").click()
    await vi.waitFor(() => expect(api.world.createMap).toHaveBeenCalledOnce())

    controller.showRestore("a1")
    request.resolve({ id: "m2", name: "新世界" })
    await vi.waitFor(() => expect(document.getElementById("modal-title").textContent).toBe("恢复归档地图"))

    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    expect(onCreated).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("世界地图已创建", "success")
  })

  it("opens transition dialogs directly without closing the replacement", async () => {
    controller.showDynamicItem({ id: "o1", item_kind: "observation", title: "北境通道" })
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "更换地图").click()

    await vi.waitFor(() => expect(document.getElementById("modal-title").textContent).toBe("分配地图待处理项"))
    expect(document.getElementById("map-inbox-assignment-map")).not.toBeNull()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })
})
