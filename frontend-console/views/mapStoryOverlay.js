/**
 * 剧情覆盖与冲突 view model。
 */

const EXPLANATION_LABELS = {
  teleport: "传送",
  secret_route: "秘道",
  vehicle: "飞舟",
  travel_omitted: "旅途省略",
  dream: "梦境",
  unknown: "移动待确认",
}

export function buildStoryOverlay({ facts = [], observations = [], onlyConflicts = false } = {}) {
  const items = [...facts, ...observations]
  const trajectories = []
  const conflicts = []
  for (const item of items) {
    if (item.dynamic_type === "movement_explanation") {
      const value = item.value_json || {}
      const label = EXPLANATION_LABELS[value.explanation_type] || "移动待确认"
      trajectories.push({
        id: item.id,
        label,
        status: "explained",
        target_entity_id: item.target_entity_id,
        from_location_id: value.from_location_id,
        to_location_id: value.to_location_id,
        from_scene_id: value.from_scene_id,
        to_scene_id: value.to_scene_id,
      })
    }
    if (item.dynamic_type === "map_conflict") {
      const value = item.value_json || {}
      const status = value.suppressed ? "suppressed" : (value.status || "open")
      const conflict = {
        id: item.id,
        label: value.conflict_type === "impossible_movement" ? "设定冲突" : "需解释",
        status,
        conflict_type: value.conflict_type || "unknown",
        reason: value.reason || item.evidence_text || "",
        target_entity_id: item.target_entity_id,
        from_location_id: value.from_location_id,
        to_location_id: value.to_location_id,
      }
      conflicts.push(conflict)
      if (!value.suppressed) {
        trajectories.push({
          ...conflict,
          status: status === "open" ? "conflict" : status,
        })
      }
    }
  }
  return {
    trajectories: onlyConflicts
      ? trajectories.filter((item) => item.status === "conflict")
      : trajectories,
    conflicts,
  }
}

export function createMovementExplanationPayload({
  targetEntityId,
  fromLocationId,
  toLocationId,
  fromSceneId,
  toSceneId,
  explanationType = "unknown",
  evidenceText = "",
} = {}) {
  return {
    target_entity_id: targetEntityId,
    dynamic_type: "movement_explanation",
    value_json: {
      explanation_type: explanationType,
      from_location_id: fromLocationId,
      to_location_id: toLocationId,
      from_scene_id: fromSceneId,
      to_scene_id: toSceneId,
    },
    evidence_text: evidenceText,
    review_state: "candidate",
  }
}

export function createMapConflictPayload({
  targetEntityId,
  conflictType = "impossible_movement",
  reason = "",
  suppressed = false,
  layoutOverrideReason = null,
} = {}) {
  return {
    target_entity_id: targetEntityId,
    dynamic_type: "map_conflict",
    value_json: {
      conflict_type: conflictType,
      status: "open",
      reason,
      suppressed,
      layout_override_reason: layoutOverrideReason,
    },
    evidence_text: reason,
    review_state: "conflicted",
  }
}
