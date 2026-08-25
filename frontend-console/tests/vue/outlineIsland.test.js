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
  options: [],
}))

vi.mock("../../vue/mountIsland.js", () => ({
  mountIsland: vi.fn((options) => {
    const base = {
      onEnter: vi.fn(async () => {}),
      render: vi.fn(() => '<div data-vue-island="outline"></div>'),
      onRendered: vi.fn(async () => {}),
      onLeave: vi.fn(),
    }
    const island = { ...base }
    stubs.bases.push(base)
    stubs.islands.push(island)
    stubs.options.push(options)
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

  it("从 story-outline query 恢复独立编辑页", async () => {
    stubs.appState.currentSubView = "story-outline"
    stubs.router.getCurrentQuery.mockReturnValue(new URLSearchParams("edit=1"))
    globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.world.listCharacters.mockResolvedValue({ items: [] })
    globalThis.api.world.listEntities.mockResolvedValue({ items: [] })

    const loaded = await stubs.options[0].load()

    expect(loaded).toMatchObject({ projectId: "p1", subView: "story-outline", editorMode: true })
  })

  it("在剧情线的 review=ai query 恢复结构化审阅页", async () => {
    stubs.appState.currentSubView = "threads"
    stubs.router.getCurrentQuery.mockReturnValue(new URLSearchParams("review=ai&status=draft"))
    globalThis.api.outline.listThreads.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.outline.listForeshadowing.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.outline.listReveals.mockResolvedValue({ items: [], total: 0 })

    const loaded = await stubs.options[0].load()

    expect(loaded).toMatchObject({
      projectId: "p1",
      subView: "threads",
      outlineGenerateReview: true,
      structureFilters: expect.objectContaining({ status: "draft" }),
    })
  })

  it("在篇章的 review=ai query 恢复结构化审阅页", async () => {
    stubs.appState.currentSubView = "arcs"
    stubs.router.getCurrentQuery.mockReturnValue(new URLSearchParams("review=ai&status=draft"))
    globalThis.api.outline.listArcs.mockResolvedValue({ items: [], total: 0 })

    const loaded = await stubs.options[0].load()

    expect(loaded).toMatchObject({
      projectId: "p1",
      subView: "arcs",
      outlineGenerateReview: true,
      structureFilters: expect.objectContaining({ status: "draft" }),
    })
  })

  it("在场景的 review=ai query 直接恢复结构化审阅页", async () => {
    stubs.appState.currentSubView = "scenes"
    stubs.router.getCurrentQuery.mockReturnValue(new URLSearchParams("review=ai"))

    const loaded = await stubs.options[0].load()

    expect(loaded).toEqual({
      projectId: "p1",
      subView: "scenes",
      outlineGenerateReview: true,
    })
  })
})
