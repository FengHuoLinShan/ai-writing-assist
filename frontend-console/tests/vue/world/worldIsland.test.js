import { beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

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
})
