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

  it("review entity deep link bypasses the paginated candidate list", async () => {
    const entity = { id: "entity-21", name: "第二十一项", status: "candidate" }
    const api = {
      world: {
        getEntity: vi.fn().mockResolvedValue(entity),
        listEntities: vi.fn().mockResolvedValue({ total: 21 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "review-objects" },
      router: { getCurrentQuery: () => new URLSearchParams("entity_id=entity-21"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(api.world.getEntity).toHaveBeenCalledWith("entity-21", "novel-1")
    expect(props.candidates).toEqual([entity])
    expect(props.candidateTotal).toBe(1)
  })

  it.each([
    ["review-aliases", "listAliasReviewGroups", "aliasGroups"],
    ["review-relations", "listRelationReviewGroups", "relationGroups"],
  ])("%s deep link pages until it finds the exact group", async (subView, method, propName) => {
    const firstGroups = Array.from({ length: 50 }, (_, index) => ({ group_id: `group-${index}`, member_count: 1 }))
    const fetchGroups = vi.fn()
      .mockResolvedValueOnce({ groups: firstGroups, group_total: 51, item_total: 51 })
      .mockResolvedValueOnce({ groups: [{ group_id: "group-50", member_count: 2 }], group_total: 51, item_total: 52 })
    const api = {
      world: {
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
        [method]: fetchGroups,
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: subView },
      router: { getCurrentQuery: () => new URLSearchParams("group_id=group-50"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(fetchGroups).toHaveBeenNthCalledWith(1, expect.objectContaining({ novel_id: "novel-1", skip: 0, limit: 50 }))
    expect(fetchGroups).toHaveBeenNthCalledWith(2, expect.objectContaining({ novel_id: "novel-1", skip: 50, limit: 50 }))
    expect(props[propName]).toEqual([{ group_id: "group-50", member_count: 2 }])
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

  it("passes a focused conflict deep link to the World Bible workspace", async () => {
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
        getCurrentQuery: () => new URLSearchParams("open=conflicts&conflict_item_id=conflict-1"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(props.bibleDeepLink).toMatchObject({ openConflicts: true, conflictId: "conflict-1" })
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
