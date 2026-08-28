import { beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

describe("world island deep links", () => {
  beforeEach(() => {
    resetBridgeOverrides()
    resetWorldSession()
  })

  it("formal relation page is restored from the URL", async () => {
    const listRelationships = vi.fn().mockResolvedValue({ items: [], total: 42 })
    setBridgeOverrides({
      api: { world: {
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships,
      } },
      state: { currentProjectId: "novel-1", currentSubView: "relations" },
      router: {
        getCurrentQuery: () => new URLSearchParams("page=2&q=雨夜"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    await loadWorld()

    expect(worldSession.relationListFilters).toEqual({ q: "雨夜", skip: 20, limit: 20 })
    expect(listRelationships).toHaveBeenCalledWith({
      novel_id: "novel-1",
      q: "雨夜",
      skip: 20,
      limit: 20,
      status: "canonical",
    })
  })

  it("formal alias page is restored from the URL", async () => {
    const listAliases = vi.fn().mockResolvedValue({ items: [], total: 42 })
    setBridgeOverrides({
      api: { world: {
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases,
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
      } },
      state: { currentProjectId: "novel-1", currentSubView: "aliases" },
      router: {
        getCurrentQuery: () => new URLSearchParams("page=2&q=旧名"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    await loadWorld()

    expect(worldSession.aliasListFilters).toEqual({ q: "旧名", skip: 20, limit: 20 })
    expect(listAliases).toHaveBeenCalledWith({
      novel_id: "novel-1",
      q: "旧名",
      skip: 20,
      limit: 20,
      display_state: "active",
    })
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
    expect(props.objectViewMode).toBe("table")
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

  it("processed review deep link does not reinsert an adopted entity into the queue", async () => {
    const api = {
      world: {
        getEntity: vi.fn().mockResolvedValue({ id: "entity-done", name: "已采用对象", status: "canonical" }),
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "review-objects" },
      router: { getCurrentQuery: () => new URLSearchParams("entity_id=entity-done&review_item=entity-done"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(props.candidates).toEqual([])
    expect(props.candidateTotal).toBe(0)
    expect(props.candidateLoadError).toBeNull()
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
      router: { getCurrentQuery: () => new URLSearchParams("group_id=group-50&q=%E4%B8%8D%E5%8C%B9%E9%85%8D&scene_index=999"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(fetchGroups).toHaveBeenNthCalledWith(1, expect.objectContaining({ novel_id: "novel-1", skip: 0, limit: 50 }))
    expect(fetchGroups).toHaveBeenNthCalledWith(2, expect.objectContaining({ novel_id: "novel-1", skip: 50, limit: 50 }))
    expect(fetchGroups.mock.calls[0][0]).not.toHaveProperty("q")
    expect(fetchGroups.mock.calls[0][0]).not.toHaveProperty("scene_index")
    expect(props[propName]).toEqual([{ group_id: "group-50", member_count: 2 }])
  })

  it("review filters pass object search and relation task flags without replacing global counts", async () => {
    const listEntities = vi.fn()
      .mockResolvedValueOnce({ total: 9 })
      .mockResolvedValueOnce({ items: [{ id: "entity-1" }], total: 1 })
    const api = {
      world: {
        listEntities,
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 8 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 7 }),
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "review" },
      router: { getCurrentQuery: () => new URLSearchParams("kind=objects&q=%E6%B8%AF"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(listEntities).toHaveBeenLastCalledWith(expect.objectContaining({ display_state: "review", q: "港" }))
    expect(props.reviewCounts).toEqual({ objects: 9, aliases: 8, relations: 7 })
    expect(props.candidateTotal).toBe(1)
  })

  it("relation task flags are passed as booleans to the grouped review request", async () => {
    const listRelationReviewGroups = vi.fn().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
    const api = {
      world: {
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationReviewGroups,
      },
    }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "novel-1", currentSubView: "review" },
      router: { getCurrentQuery: () => new URLSearchParams("kind=relations&relation_kind=epistemic&has_reverse_candidates=true&has_canonical_relation=true"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    await loadWorld()

    expect(listRelationReviewGroups).toHaveBeenCalledWith(expect.objectContaining({
      has_reverse_candidates: true,
      has_canonical_relation: true,
      relation_kind: "epistemic",
    }))
  })

  it("alias kind is passed to the grouped review request", async () => {
    const listAliasReviewGroups = vi.fn().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
    setBridgeOverrides({
      api: { world: {
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
        listAliasReviewGroups,
      } },
      state: { currentProjectId: "novel-1", currentSubView: "review" },
      router: { getCurrentQuery: () => new URLSearchParams("kind=aliases&alias_kind=identity&type_kind=custom"), registerView: vi.fn() },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    await loadWorld()

    expect(listAliasReviewGroups).toHaveBeenCalledWith(expect.objectContaining({ alias_kind: "identity", type_kind: "custom" }))
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

  it("loads active entities for the unified World Bible card home with URL filters", async () => {
    const listEntities = vi.fn(async (params) => (
      params.display_state === "active"
        ? { items: [{ id: "entity-1", name: "雾港", entity_type: "location" }], total: 61 }
        : { items: [], total: 0 }
    ))
    const api = {
      world: {
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        listEntities,
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
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
        getCurrentQuery: () => new URLSearchParams("kind=entity&type=location&q=%E9%9B%BE%E6%B8%AF"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "novel-1",
      display_state: "active",
      view_mode: "normal",
      q: "雾港",
      entity_type: "location",
      skip: 0,
      limit: 50,
    }))
    expect(props.worldCardFilters).toMatchObject({ kind: "entity", type: "location", q: "雾港", state: "", layout: "cards" })
    expect(props.bible).toMatchObject({ entities: [{ id: "entity-1" }], entityTotal: 61, entitiesLoadError: null })
  })

  it("loads an exact unified-library entity even when returning to page-only filters", async () => {
    const entity = { id: "entity-1", name: "沉钟港", entity_type: "location" }
    const api = {
      world: {
        listEntityTypes: vi.fn().mockResolvedValue({ items: [] }),
        getReviewTypeCatalog: vi.fn().mockResolvedValue({}),
        getEntity: vi.fn().mockResolvedValue(entity),
        listEntities: vi.fn().mockResolvedValue({ total: 0 }),
        listAliases: vi.fn().mockResolvedValue({ total: 0 }),
        listRelationships: vi.fn().mockResolvedValue({ total: 0 }),
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
        getCurrentQuery: () => new URLSearchParams("kind=page&state=working&layout=list&entity_id=entity-1"),
        registerView: vi.fn(),
      },
      toast: vi.fn(),
    })
    const { loadWorld } = await import("../../../vue/worldIsland.js")

    const props = await loadWorld()

    expect(api.world.getEntity).toHaveBeenCalledWith("entity-1", "novel-1")
    expect(props.worldCardFilters).toMatchObject({ kind: "page", state: "working", layout: "list" })
    expect(props.bible.entities).toEqual([entity])
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
