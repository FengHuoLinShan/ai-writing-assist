import { beforeEach, describe, expect, it, vi } from "vitest"

const stubs = vi.hoisted(() => ({ island: { onEnter: vi.fn(), render: vi.fn(), onRendered: vi.fn(), onLeave: vi.fn(), canLeave: vi.fn(() => true) }, mountIsland: vi.fn() }))
stubs.mountIsland.mockReturnValue(stubs.island)
vi.mock("../../vue/mountIsland.js", () => ({ mountIsland: stubs.mountIsland }))

const bridge = await import("../../vue/bridge/index.js")

describe("mapIsland", () => {
  beforeEach(() => { bridge.resetBridgeOverrides(); vi.clearAllMocks(); stubs.mountIsland.mockReturnValue(stubs.island) })

  it("registers a Vue-owned map route without importing the legacy workspace", async () => {
    const router = { registerView: vi.fn() }
    bridge.setBridgeOverrides({ router })
    const module = await import("../../vue/mapIsland.js")

    expect(stubs.mountIsland).toHaveBeenCalledWith(expect.objectContaining({ viewName: "map", load: expect.any(Function) }))
    expect(router.registerView).toHaveBeenCalledWith("map", stubs.island)
    expect(module.registerMapIsland).toBeTypeOf("function")
  })
})
