import { describe, expect, it, vi } from "vitest"
import mapQuickCreateView from "../../../views/mapQuickCreateView.js"
import { openWritingMapQuickCreate } from "../../../vue/views/writing/controllers/mapQuickCreateBridge.js"

describe("mapQuickCreateBridge", () => {
  it("只透传打开参数与完成回调，写作岛不读写地图弹窗 DOM", async () => {
    const onCreated = vi.fn()
    const options = { projectId: "p1", onCreated }
    const open = vi.spyOn(mapQuickCreateView, "open").mockResolvedValue("opened")

    await expect(openWritingMapQuickCreate(options)).resolves.toBe("opened")
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(options)
  })
})
