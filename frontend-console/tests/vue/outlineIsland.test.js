import { describe, expect, it, vi } from "vitest"

const stubs = vi.hoisted(() => ({
  appState: {
    currentProjectId: "p1",
    currentSubView: "story-outline",
    viewStates: {},
  },
  router: {
    getCurrentQuery: vi.fn(() => new URLSearchParams()),
    navigate: vi.fn(),
    registerView: vi.fn(),
  },
  islands: [],
  bases: [],
}))

vi.mock("../../vue/mountIsland.js", () => ({
  mountIsland: vi.fn(() => {
    const base = {
      onEnter: vi.fn(async () => {}),
      render: vi.fn(() => '<div data-vue-island="outline"></div>'),
      onRendered: vi.fn(async () => {}),
      onLeave: vi.fn(),
    }
    const island = { ...base }
    stubs.bases.push(base)
    stubs.islands.push(island)
    return island
  }),
}))

vi.mock("../../vue/bridge/index.js", () => ({
  getApi: () => globalThis.api,
  getAppState: () => stubs.appState,
  getEsc: () => (value) => String(value ?? ""),
  getRouter: () => stubs.router,
}))

await import("../../vue/outlineIsland.js")

describe("outlineIsland scene transition", () => {
  it("uses the same Vue island lifecycle for scenes instead of a vanilla delegate", async () => {
    const island = stubs.islands[0]
    const base = stubs.bases[0]
    stubs.appState.currentSubView = "scenes"

    await island.onEnter()
    expect(island.render()).toBe('<div data-vue-island="outline"></div>')
    await island.onRendered()

    expect(base.onEnter).toHaveBeenCalledTimes(1)
    expect(base.render).toHaveBeenCalledTimes(1)
    expect(base.onRendered).toHaveBeenCalledTimes(1)
    expect(base.onLeave).not.toHaveBeenCalled()
  })
})
