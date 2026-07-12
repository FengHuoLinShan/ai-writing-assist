const DEEP_IMPORT_GROUPS = [
  {
    id: "global",
    label: "Global",
    fields: [
      { key: "structured_timeout_grace_seconds", label: "结构化调用宽限（秒）", type: "int", min: 1, max: 600, value: 15 },
      { key: "structured_max_fix_attempts", label: "结构化修复次数", type: "int", min: 0, max: 10, value: 2 },
    ],
  },
  {
    id: "phase0",
    label: "Phase 0 Plan",
    fields: [
      { key: "target_input_chars", label: "窗口目标字数", type: "int", min: 1000, max: 500000, value: 72000 },
      { key: "max_chapters_per_window", label: "窗口最大章节", type: "int", min: 1, max: 100, value: 20 },
      { key: "right_overlap_chapters", label: "右侧重叠章节", type: "int", min: 0, max: 20, value: 2 },
      { key: "max_tokens_per_input_char", label: "Max tokens / 字符", type: "float", min: 0.05, max: 2, step: "0.01", value: 1.0 },
      { key: "min_max_tokens", label: "窗口最小 tokens", type: "int", min: 1, max: 200000, value: 13000 },
      { key: "max_max_tokens", label: "窗口最大 tokens", type: "int", min: 1, max: 200000, value: 32768 },
    ],
  },
  {
    id: "phase1a",
    label: "Phase 1A Scene Slicing",
    fields: [
      { key: "scene_slicing_timeout_seconds", label: "切分超时（秒）", type: "int", min: 1, max: 7200, value: 900 },
      { key: "structured_max_fix_attempts", label: "Schema 修复次数", type: "int", min: 0, max: 10, value: 1 },
    ],
  },
  {
    id: "phase1b",
    label: "Phase 1B",
    fields: [
      { key: "small_sample_max_tokens", label: "小样本 max tokens", type: "int", min: 1, max: 200000, value: 6144 },
      { key: "small_sample_timeout_seconds", label: "小样本超时（秒）", type: "int", min: 1, max: 3600, value: 90 },
      { key: "reducer_max_tokens", label: "Reducer max tokens", type: "int", min: 1, max: 200000, value: 128 },
      { key: "reducer_timeout_seconds", label: "Reducer 超时（秒）", type: "int", min: 1, max: 3600, value: 45 },
      { key: "compact_text_limit", label: "建议文本压缩字数", type: "int", min: 10, max: 5000, value: 180 },
      { key: "enrich_max_tokens", label: "Enrich max tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "enrich_timeout_seconds", label: "Enrich 超时（秒）", type: "int", min: 1, max: 7200, value: 300 },
      { key: "use_llm", label: "Fusion 使用 LLM", type: "nullableBool", value: "" },
    ],
  },
  {
    id: "phase1c",
    label: "Phase 1C Scene Fusion",
    fields: [
      { key: "auto_merge_confidence", label: "自动融合置信度", type: "float", min: 0, max: 1, step: "0.01", value: 0.92 },
      { key: "boundary_context_chars", label: "边界上下文字数", type: "int", min: 100, max: 100000, value: 2000 },
      { key: "concurrency", label: "边界审核并发", type: "int", min: 1, max: 100, value: 20 },
      { key: "decision_max_tokens", label: "决策 max tokens", type: "int", min: 1, max: 200000, value: 1024 },
      { key: "timeout_seconds", label: "Phase 1C 超时（秒）", type: "int", min: 1, max: 7200, value: 180 },
    ],
  },
  {
    id: "phase2",
    label: "Phase 2",
    fields: [
      { key: "world_timeout_seconds", label: "世界抽取超时（秒）", type: "int", min: 1, max: 7200, value: 900 },
      { key: "world_min_max_tokens", label: "世界抽取最小 tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_max_tokens", label: "世界抽取最大 tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_tokens_per_source_char", label: "世界 tokens / 字符", type: "float", min: 0.05, max: 2, step: "0.01", value: 1.0 },
      { key: "world_window_concurrency", label: "世界窗口并发", type: "int", min: 1, max: 100, value: 20 },
      { key: "parallel_scene_concurrency", label: "Scene 实体并发", type: "int", min: 1, max: 64, value: 20 },
      { key: "parallel_scene_max_tokens", label: "Scene 实体 max tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "parallel_provider_timeout_seconds", label: "Scene 实体 Provider 超时", type: "int", min: 1, max: 1800, value: 240 },
      { key: "parallel_llm_timeout_seconds", label: "Scene 实体总超时", type: "int", min: 1, max: 1800, value: 270 },
      { key: "batch_size_scenes", label: "Scene / batch", type: "int", min: 1, max: 200, value: 12 },
      { key: "batch_concurrency", label: "Batch 并发", type: "int", min: 1, max: 100, value: 6 },
      { key: "boundary_scenes", label: "边界 Scene 数", type: "int", min: 1, max: 20, value: 2 },
      { key: "boundary_supplement_enabled", label: "边界补提", type: "bool", value: false },
      { key: "boundary_total_timeout_seconds", label: "边界总超时（秒）", type: "float", min: 0.1, max: 7200, step: "0.1", value: 120 },
      { key: "alias_relation_total_timeout_seconds", label: "别名关系总超时（秒）", type: "int", min: 1, max: 7200, value: 240 },
      { key: "alias_relation_concurrency", label: "别名关系并发", type: "int", min: 1, max: 100, value: 4 },
      { key: "alias_relation_llm_timeout_seconds", label: "别名关系 LLM 超时", type: "int", min: 1, max: 3600, value: 120 },
      { key: "alias_relation_scene_char_limit", label: "Scene 文本上限", type: "int", min: 100, max: 100000, value: 3200 },
      { key: "alias_relation_entity_index_char_limit", label: "实体索引字数", type: "int", min: 100, max: 100000, value: 3600 },
      { key: "alias_relation_entity_index_fallback_limit", label: "实体索引兜底数", type: "int", min: 1, max: 1000, value: 30 },
      { key: "alias_relation_supplement_enabled", label: "别名关系补提", type: "bool", value: false },
      { key: "postprocess_timeout_seconds", label: "后处理超时（秒）", type: "float", min: 0.1, max: 3600, step: "0.1", value: 30 },
    ],
  },
  {
    id: "phase3",
    label: "Phase 3",
    fields: [
      { key: "structure_timeout_seconds", label: "结构分析超时（秒）", type: "int", min: 1, max: 7200, value: 300 },
      { key: "structure_max_tokens", label: "结构分析 max tokens", type: "int", min: 1, max: 200000, value: 32768 },
    ],
  },
]

export { DEEP_IMPORT_GROUPS }

export function renderDeepImportFields(settings) {
  return `
    <div class="llm-deep-import-grid">
      ${DEEP_IMPORT_GROUPS.map((group) => `
        <div class="deep-import-group">
          <h4>${group.label}</h4>
          <div class="form-row">
            ${group.fields.map((field) => renderDeepImportField(group.id, field, settings[group.id]?.[field.key])).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `
}

function renderDeepImportField(groupId, field, value) {
  const id = deepImportFieldId(groupId, field.key)
  if (field.type === "bool") {
    return renderBoolField(id, field.label, value)
  }
  if (field.type === "nullableBool") {
    return renderNullableBoolField(id, field.label, value)
  }
  return renderNumberField(id, field, value)
}

function renderBoolField(id, label, value) {
  return `
    <div class="form-group">
      <label for="${id}">${label}</label>
      <select class="form-input" id="${id}">
        <option value="false" ${value ? "" : "selected"}>关闭</option>
        <option value="true" ${value ? "selected" : ""}>开启</option>
      </select>
    </div>
  `
}

function renderNullableBoolField(id, label, value) {
  const selected = value === true ? "true" : value === false ? "false" : ""
  return `
    <div class="form-group">
      <label for="${id}">${label}</label>
      <select class="form-input" id="${id}">
        <option value="" ${selected === "" ? "selected" : ""}>自动</option>
        <option value="true" ${selected === "true" ? "selected" : ""}>开启</option>
        <option value="false" ${selected === "false" ? "selected" : ""}>关闭</option>
      </select>
    </div>
  `
}

function renderNumberField(id, field, value) {
  const step = field.step || (field.type === "float" ? "0.01" : "1")
  const displayValue = value === undefined || value === null ? "" : String(value)
  return `
    <div class="form-group">
      <label for="${id}">${field.label}</label>
      <input class="form-input" id="${id}" type="number" min="${field.min}" max="${field.max}" step="${step}" value="${displayValue}" />
    </div>
  `
}

export function deepImportFieldId(groupId, key) {
  return `deep-import-${groupId}-${key.replaceAll("_", "-")}`
}

export function readDeepImportFields() {
  const value = {}
  for (const group of DEEP_IMPORT_GROUPS) {
    value[group.id] = {}
    for (const field of group.fields) {
      const id = deepImportFieldId(group.id, field.key)
      const readResult = readField(field, id)
      if (!readResult.ok) return readResult
      value[group.id][field.key] = readResult.value ?? field.value
    }
  }
  return { ok: true, value }
}

function readField(field, id) {
  if (field.type === "bool") {
    return { ok: true, value: document.getElementById(id)?.value === "true" }
  }
  if (field.type === "nullableBool") {
    const raw = document.getElementById(id)?.value || ""
    return { ok: true, value: raw === "" ? null : raw === "true" }
  }
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return { ok: true, value: null }
  const num = Number(raw)
  const inRange = num >= field.min && num <= field.max
  const isFinite = Number.isFinite(num)
  const ok = field.type === "float" ? isFinite && inRange : Number.isInteger(num) && inRange
  if (!ok) {
    return { ok: false, error: `${field.label} 必须是 ${field.min}-${field.max} 的数字` }
  }
  return { ok: true, value: num }
}
