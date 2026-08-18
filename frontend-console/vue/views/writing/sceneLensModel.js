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

export function sceneLensItems(value) {
  return (Array.isArray(value) ? value : [])
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      label: readable(item.label) || "未命名资料",
      summary: readable(item.summary) || "暂无可靠摘要",
      availability: item.availability === true,
    }))
}
