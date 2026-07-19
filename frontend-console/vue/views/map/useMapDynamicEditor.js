import { reactive } from "vue"
import { getAppState, getToast } from "../../bridge/index.js"

export const MAP_DYNAMIC_TYPES = Object.freeze([
  ["location", "人物/对象位置"], ["route_state", "线路状态"], ["status", "对象状态"],
  ["boundary", "势力范围"], ["resource", "资源控制"], ["terrain", "地形变化"],
  ["crisis", "危机扩散"], ["semantic", "语义关联"],
])
const SUPPORTED = new Set(MAP_DYNAMIC_TYPES.map(([value]) => value))

export function canonicalDynamicType(value) {
  const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_")
  return ({ movement: "location", position: "location", position_change: "location", journey: "location", route: "route_state", path_state: "route_state", state: "status", territory: "boundary", territory_change: "boundary", resource_control: "resource", terrain_change: "terrain", crisis_spread: "crisis", semantic_relation: "semantic", movement_explanation: "semantic" })[normalized] || normalized
}

export function parseDynamicHexes(raw) {
  const byKey = new Map()
  for (const token of String(raw || "").split(/[\n;]+/).map((item) => item.trim()).filter(Boolean)) {
    const match = token.match(/^(\d+)\s*,\s*(\d+)$/)
    if (!match) throw new Error(`范围格“${token}”格式不正确，应为 q,r`)
    const hex = { hex_q: Number(match[1]), hex_r: Number(match[2]) }
    byKey.set(`${hex.hex_q},${hex.hex_r}`, hex)
    if (byKey.size > 20000) throw new Error("范围格一次最多 20,000 个")
  }
  return [...byKey.values()].sort((a, b) => a.hex_q - b.hex_q || a.hex_r - b.hex_r)
}

export function useMapDynamicEditor({ projectId, getViewport, getEntities, getLocations, onSaveObservation, onFactStatus }) {
  const toast = getToast()
  const state = reactive({
    open: false, saving: false, item: null, isFact: false, legacy: false,
    status: "candidate", targetName: "", targetEntityId: "", targetEntityType: "",
    entities: [], paths: [], value: {}, scalarType: "string", hexText: "", error: null,
  })
  const owns = () => state.open && getAppState()?.currentProjectId === projectId

  function proposalToTyped(item, proposal, entities, paths) {
    const entityId = (name, types = null) => entities.find((entity) => entity.name === name && (!types || types.includes(entity.entityType)))?.id || null
    if (["character_location", "event_location"].includes(proposal?.proposal_type)) return { schema_version: 1, type: "location", location_entity_id: entityId(proposal.location_name, ["location"]), path_id: null, movement_mode: proposal.movement_mode || "unknown", state: proposal.state || (proposal.proposal_type === "event_location" ? "occurred" : "present") }
    if (proposal?.proposal_type === "route_state") return { schema_version: 1, type: "route_state", path_id: paths.find((path) => path.name === proposal.path_name)?.id || null, state: proposal.state || "open", reason: proposal.reason || null }
    if (proposal?.proposal_type === "boundary") return { schema_version: 1, type: "boundary", controller_entity_id: entityId(proposal.controller_name, ["organization", "faction"]) || item.target_entity_id || null, hexes: [] }
    return proposal
  }

  function open(item) {
    const viewportEntities = [
      ...(getEntities?.() || []),
      ...(getViewport?.()?.timelineEntityOptions?.() || []),
    ]
    const byId = new Map([...viewportEntities, ...(getLocations?.() || []).map((entry) => ({ id: entry.id, name: entry.name, entityType: "location" }))].filter((entry) => entry?.id).map((entry) => [entry.id, entry]))
    state.entities = [...byId.values()]
    state.paths = getViewport?.()?.timelinePathOptions?.() || []
    state.item = item
    state.isFact = item.item_kind === "fact"
    state.status = state.isFact ? item.fact_status || "confirmed" : item.review_state || "candidate"
    state.targetName = item.target_name || item.title || ""
    state.targetEntityId = item.target_entity_id || ""
    state.targetEntityType = item.target_entity_type || ""
    const proposal = item.proposal_value || (item.value_json?.payload_kind === "proposal" ? item.value_json : null)
    const raw = item.normalized_value || (proposal ? proposalToTyped(item, proposal, state.entities, state.paths) : item.value_json) || {}
    const type = canonicalDynamicType(raw.type)
    state.legacy = !state.isFact && !(raw.schema_version === 1 && SUPPORTED.has(type))
    state.value = state.legacy ? {} : JSON.parse(JSON.stringify({ ...raw, type }))
    const scalar = state.value?.value
    state.scalarType = scalar === null ? "null" : typeof scalar === "number" ? "number" : typeof scalar === "boolean" ? "boolean" : "string"
    state.hexText = (state.value?.hexes || []).map((hex) => `${hex.hex_q},${hex.hex_r}`).join("\n")
    state.error = null
    state.open = true
  }
  function close() { state.open = false; state.item = null }

  function typedValue() {
    const value = JSON.parse(JSON.stringify(state.value || {}))
    value.schema_version = 1
    value.type = canonicalDynamicType(value.type)
    if (!SUPPORTED.has(value.type)) throw new Error("不支持的结构化动态类型")
    const required = (current, label) => { if (current === null || current === undefined || String(current).trim() === "") throw new Error(`请填写${label}`); return current }
    if (value.type === "location") value.state = required(value.state, "位置状态")
    if (value.type === "route_state") { value.path_id = required(value.path_id, "线路"); value.state ||= "open"; value.reason ||= null }
    if (value.type === "status") {
      value.field_key = required(value.field_key, "状态字段")
      const raw = value.value
      if (state.scalarType === "null") value.value = null
      else if (state.scalarType === "boolean") { const normalized = String(raw).toLowerCase(); if (!["true", "false", "是", "否"].includes(normalized)) throw new Error("状态值应填写 true/false 或 是/否"); value.value = ["true", "是"].includes(normalized) }
      else if (state.scalarType === "number") { const number = Number(raw); if (raw === "" || !Number.isFinite(number)) throw new Error("状态数字必须是有限数值"); value.value = number }
      else value.value = String(raw ?? "")
    }
    if (["boundary", "terrain", "crisis"].includes(value.type)) value.hexes = parseDynamicHexes(state.hexText)
    if (value.type === "boundary") value.controller_entity_id = required(value.controller_entity_id, "控制者")
    if (value.type === "resource") { value.resource_key = required(value.resource_key, "资源名称/键"); if (value.amount !== null && value.amount !== "" && !Number.isFinite(Number(value.amount))) throw new Error("资源数量必须是有限数值"); value.amount = value.amount === "" || value.amount == null ? null : Number(value.amount); value.controller_entity_id ||= null; value.status ||= null }
    if (value.type === "terrain") { value.terrain_key = required(value.terrain_key, "地形名称/键"); value.state = required(value.state, "地形状态") }
    if (value.type === "crisis") { value.crisis_key = required(value.crisis_key, "危机名称/键"); value.severity = Number(value.severity); if (!Number.isInteger(value.severity) || value.severity < 0 || value.severity > 5) throw new Error("危机强度必须是 0–5 的整数") }
    if (value.type === "semantic") { value.relation_type = required(value.relation_type, "关联类型"); value.related_entity_ids = [...new Set(value.related_entity_ids || [])].slice(0, 200).sort(); value.summary ||= null }
    if (value.type === "location") return { schema_version: 1, type: value.type, location_entity_id: value.location_entity_id || null, path_id: value.path_id || null, movement_mode: value.movement_mode || "unknown", state: value.state }
    if (value.type === "route_state") return { schema_version: 1, type: value.type, path_id: value.path_id, state: value.state, reason: value.reason || null }
    if (value.type === "status") return { schema_version: 1, type: value.type, field_key: value.field_key, value: value.value }
    if (value.type === "boundary") return { schema_version: 1, type: value.type, controller_entity_id: value.controller_entity_id, hexes: value.hexes }
    if (value.type === "resource") return { schema_version: 1, type: value.type, resource_key: value.resource_key, controller_entity_id: value.controller_entity_id, status: value.status, amount: value.amount }
    if (value.type === "terrain") return { schema_version: 1, type: value.type, terrain_key: value.terrain_key, state: value.state, hexes: value.hexes }
    if (value.type === "crisis") return { schema_version: 1, type: value.type, crisis_key: value.crisis_key, severity: value.severity, hexes: value.hexes }
    return { schema_version: 1, type: value.type, relation_type: value.relation_type, related_entity_ids: value.related_entity_ids, summary: value.summary }
  }

  async function save() {
    if (!owns()) { toast("当前项目已切换，请重新打开编辑", "warning"); return false }
    state.saving = true
    state.error = null
    try {
      let success
      if (state.isFact) success = await onFactStatus?.(state.item, state.status)
      else {
        if (state.legacy) throw new Error("该记录仍使用旧版格式，当前只读保留")
        const entity = state.entities.find((item) => item.id === state.targetEntityId)
        success = await onSaveObservation?.(state.item, {
          expected_updated_at: state.item.updated_at,
          review_state: state.status,
          target_entity_id: state.targetEntityId || null,
          target_entity_type: entity?.entityType || state.targetEntityType || null,
          target_name: state.targetName.trim() || entity?.name || null,
          value_json: typedValue(),
        })
      }
      if (success) close()
      return Boolean(success)
    } catch (error) { state.error = error.message || "地图待处理项字段格式不正确"; toast(state.error, "error"); return false }
    finally { state.saving = false }
  }

  return { state, open, close, save, typedValue }
}
