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

const PROVENANCE_STATUS_LABELS = Object.freeze({
  exact: "有据",
  unverified: "来源待核实",
  conflict: "来源冲突",
})

const PROVENANCE_REF_INT_KEYS = ["chapter_index", "version_number", "start_offset", "end_offset"]

function provenanceRef(ref) {
  return {
    draftId: ref.draft_id,
    chapterIndex: ref.chapter_index,
    version: ref.version_number,
    contentMode: ref.content_mode || "working",
    startOffset: ref.start_offset,
    endOffset: ref.end_offset,
    sourceHash: typeof ref.source_hash === "string" ? ref.source_hash : "",
    rangeHash: typeof ref.range_hash === "string" ? ref.range_hash : "",
    // readEvidence 回开需要完整指纹；缺哈希时只展示区间，不提供回开。
    reopenable: /^[0-9a-f]{64}$/.test(ref.source_hash || "")
      && /^[0-9a-f]{64}$/.test(ref.range_hash || ""),
  }
}

/** fact 级 provenance → 作者侧下钻形态；形态不符返回 null，不冒充依据。 */
export function sceneFieldProvenance(value) {
  if (!value || typeof value !== "object") return null
  const status = typeof value.status === "string" ? value.status : ""
  if (!PROVENANCE_STATUS_LABELS[status]) return null
  const refs = (Array.isArray(value.source_refs) ? value.source_refs : [])
    .filter((ref) => ref && typeof ref === "object"
      && typeof ref.draft_id === "string" && ref.draft_id
      && PROVENANCE_REF_INT_KEYS.every((key) => Number.isInteger(ref[key])))
    .map(provenanceRef)
  return {
    status,
    statusLabel: PROVENANCE_STATUS_LABELS[status],
    field: typeof value.field === "string" ? value.field : "",
    eventId: value.event_id || null,
    refs,
  }
}

const HISTORY_DIMENSION_LABELS = Object.freeze({
  entities: "人物与对象",
  relations: "关系",
  locations: "空间与位置",
  knowledge: "知识边界",
  timeline: "时间顺序",
  causality: "因果与前提",
})

/** 历史 checkpoint 行 → 按记录批次分组的作者侧列表（保留返回顺序，新批次在前）。 */
export function sceneCheckpointHistoryGroups(items) {
  const groups = []
  const byKey = new Map()
  for (const item of Array.isArray(items) ? items : []) {
    if (!item || typeof item !== "object" || !item.checkpoint_id) continue
    const chapterIndex = Number.isInteger(item.chapter_index) ? item.chapter_index : null
    const version = Number.isInteger(item.version) ? item.version : null
    const key = `${chapterIndex ?? "无章"}:${version ?? "无序"}`
    let group = byKey.get(key)
    if (!group) {
      group = {
        key,
        chapterIndex,
        version,
        dimensionLabels: [],
        isCurrent: false,
        hasFieldProvenance: false,
        createdAt: null,
        checkpoints: [],
      }
      byKey.set(key, group)
      groups.push(group)
    }
    const dimensionLabel = HISTORY_DIMENSION_LABELS[item.dimension]
    if (dimensionLabel && !group.dimensionLabels.includes(dimensionLabel)) group.dimensionLabels.push(dimensionLabel)
    group.isCurrent = group.isCurrent || item.is_current === true
    group.hasFieldProvenance = group.hasFieldProvenance || item.has_field_provenance === true
    if (item.created_at && (!group.createdAt || item.created_at > group.createdAt)) group.createdAt = item.created_at
    group.checkpoints.push({ checkpointId: item.checkpoint_id, label: item.label })
  }
  return groups
}

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
        provenance: sceneFieldProvenance(field?.source?.provenance),
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
