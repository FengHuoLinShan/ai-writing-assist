import { beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

describe("world island deep links", () => {
  beforeEach(() => {
    resetBridgeOverrides()
  })

  it("entity_id loads exactly one project entity", async () => {
    const entity = { id: "entity-1", name: "沉钟港", status: "canonical" }
    const api = {
      world: {
        getEntity: vi.fn().mockResolvedValue(entity),
        listEntities: vi.fn(),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getWorldReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityBatches: vi.fn().mockResolvedValue([]),
      },
    }
    const router = {
      getCurrentQuery: () => new URLSearchParams("entity_id=entity-1&q=沉钟港"),
      registerView: vi.fn(),
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "objects" },
      router,
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(api.world.getEntity).toHaveBeenCalledWith("entity-1", "novel-1")
    expect(api.world.listEntities).not.toHaveBeenCalledWith(expect.objectContaining({ display_state: "active" }))
    expect(props.entities).toEqual([entity])
  })

  it("passes the adoption package deep link only to the World Bible workspace", async () => {
    const api = {
      world: {
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listBiblePages: vi.fn().mockResolvedValue({ items: [] }),
        listBibleCategories: vi.fn().mockResolvedValue({ items: [] }),
        listBibleDrafts: vi.fn().mockResolvedValue({ items: [] }),
        getBibleSynopsis: vi.fn().mockResolvedValue(null),
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "bible" },
      router: {
        getCurrentQuery: () => new URLSearchParams("adoption_package_id=package-1"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(props.bibleDeepLink.adoptionPackageId).toBe("package-1")
  })

  it("starts independent shared and object requests concurrently", async () => {
    const entityTypes = deferred()
    const entityStarted = deferred()
    const entity = deferred()
    const api = {
      world: {
        listEntityTypes: vi.fn(() => entityTypes.promise),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
        getEntity: vi.fn(() => {
          entityStarted.resolve()
          return entity.promise
        }),
        listEntityBatches: vi.fn().mockResolvedValue([]),
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "objects" },
      router: { getCurrentQuery: () => new URLSearchParams("entity_id=entity-1"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const loading = loadWorld()
    expect(api.world.getReviewTypeCatalog).toHaveBeenCalledOnce()
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "novel-1", display_state: "review", skip: 0, limit: 1,
    })
    expect(api.world.listAliases).toHaveBeenCalledWith({
      novel_id: "novel-1", display_state: "review", skip: 0, limit: 1,
    })
    expect(api.world.listRelationships).toHaveBeenCalledWith({
      novel_id: "novel-1", status: "candidate", skip: 0, limit: 1,
    })
    entityTypes.resolve({ items: [] })
    await entityStarted.promise
    expect(api.world.getEntity).toHaveBeenCalledWith("entity-1", "novel-1")
    expect(api.world.listEntityBatches).toHaveBeenCalledWith({ novel_id: "novel-1" })
    expect(api.world.listEntities).not.toHaveBeenCalledWith(expect.objectContaining({ display_state: "active" }))
    entity.resolve({ id: "entity-1", name: "沉钟港" })

    await expect(loading).resolves.toMatchObject({ entities: [{ id: "entity-1" }] })
  })
})
