/**
 * 深度导入字段纯逻辑 — 从 views/settings/shared/deepImportFields.js 移植。
 * DEEP_IMPORT_GROUPS 为字段事实来源（默认值/min/max/类型），与原文件保持一致；
 * 表单读写由 DOM 改为响应式对象，校验语义不变。
 */

const DEEP_IMPORT_GROUPS = [
  {
    id: "global",
    label: "Global",
    fields: [
      { key: "structured_timeout_grace_seconds", label: "结构化调用宽限（秒）", type: "int", min: 1, max: 600, value: 60 },
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
      { key: "small_sample_timeout_seconds", label: "小样本超时（秒）", type: "int", min: 1, max: 3600, value: 420 },
      { key: "reducer_max_tokens", label: "Reducer max tokens", type: "int", min: 1, max: 200000, value: 128 },
      { key: "reducer_timeout_seconds", label: "Reducer 超时（秒）", type: "int", min: 1, max: 3600, value: 420 },
      { key: "compact_text_limit", label: "建议文本压缩字数", type: "int", min: 10, max: 5000, value: 180 },
      { key: "enrich_max_tokens", label: "Enrich max tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "enrich_timeout_seconds", label: "Enrich 超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
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
      { key: "decision_max_tokens", label: "决策 max tokens（留空继承全局）", type: "int", min: 1, max: 200000, value: null },
      { key: "timeout_seconds", label: "Phase 1C 超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
    ],
  },
  {
    id: "phase2",
    label: "Phase 2",
    fields: [
      { key: "world_timeout_seconds", label: "世界抽取超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "world_min_max_tokens", label: "世界抽取最小 tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_max_tokens", label: "世界抽取最大 tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_tokens_per_source_char", label: "世界 tokens / 字符", type: "float", min: 0.05, max: 2, step: "0.01", value: 1.0 },
      { key: "world_window_concurrency", label: "世界窗口并发", type: "int", min: 1, max: 100, value: 20 },
      { key: "parallel_scene_concurrency", label: "Scene 实体并发", type: "int", min: 1, max: 64, value: 25 },
      { key: "parallel_scene_max_tokens", label: "Scene 实体 max tokens", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "parallel_provider_timeout_seconds", label: "Scene 实体 Provider 超时", type: "int", min: 1, max: 1800, value: 360 },
      { key: "parallel_llm_timeout_seconds", label: "Scene 实体总超时", type: "int", min: 1, max: 1800, value: 900 },
      { key: "batch_size_scenes", label: "Scene / batch", type: "int", min: 1, max: 200, value: 12 },
      { key: "batch_concurrency", label: "Batch 并发", type: "int", min: 1, max: 100, value: 6 },
      { key: "boundary_scenes", label: "边界 Scene 数", type: "int", min: 1, max: 20, value: 2 },
      { key: "boundary_supplement_enabled", label: "边界补提", type: "bool", value: false },
      { key: "boundary_total_timeout_seconds", label: "边界总超时（秒）", type: "float", min: 0.1, max: 7200, step: "0.1", value: 900 },
      { key: "alias_relation_total_timeout_seconds", label: "别名关系总超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "alias_relation_concurrency", label: "别名关系并发", type: "int", min: 1, max: 100, value: 4 },
      { key: "alias_relation_llm_timeout_seconds", label: "别名关系 LLM 超时", type: "int", min: 1, max: 3600, value: 600 },
      { key: "alias_relation_scene_char_limit", label: "Scene 文本上限", type: "int", min: 100, max: 100000, value: 3200 },
      { key: "alias_relation_entity_index_char_limit", label: "实体索引字数", type: "int", min: 100, max: 100000, value: 3600 },
      { key: "alias_relation_entity_index_fallback_limit", label: "实体索引兜底数", type: "int", min: 1, max: 1000, value: 30 },
      { key: "alias_relation_supplement_enabled", label: "别名关系补提", type: "bool", value: false },
      { key: "postprocess_timeout_seconds", label: "后处理超时（秒）", type: "float", min: 0.1, max: 3600, step: "0.1", value: 120 },
    ],
  },
  {
    id: "phase3",
    label: "Phase 3",
    fields: [
      { key: "structure_timeout_seconds", label: "结构分析超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "structure_max_tokens", label: "结构分析 max tokens", type: "int", min: 1, max: 200000, value: 32768 },
    ],
  },
]

export { DEEP_IMPORT_GROUPS }

export function deepImportFieldId(groupId, key) {
  return `deep-import-${groupId}-${key.replaceAll("_", "-")}`
}

function displayValue(value) {
  return value === undefined || value === null ? "" : String(value)
}

/**
 * 由 deep_import 覆盖对象（source=project 时的 value，否则 {}）构造表单初值：
 * 未覆盖字段回退到 DEEP_IMPORT_GROUPS 内嵌默认值；bool 统一为 "true"/"false"
 * 字符串，nullableBool 允许 ""（自动）。
 */
export function deepImportFormFromSettings(settings) {
  const configured = settings || {}
  const form = {}
  for (const group of DEEP_IMPORT_GROUPS) {
    form[group.id] = {}
    for (const field of group.fields) {
      const groupSettings = configured[group.id]
      const value = groupSettings && Object.hasOwn(groupSettings, field.key)
        ? groupSettings[field.key]
        : field.value
      if (field.type === "bool") {
        form[group.id][field.key] = value ? "true" : "false"
      } else if (field.type === "nullableBool") {
        form[group.id][field.key] = value === true ? "true" : value === false ? "false" : ""
      } else {
        form[group.id][field.key] = displayValue(value)
      }
    }
  }
  return form
}

function readFormField(field, raw) {
  if (field.type === "bool") {
    return { ok: true, value: raw === "true" }
  }
  if (field.type === "nullableBool") {
    return { ok: true, value: raw === "" || raw === null || raw === undefined ? null : raw === "true" }
  }
  const text = String(raw ?? "").trim()
  if (!text) return { ok: true, value: null }
  const num = Number(text)
  const inRange = num >= field.min && num <= field.max
  const ok = field.type === "float" ? Number.isFinite(num) && inRange : Number.isInteger(num) && inRange
  if (!ok) {
    return { ok: false, error: `${field.label} 必须是 ${field.min}-${field.max} 的数字` }
  }
  return { ok: true, value: num }
}

/** 对应原 readDeepImportFields：空值回退字段默认值，越界返回首个错误。 */
export function buildDeepImportPayload(form) {
  const value = {}
  for (const group of DEEP_IMPORT_GROUPS) {
    value[group.id] = {}
    for (const field of group.fields) {
      const readResult = readFormField(field, form?.[group.id]?.[field.key])
      if (!readResult.ok) return readResult
      value[group.id][field.key] = readResult.value ?? field.value
    }
  }
  return { ok: true, value }
}
