import { describe, expect, it, vi } from "vitest"

import {
  createMapTimelineState,
  drawTimelineProjection,
  filterTimelineItems,
  formatMapDynamicValue,
  mapDynamicNormalizationLabel,
  normalizeMapStateAtResponse,
  normalizeMapTimelineResponse,
  timelineAnchorPoint,
  timelineProjectionSignature,
} from "../views/mapTimelineProjection.js"

function canvasContext() {
  return {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    setLineDash: vi.fn(),
    arc: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
  }
}

describe("mapTimelineProjection", () => {
  it("normalizes non-contiguous Scene stops without inventing intermediate Scenes", () => {
    const result = normalizeMapTimelineResponse({
      scenes: [{ scene_index: 2, delta_count: 1 }, { scene_index: 9, delta_count: 1 }],
      deltas: [{ delta_id: "d1", scene_index: 9, track: "journey" }],
      candidates: [{ id: "c1", scene_index: 15, dynamic_type: "status" }],
      untyped_facts: [{ id: "legacy", scene_index: 9 }],
    })

    expect(result.scenes.map((scene) => scene.scene_index)).toEqual([2, 9, 15])
    expect(result.scenes).not.toContainEqual(expect.objectContaining({ scene_index: 3 }))
    expect(result.untyped_facts).toEqual([{ id: "legacy", scene_index: 9 }])
  })

  it("keeps candidates outside formal state and infers tracks for old records", () => {
    const timeline = normalizeMapTimelineResponse({
      candidates: [{ id: "candidate", scene_index: 3, dynamic_type: "location" }],
    })
    const stateAt = normalizeMapStateAtResponse({
      scene_index: 3,
      items: [{ target_name: "沈砚", dynamic_type: "status", normalized_value: { type: "status" } }],
    })
    const selected = { ...createMapTimelineState().selectedTracks, status: false }

    expect(stateAt.items).toHaveLength(1)
    expect(stateAt.items).not.toContainEqual(expect.objectContaining({ id: "candidate" }))
    expect(filterTimelineItems(timeline.candidates, { journey: true, world: false })).toHaveLength(1)
    expect(filterTimelineItems(stateAt.items, selected)).toHaveLength(0)
  })

  it("formats typed and legacy states with author-facing labels", () => {
    expect(formatMapDynamicValue({ type: "status", field_key: "戒备", value: "加强" }))
      .toBe("戒备：加强")
    expect(formatMapDynamicValue({ type: "crisis", crisis_key: "洪水", severity: 4 }))
      .toBe("洪水 · 强度 4")
    expect(mapDynamicNormalizationLabel("legacy_normalized")).toBe("旧记录已兼容")
    expect(mapDynamicNormalizationLabel("untyped")).toBe("尚未结构化")
  })

  it("invalidates the projection signature on explicit reloads and candidate visibility", () => {
    const projection = {
      projectionToken: "load-1",
      sceneIndex: 4,
      stateItems: [{ source_fact_ids: ["fact-1"] }],
      deltas: [{ delta_id: "delta-1" }],
      candidates: [{ id: "candidate-1" }],
      includeCandidates: false,
      selectedTracks: { journey: true },
    }

    expect(timelineProjectionSignature({ ...projection, projectionToken: "load-2" }))
      .not.toBe(timelineProjectionSignature(projection))
    expect(timelineProjectionSignature({ ...projection, includeCandidates: true }))
      .not.toBe(timelineProjectionSignature(projection))
  })

  it("includes stable candidate content and position only while candidate preview is enabled", () => {
    const base = {
      projectionToken: "canonical-token",
      sceneIndex: 4,
      stateItems: [],
      deltas: [],
      includeCandidates: true,
      selectedTracks: { territory: true },
    }
    const first = {
      id: "candidate-1",
      scene_index: 4,
      dynamic_type: "boundary",
      spatial_anchor: { hex_q: 2, hex_r: 3 },
      normalized_value: {
        schema_version: 1,
        type: "boundary",
        controller_entity_id: "entity-1",
        hexes: [{ hex_q: 2, hex_r: 3 }],
      },
    }
    const reordered = {
      normalized_value: {
        hexes: [{ hex_r: 3, hex_q: 2 }],
        controller_entity_id: "entity-1",
        type: "boundary",
        schema_version: 1,
      },
      spatial_anchor: { hex_r: 3, hex_q: 2 },
      dynamic_type: "boundary",
      scene_index: 4,
      id: "candidate-1",
    }
    const moved = {
      ...first,
      spatial_anchor: { hex_q: 7, hex_r: 8 },
    }
    const changed = {
      ...first,
      normalized_value: {
        ...first.normalized_value,
        hexes: [{ hex_q: 5, hex_r: 6 }],
      },
    }

    expect(timelineProjectionSignature({ ...base, candidates: [reordered] }))
      .toBe(timelineProjectionSignature({ ...base, candidates: [first] }))
    expect(timelineProjectionSignature({ ...base, candidates: [moved] }))
      .not.toBe(timelineProjectionSignature({ ...base, candidates: [first] }))
    expect(timelineProjectionSignature({ ...base, candidates: [changed] }))
      .not.toBe(timelineProjectionSignature({ ...base, candidates: [first] }))
    expect(timelineProjectionSignature({
      ...base,
      candidates: [{ ...first, evidence: "long read-only evidence", source_ref: "source-2" }],
    })).toBe(timelineProjectionSignature({ ...base, candidates: [first] }))
    expect(timelineProjectionSignature({ ...base, includeCandidates: false, candidates: [moved] }))
      .toBe(timelineProjectionSignature({ ...base, includeCandidates: false, candidates: [first] }))
  })

  it("draws canonical movement and only draws candidates after explicit opt-in", () => {
    const ctx = canvasContext()
    const projection = {
      sceneIndex: 8,
      selectedTracks: { journey: true, world: true },
      stateItems: [{ track: "journey", spatial_anchor: { hex_q: 2, hex_r: 2 } }],
      deltas: [{
        delta_id: "d1",
        track: "journey",
        scene_index: 8,
        spatial_anchor_before: { hex_q: 1, hex_r: 1 },
        spatial_anchor_after: { hex_q: 2, hex_r: 2 },
      }],
      candidates: [{ id: "c1", scene_index: 8, spatial_anchor: { hex_q: 3, hex_r: 3 } }],
      includeCandidates: false,
    }

    drawTimelineProjection(ctx, projection, { hexSize: 20 })
    expect(ctx.setLineDash).not.toHaveBeenCalledWith([5, 4])

    drawTimelineProjection(ctx, { ...projection, includeCandidates: true }, { hexSize: 20 })
    expect(ctx.setLineDash).toHaveBeenCalledWith([5, 4])
    expect(ctx.lineTo).toHaveBeenCalled()
  })

  it("culls timeline hexes outside the current viewport", () => {
    const ctx = canvasContext()
    drawTimelineProjection(ctx, {
      sceneIndex: 1,
      selectedTracks: { territory: true },
      stateItems: [{
        track: "territory",
        normalized_value: {
          type: "boundary",
          hexes: [{ hex_q: 1, hex_r: 1 }, { hex_q: 99, hex_r: 99 }],
        },
      }],
      deltas: [],
      candidates: [],
    }, {
      hexSize: 20,
      isVisible: (point) => point.q < 10,
    })

    expect(ctx.arc).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["boundary", "territory"],
    ["terrain", "world"],
    ["crisis", "crisis"],
  ])("draws visible %s candidate footprint hexes with candidate styling", (type, track) => {
    const ctx = canvasContext()
    drawTimelineProjection(ctx, {
      sceneIndex: 6,
      selectedTracks: { [track]: true },
      stateItems: [],
      deltas: [],
      candidates: [{
        id: `${type}-candidate`,
        scene_index: 6,
        dynamic_type: type,
        normalized_value: {
          type,
          hexes: [{ hex_q: 2, hex_r: 3 }, { hex_q: 99, hex_r: 99 }],
        },
      }],
      includeCandidates: true,
    }, {
      hexSize: 20,
      isVisible: (point) => point.q < 10,
    })

    expect(ctx.arc).toHaveBeenCalledTimes(1)
    expect(ctx.setLineDash).toHaveBeenCalledWith([5, 4])

    const hiddenCtx = canvasContext()
    drawTimelineProjection(hiddenCtx, {
      sceneIndex: 6,
      selectedTracks: { [track]: false },
      stateItems: [],
      deltas: [],
      candidates: [{
        id: `${type}-candidate`,
        scene_index: 6,
        dynamic_type: type,
        normalized_value: { type, hexes: [{ hex_q: 2, hex_r: 3 }] },
      }],
      includeCandidates: true,
    }, { hexSize: 20 })
    expect(hiddenCtx.arc).not.toHaveBeenCalled()
  })

  it("treats an explicit null spatial anchor as an unpositioned state", () => {
    expect(timelineAnchorPoint(null)).toBeNull()

    const ctx = canvasContext()
    expect(() => drawTimelineProjection(ctx, {
      sceneIndex: 1,
      selectedTracks: { status: true, world: true },
      stateItems: [{ track: "status", spatial_anchor: null }],
      deltas: [],
      candidates: [{
        id: "legacy-candidate",
        scene_index: 1,
        dynamic_type: "legacy_unknown",
        spatial_anchor: null,
        normalized_value: null,
      }],
      includeCandidates: true,
    }, { hexSize: 20 })).not.toThrow()
    expect(ctx.arc).not.toHaveBeenCalled()
  })
})
