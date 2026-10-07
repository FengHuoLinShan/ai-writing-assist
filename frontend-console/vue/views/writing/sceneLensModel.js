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
      stale: item.stale === true,
    }))
}

const OBJECT_FIELD_LABELS = Object.freeze({
  custody_holder: "保管人",
  custody_owner: "所有人",
  location: "所在",
  opening_key_id: "所需钥匙",
  opening_moon_phase: "所需月相",
  opening_passphrase: "所需口令",
  entity_type: "对象类型",
})

export function sceneObjectStates(value) {
  return (Array.isArray(value) ? value : [])
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      key: `${item.subject_id}:${item.label}`,
      label: readable(item.label) || "未命名对象",
      location: readable(item.location),
      locationSource: item.location_source,
      unknowns: (item.unknowns || []).map(readable).filter(Boolean),
      stale: item.stale === true,
      fields: (Array.isArray(item.fields) ? item.fields : []).map((field) => ({
        label: OBJECT_FIELD_LABELS[field?.field] || (/^[a-zA-Z_][a-zA-Z0-9_.]*$/.test(field?.field || "") ? "其他状态记录" : field?.field) || "状态",
        display: readable(field?.display),
        confirmed: field?.confidence === "confirmed",
        source: field?.source,
      })).filter((field) => field.display),
      knowledge: (Array.isArray(item.knowledge) ? item.knowledge : []).map((belief) => ({
        holder: readable(belief?.holder) || "某角色",
        text: readable(belief?.text),
        possiblyFalse: belief?.possibly_false === true,
        source: belief?.source,
      })).filter((belief) => belief.text),
    }))
    .filter((item) => item.fields.length || item.knowledge.length || item.location || item.unknowns.length)
}
