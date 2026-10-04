/**
 * revisionHistory — 世界编辑历史的共享展示助手（阶段 0）。
 *
 * 原因词典、相对/绝对时间、写作进度与改动字段标签，供实体、世界书页面、模板、
 * 简介、地图历史与世界改动记录共用；`worldEntityHelpers.formatBatchTime` 的
 * 相对时间语义由本模块承载（formatBatchTime 只是转发）。
 */

/** §6.5 原因词典：作者看到的文字；键为各历史表的 revision_reason 内部取值。 */
export const REVISION_REASON_LABELS = {
  manual_update: "手动编辑",
  manual_promote: "采用为正式设定",
  focused_completion: "采用了 AI 补全",
  focused_completion_rollback: "撤销了 AI 补全",
  rollback: "恢复到旧版本",
  manual_delete: "移除了这个设定",
  redundant_alias_resolution: "整理了重复别名",
  spreadsheet_migration_rollback: "撤销了表格导入",
  ai_import: "导入时记录",
  manual_publish: "发布了这一版",
  legacy_create: "最初版本",
  legacy_update: "早期更新",
  create: "新建模板",
  update: "修改模板",
  restore: "恢复旧版模板",
}

/** 未知或缺失的原因一律显示「其他改动」，不暴露英文内部枚举。 */
export function revisionReasonLabel(reason) {
  if (!reason) return "其他改动"
  return REVISION_REASON_LABELS[reason] || "其他改动"
}

/** 实体改动字段（EntityRevisionField）的作者叫法；沿用现有界面用语（概要/作者秘密）。 */
export const ENTITY_REVISION_FIELD_LABELS = {
  entity_type: "类型",
  name: "名称",
  summary: "概要",
  public_info: "公开信息",
  hidden_truth: "作者秘密",
  aliases: "别名",
  content: "其他资料",
  importance: "重要程度",
  reveal_level: "揭示程度",
  status: "状态",
}

/** 世界书页面改动字段的作者叫法；后端未收录的键回落到 fallback。 */
export const PAGE_REVISION_FIELD_LABELS = {
  title: "标题",
  summary: "页面概览",
  overview: "页面概览",
  free_text: "正文",
  sections: "分区",
  category: "分类",
  visible_scope: "可见范围",
  status: "状态",
}

/** importance_level 内部枚举 → 作者语言。 */
export const IMPORTANCE_LEVEL_LABELS = {
  core: "核心设定",
  important: "重要设定",
  normal: "普通设定",
  temporary: "临时设定",
}

/** reveal_level 内部枚举 → 作者语言。 */
export const REVEAL_LEVEL_LABELS = {
  author_only: "仅作者可见",
  hinted: "已有暗示",
  revealed: "已揭示",
  fully_known: "完全揭晓",
}

/**
 * 相对时间：刚刚 / N 分钟前 / N 小时前 / 昨天 HH:MM / MM-DD HH:MM / YYYY-MM-DD HH:MM。
 * 语义与 worldEntityHelpers.formatBatchTime 一致（该函数转发到这里）。
 */
export function formatRelativeTime(isoStr) {
  if (!isoStr) return ""
  try {
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return String(isoStr)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const pad = (n) => String(n).padStart(2, "0")
    const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
    if (diffMs >= 0 && diffMs < 60 * 1000) return "刚刚"
    if (diffMs >= 0 && diffMs < 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 1000)))} 分钟前`
    if (diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 60 * 1000)))} 小时前`
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    if (
      d.getFullYear() === yesterday.getFullYear()
      && d.getMonth() === yesterday.getMonth()
      && d.getDate() === yesterday.getDate()
    ) {
      return `昨天 ${time}`
    }
    if (d.getFullYear() === now.getFullYear()) {
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
    }
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
  } catch {
    return String(isoStr)
  }
}

/** 绝对时间（悬停提示用）：YYYY-MM-DD HH:MM。 */
export function formatFullTime(isoStr) {
  if (!isoStr) return ""
  try {
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return String(isoStr)
    const pad = (n) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return String(isoStr)
  }
}

/**
 * 写作进度文案：NULL（功能上线前的旧记录）不显示也不伪造；0 = 尚无正文（动笔前）。
 * 含义是「保存时写到第几章」，不是剧情发生在第几章。
 */
export function formatWritingProgress(chapterIndex) {
  if (chapterIndex == null || chapterIndex === "") return ""
  const index = Number(chapterIndex)
  if (!Number.isFinite(index) || index < 0) return ""
  if (index === 0) return "动笔前"
  return `写到第 ${index} 章时`
}

/**
 * 改动字段标签列表 → 作者可读的一段文字；空列表/缺省返回 null（界面不显示该行）。
 * 未收录的键合并为一个 fallback 标签（默认「其他内容」），不暴露内部键名。
 */
export function formatChangedFields(fields, {
  labels = ENTITY_REVISION_FIELD_LABELS,
  fallback = "其他内容",
} = {}) {
  if (!Array.isArray(fields) || fields.length === 0) return null
  const out = []
  let hasUnknown = false
  for (const field of fields) {
    const label = labels[field]
    if (label) {
      if (!out.includes(label)) out.push(label)
    } else {
      hasUnknown = true
    }
  }
  if (hasUnknown && !out.includes(fallback)) out.push(fallback)
  return out.join("、")
}
