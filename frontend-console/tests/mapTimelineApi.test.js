import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import "../apiContracts.js"
import "../api.js"

describe("map timeline API wrappers", () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    window.api.clearCache()
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [] }),
    }))
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it("maps timeline options to the documented query contract", async () => {
    await window.api.world.getMapTimeline("map-1", "novel-1", {
      fromSceneIndex: 2,
      toSceneIndex: 9,
      focusEntityId: "entity-1",
      tracks: ["journey", "status"],
      includeCandidates: true,
      skip: 5,
      limit: 100,
    })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/world/maps/map-1/timeline?")
    expect(url).toContain("novel_id=novel-1")
    expect(url).toContain("from_scene_index=2")
    expect(url).toContain("to_scene_index=9")
    expect(url).toContain("focus_entity_id=entity-1")
    expect(url).toContain("tracks=journey%2Cstatus")
    expect(url).toContain("include_candidates=true")
    expect(url).toContain("skip=5")
    expect(url).toContain("limit=100")
    expect(init.method).toBe("GET")
  })

  it("always sends the required state-at Scene index", async () => {
    await window.api.world.getMapStateAt("map-1", "novel-1", 9, {
      focusEntityId: "entity-1",
      tracks: "journey",
    })

    const [url] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/world/maps/map-1/state-at?")
    expect(url).toContain("novel_id=novel-1")
    expect(url).toContain("scene_index=9")
    expect(url).toContain("focus_entity_id=entity-1")
    expect(url).toContain("tracks=journey")
  })
})
