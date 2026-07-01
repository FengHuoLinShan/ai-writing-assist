import { describe, expect, it } from "vitest"
import {
  buildStoryOverlay,
  createMapConflictPayload,
  createMovementExplanationPayload,
} from "../views/mapStoryOverlay.js"

describe("mapStoryOverlay", () => {
  it("labels confirmed teleport movement as 传送", () => {
    const overlay = buildStoryOverlay({
      facts: [{
        id: "fact1",
        dynamic_type: "movement_explanation",
        target_entity_id: "char1",
        value_json: {
          explanation_type: "teleport",
          from_location_id: "a",
          to_location_id: "b",
        },
      }],
    })

    expect(overlay.trajectories[0]).toMatchObject({
      label: "传送",
      status: "explained",
      from_location_id: "a",
      to_location_id: "b",
    })
  })

  it("shows unsuppressed map conflict as warning trajectory", () => {
    const overlay = buildStoryOverlay({
      observations: [{
        id: "obs1",
        dynamic_type: "map_conflict",
        value_json: {
          conflict_type: "impossible_movement",
          status: "open",
          reason: "短时间跨越万里且无传送解释",
        },
      }],
    })

    expect(overlay.trajectories[0]).toMatchObject({
      label: "设定冲突",
      status: "conflict",
    })
    expect(overlay.conflicts[0].reason).toContain("短时间")
  })

  it("keeps suppressed conflict in inspector list but removes warning trajectory", () => {
    const overlay = buildStoryOverlay({
      facts: [{
        id: "fact1",
        dynamic_type: "map_conflict",
        value_json: {
          conflict_type: "geo_fact_mismatch",
          suppressed: true,
          layout_override_reason: "readability",
        },
      }],
    })

    expect(overlay.trajectories).toEqual([])
    expect(overlay.conflicts[0]).toMatchObject({
      status: "suppressed",
      conflict_type: "geo_fact_mismatch",
    })
  })

  it("builds payloads for movement explanations and map conflicts", () => {
    expect(createMovementExplanationPayload({
      targetEntityId: "char1",
      fromLocationId: "a",
      toLocationId: "b",
      explanationType: "dream",
    })).toMatchObject({
      dynamic_type: "movement_explanation",
      value_json: { explanation_type: "dream" },
      review_state: "candidate",
    })
    expect(createMapConflictPayload({
      targetEntityId: "char1",
      conflictType: "impossible_movement",
      reason: "缺少解释",
    })).toMatchObject({
      dynamic_type: "map_conflict",
      review_state: "conflicted",
      value_json: { status: "open", reason: "缺少解释" },
    })
  })
})
