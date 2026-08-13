/**
 * 深度导入字段纯逻辑 — 从 views/settings/shared/deepImportFields.js 移植。
 * DEEP_IMPORT_GROUPS 为字段事实来源（默认值/min/max/类型），与原文件保持一致；
 * 表单读写由 DOM 改为响应式对象，校验语义不变。
 */

const DEEP_IMPORT_GROUPS = [
  {
    id: "global",
    label: "怎样让整理结果更稳定",
    summary: "处理所有整理步骤共用的等待与修复规则。",
    when: "模型偶尔返回不完整结果或响应较慢时再调整。",
    cost: "等待和修复次数越多，完成时间与模型用量越高。",
    fields: [
      { key: "structured_timeout_grace_seconds", label: "结构化调用宽限（秒）", type: "int", min: 1, max: 600, value: 60 },
      { key: "structured_max_fix_attempts", label: "结构化修复次数", type: "int", min: 0, max: 10, value: 2 },
    ],
  },
  {
    id: "phase0",
    label: "怎样切分场景",
    summary: "决定一次阅读多少正文，以及相邻章节如何衔接。",
    when: "场景跨章节、章节长短差异很大时调整。",
    cost: "窗口和上下文越大，细节更多，但更慢、更贵。",
    fields: [
      { key: "target_input_chars", label: "窗口目标字数", type: "int", min: 1000, max: 500000, value: 72000 },
      { key: "max_chapters_per_window", label: "窗口最大章节", type: "int", min: 1, max: 100, value: 20 },
      { key: "right_overlap_chapters", label: "右侧重叠章节", type: "int", min: 0, max: 20, value: 2 },
      { key: "max_tokens_per_input_char", label: "每字允许的输出量", type: "float", min: 0.05, max: 2, step: "0.01", value: 1.0 },
      { key: "min_max_tokens", label: "每次整理的最小输出量", type: "int", min: 1, max: 200000, value: 13000 },
      { key: "max_max_tokens", label: "每次整理的最大输出量", type: "int", min: 1, max: 200000, value: 32768 },
    ],
  },
  {
    id: "phase1a",
    label: "如何识别场景边界",
    summary: "决定识别场景切换时的等待和格式修复。",
    when: "场景边界常被漏掉或模型响应不稳定时调整。",
    cost: "更长等待和更多修复会延长导入。",
    fields: [
      { key: "scene_slicing_timeout_seconds", label: "切分超时（秒）", type: "int", min: 1, max: 7200, value: 900 },
      { key: "structured_max_fix_attempts", label: "结果格式修复次数", type: "int", min: 0, max: 10, value: 1 },
    ],
  },
  {
    id: "phase1b",
    label: "如何补全场景事实",
    summary: "为已识别场景补齐摘要、人物、地点和发生的事。",
    when: "希望场景卡更细，或导入耗时需要控制时调整。",
    cost: "输出和上下文越大，细节更多，但更慢、更贵。",
    fields: [
      { key: "small_sample_max_tokens", label: "小段正文的输出上限", type: "int", min: 1, max: 200000, value: 6144 },
      { key: "small_sample_timeout_seconds", label: "小样本超时（秒）", type: "int", min: 1, max: 3600, value: 420 },
      { key: "reducer_max_tokens", label: "摘要压缩的输出上限", type: "int", min: 1, max: 200000, value: 128 },
      { key: "reducer_timeout_seconds", label: "摘要压缩等待（秒）", type: "int", min: 1, max: 3600, value: 420 },
      { key: "compact_text_limit", label: "建议文本压缩字数", type: "int", min: 10, max: 5000, value: 180 },
      { key: "enrich_max_tokens", label: "场景补全的输出上限", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "enrich_timeout_seconds", label: "场景补全等待（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "use_llm", label: "由 AI 审核场景衔接", type: "nullableBool", value: "" },
    ],
  },
  {
    id: "phase1c",
    label: "何时合并相邻场景",
    summary: "审核相邻场景是否应视为同一段连续事件。",
    when: "章节边界常造成同一场景被拆开，或担心错误合并时调整。",
    cost: "审核范围、并发和等待越高，速度与限流风险会变化。",
    fields: [
      { key: "auto_merge_confidence", label: "自动融合置信度", type: "float", min: 0, max: 1, step: "0.01", value: 0.92 },
      { key: "boundary_context_chars", label: "边界上下文字数", type: "int", min: 100, max: 100000, value: 2000 },
      { key: "concurrency", label: "边界审核并发", type: "int", min: 1, max: 100, value: 20 },
      { key: "decision_max_tokens", label: "边界审核的输出上限（留空沿用默认）", type: "int", min: 1, max: 200000, value: null },
      { key: "timeout_seconds", label: "边界审核等待（秒）", type: "int", min: 1, max: 7200, value: 1200 },
    ],
  },
  {
    id: "phase2",
    label: "怎样整理人物、地点与关系",
    summary: "从确认后的场景中整理长期设定、别名和关系。",
    when: "需要更多世界细节，或遇到限流、遗漏时调整。",
    cost: "并发和批量越大越快，但更容易限流；上下文越大越贵。",
    fields: [
      { key: "world_timeout_seconds", label: "世界抽取超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "world_min_max_tokens", label: "设定整理的最小输出量", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_max_tokens", label: "设定整理的最大输出量", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "world_max_tokens_per_source_char", label: "每字允许的设定输出量", type: "float", min: 0.05, max: 2, step: "0.01", value: 1.0 },
      { key: "world_window_concurrency", label: "同时整理的正文窗口数", type: "int", min: 1, max: 100, value: 20 },
      { key: "parallel_scene_concurrency", label: "同时整理的场景数", type: "int", min: 1, max: 64, value: 25 },
      { key: "parallel_scene_max_tokens", label: "每个场景的对象整理上限", type: "int", min: 1, max: 200000, value: 32768 },
      { key: "parallel_provider_timeout_seconds", label: "单个场景的模型等待", type: "int", min: 1, max: 1800, value: 360 },
      { key: "parallel_llm_timeout_seconds", label: "场景对象整理总等待", type: "int", min: 1, max: 1800, value: 900 },
      { key: "batch_size_scenes", label: "每批场景数", type: "int", min: 1, max: 200, value: 12 },
      { key: "batch_concurrency", label: "同时处理的批次数", type: "int", min: 1, max: 100, value: 6 },
      { key: "boundary_scenes", label: "边界参考场景数", type: "int", min: 1, max: 20, value: 2 },
      { key: "boundary_supplement_enabled", label: "边界补提", type: "bool", value: false },
      { key: "boundary_total_timeout_seconds", label: "边界总超时（秒）", type: "float", min: 0.1, max: 7200, step: "0.1", value: 900 },
      { key: "alias_relation_total_timeout_seconds", label: "别名关系总超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "alias_relation_concurrency", label: "别名关系并发", type: "int", min: 1, max: 100, value: 4 },
      { key: "alias_relation_llm_timeout_seconds", label: "别名关系的模型等待", type: "int", min: 1, max: 3600, value: 600 },
      { key: "alias_relation_scene_char_limit", label: "每个场景的参考正文量", type: "int", min: 100, max: 100000, value: 3200 },
      { key: "alias_relation_entity_index_char_limit", label: "实体索引字数", type: "int", min: 100, max: 100000, value: 3600 },
      { key: "alias_relation_entity_index_fallback_limit", label: "实体索引兜底数", type: "int", min: 1, max: 1000, value: 30 },
      { key: "alias_relation_supplement_enabled", label: "别名关系补提", type: "bool", value: false },
      { key: "postprocess_timeout_seconds", label: "后处理超时（秒）", type: "float", min: 0.1, max: 3600, step: "0.1", value: 120 },
    ],
  },
  {
    id: "phase3",
    label: "怎样生成故事结构",
    summary: "基于已确认场景整理剧情线和结构建议。",
    when: "结构建议太简略或模型响应较慢时调整。",
    cost: "输出上限和等待越大，细节更多，但更慢、更贵。",
    fields: [
      { key: "structure_timeout_seconds", label: "结构分析超时（秒）", type: "int", min: 1, max: 7200, value: 1200 },
      { key: "structure_max_tokens", label: "结构分析的输出上限", type: "int", min: 1, max: 200000, value: 32768 },
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
      if (!readResult.ok) return { ...readResult, groupId: group.id, fieldKey: field.key }
      value[group.id][field.key] = readResult.value ?? field.value
    }
  }
  return { ok: true, value }
}
