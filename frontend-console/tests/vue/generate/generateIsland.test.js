import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { loadGenerate } from "../../../vue/generateIsland.js"
import {
  emptyGenerateSession,
  generateSessionKey,
  writeGenerateSession,
} from "../../../vue/views/generate/generateSession.js"

function collection(items = []) {
  return { items, total: items.length }
}

function makeApi() {
  return {
    generate: { listPromptTemplates: vi.fn(async () => collection()) },
    context: { listActivationProfiles: vi.fn(async () => collection()) },
    world: {
      listBiblePages: vi.fn(async () => collection()),
      listBibleDrafts: vi.fn(async () => collection()),
      listBibleCategories: vi.fn(async () => collection()),
      listBiblePageTemplates: vi.fn(async () => collection()),
      listCharacters: vi.fn(async () => collection()),
      listEntities: vi.fn(async () => collection()),
      listSuggestions: vi.fn(async () => collection()),
    },
    outline: {
      listScenesOrdered: vi.fn(async () => []),
      listThreads: vi.fn(async () => collection()),
    },
    writing: { listChapters: vi.fn(async () => ({ chapters: [] })) },
  }
}

let api
let state
let router
let toast

beforeEach(() => {
  localStorage.clear()
  api = makeApi()
  state = { currentProjectId: "p1" }
  router = {
    getCurrentQuery: vi.fn(() => new URLSearchParams("tab=world")),
    registerView: vi.fn(),
  }
  toast = vi.fn()
  setBridgeOverrides({ api, state, router, toast })
})

afterEach(() => resetBridgeOverrides())

describe("generateIsland load contract", () => {
  it("restores a pending page proposal only for the current project, source, and target", async () => {
    router.getCurrentQuery.mockReturnValue(new URLSearchParams("tab=world&source_page_id=page-1&target=world_bible_page"))
    writeGenerateSession(
      generateSessionKey("p1", "page-1", "world_bible_page"),
      { ...emptyGenerateSession(), suggestionId: "suggestion-restore" },
    )
    api.world.listBiblePages.mockResolvedValue(collection([{ id: "page-1", version_number: 3 }]))
    api.world.listSuggestions.mockResolvedValue(collection([{
      id: "suggestion-restore",
      target_type: "world_bible_page_draft",
      payload_json: {
        operation: "replace_existing",
        target_page_id: "page-1",
        page: { title: "恢复的北境" },
      },
    }]))

    const props = await loadGenerate()

    expect(props.restoredWorldResult).toEqual(expect.objectContaining({
      kind: "world_bible_page",
      suggestion: expect.objectContaining({ id: "suggestion-restore" }),
    }))
    expect(api.world.listSuggestions).toHaveBeenCalledWith({
      novel_id: "p1",
      source_module: "world",
      review_group: "generation_center",
      status: "pending",
      skip: 0,
      limit: 200,
    })
  })

  it("paginates all active assets and uses the ordered active-scene seam", async () => {
    const firstCharacters = Array.from({ length: 50 }, (_, index) => ({ entity_id: `character-${index + 1}` }))
    const firstEntities = Array.from({ length: 50 }, (_, index) => ({ id: `entity-${index + 1}`, entity_type: "item" }))
    api.world.listCharacters.mockImplementation(async ({ skip }) => (
      skip === 0 ? { items: firstCharacters, total: 51 } : { items: [{ entity_id: "character-51" }], total: 51 }
    ))
    api.world.listEntities.mockImplementation(async ({ skip }) => (
      skip === 0 ? { items: firstEntities, total: 51 } : { items: [{ id: "entity-51", entity_type: "location" }], total: 51 }
    ))
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "scene-1", status: "canonical" },
      { id: "scene-2", status: "draft" },
    ])

    const props = await loadGenerate()

    expect(props.worldCharacters).toHaveLength(51)
    expect(props.worldEntities).toHaveLength(51)
    expect(props.worldScenes.map((item) => item.id)).toEqual(["scene-1", "scene-2"])
    expect(api.world.listCharacters).toHaveBeenNthCalledWith(2, { novel_id: "p1", skip: 50, limit: 50 })
    expect(api.world.listEntities).toHaveBeenNthCalledWith(2, { novel_id: "p1", display_state: "active", skip: 50, limit: 50 })
    expect(api.outline.listScenesOrdered).toHaveBeenCalledWith("p1")
  })

  it("does not reuse a foreign project session and downgrades a missing source page safely", async () => {
    writeGenerateSession(
      generateSessionKey("p1", "foreign-page", "world_bible_page"),
      { ...emptyGenerateSession(), suggestionId: "foreign-suggestion" },
    )
    writeGenerateSession(
      generateSessionKey("p2", null, "core_entity"),
      { ...emptyGenerateSession(), selectedTemplateId: "builtin:location" },
    )
    state.currentProjectId = "p2"
    router.getCurrentQuery.mockReturnValue(new URLSearchParams("tab=world&source_page_id=foreign-page&target=world_bible_page"))

    const props = await loadGenerate()

    expect(props.projectId).toBe("p2")
    expect(props.sourcePageId).toBeNull()
    expect(props.targetKind).toBe("core_entity")
    expect(props.sessionKey).toBe(generateSessionKey("p2", null, "core_entity"))
    expect(props.initialSession.selectedTemplateId).toBe("builtin:location")
    expect(props.restoredWorldResult).toBeNull()
    expect(api.world.listSuggestions).not.toHaveBeenCalled()
    expect(api.world.listBiblePages).toHaveBeenCalledWith({ novel_id: "p2" })
    expect(api.world.listCharacters).toHaveBeenCalledWith({ novel_id: "p2", skip: 0, limit: 50 })
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("foreign-suggestion"), expect.anything())
  })
})
