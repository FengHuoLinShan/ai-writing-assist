const STRUCTURE_FIELDS = Object.freeze([
  ["knowledge_boundary", "知识边界"],
  ["entry_state", "入场状态"],
  ["exit_state", "离场状态"],
  ["outcome", "本场结果"],
  ["cost", "付出代价"],
  ["continuity", "连续性"],
  ["new_fact_candidates", "待确认新事实"],
])

function readable(value) {
  if (typeof value === "string" || typeof value === "number") return String(value).trim()
  if (Array.isArray(value)) return value.map(readable).filter(Boolean).join("、")
  if (!value || typeof value !== "object") return ""
  return ["summary", "description", "text", "state", "label", "name"]
    .map((key) => readable(value[key]))
    .find(Boolean) || ""
}

export function sceneStructureSummary(scene) {
  const meta = scene?.structure_meta && typeof scene.structure_meta === "object"
    ? scene.structure_meta
    : {}
  const fixed = [
    ["目标", scene?.goal],
    ["核心冲突", scene?.core_conflict],
    ["必须发生", scene?.must_happen],
    ["不能发生", scene?.must_not_happen],
    ["情绪节拍", scene?.emotional_beat],
  ]
  return [...fixed, ...STRUCTURE_FIELDS.map(([key, label]) => [label, meta[key]])]
    .map(([label, value]) => ({ label, value: readable(value) }))
    .filter((item) => item.value)
}

export function roleKnowledgeItems(lens) {
  const knowledge = lens?.role_visible_knowledge || {}
  return [...(knowledge.characters || []), ...(knowledge.world_entities || [])]
    .map((item) => ({
      label: readable(item?.name || item?.title) || "未命名资料",
      value: readable(
        item?.misconception
        || item?.known_content
        || item?.public_info
        || item?.summary
        || item?.current_state
        || item?.current_goal
        || item?.current_emotion
        || item?.stance
        || item?.role,
      ) || "已在角色可见范围内",
    }))
}

export function worldStateItems(lens) {
  return (lens?.scene_world_state?.items || []).map((item) => ({
    label: readable(item?.dimension_label || item?.dimension) || "状态",
    value: readable(item?.display_summary) || (item?.gap_reason ? "暂无可靠状态" : "已记录"),
  }))
}
