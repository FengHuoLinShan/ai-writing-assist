/**
 * 作者偏好表单纯逻辑 — 从 views/settings/shared/authorPreferencesForm.js
 * 与 constants.js 移植；数据来源由 DOM 改为响应式表单对象。
 */

export const EDITOR_FONT_OPTIONS = ["system", "serif", "sans", "mono"]

const EDITOR_FONT_LABELS = {
  system: "跟随系统",
  serif: "衬线",
  sans: "无衬线",
  mono: "等宽",
}

function safeDisplayValue(value) {
  if (value === null || value === undefined) return value
  try {
    return String(value) || "（空值）"
  } catch {
    return "（未知值）"
  }
}

export function editorFontDisplayLabel(value) {
  if (value === null || value === undefined) return value
  return Object.hasOwn(EDITOR_FONT_LABELS, value)
    ? EDITOR_FONT_LABELS[value]
    : safeDisplayValue(value)
}

export function defaultFocusModeDisplayLabel(value) {
  if (value === null || value === undefined) return value
  if (value === true) return "开启"
  if (value === false) return "关闭"
  return safeDisplayValue(value)
}

// 全局作者偏好硬默认（前端 fallback，与后端 AUTHOR_PREFS_DEFAULTS 对齐）
export const AUTHOR_PREFS_DEFAULTS = {
  daily_goal: null,
  editor_font: "system",
  default_focus_mode: false,
}

/** 对应原 readAuthorPreferencesForm。daily_goal 为原始输入字符串。 */
export function buildAuthorPrefsPayload(form) {
  const raw = String(form.daily_goal ?? "").trim()
  return {
    daily_goal: raw ? Number(raw) : null,
    editor_font: form.editor_font || null,
    default_focus_mode: Boolean(form.default_focus_mode),
  }
}

export function validateAuthorPreferences(prefs) {
  if (
    prefs.daily_goal != null &&
    (!Number.isInteger(prefs.daily_goal) || prefs.daily_goal < 0 || prefs.daily_goal > 100000)
  ) {
    return { ok: false, message: "日更目标必须是 0-100000 的整数" }
  }
  return { ok: true }
}

/** 原 renderResetFor：project/未配置来源才显示"恢复到全局默认"按钮。 */
export function isResettableSource(srcObj) {
  if (!srcObj) return false
  return srcObj.source !== "global" && srcObj.source !== "system"
}

/**
 * 由 effective-author-preferences 响应构造表单初值。
 * editor_font 回退 "system"：与 vanilla 一致——DOM select 无选中项时读取结果
 * 即首个 option 的值（EDITOR_FONT_OPTIONS[0]）。
 */
export function authorFormFromEffective(effectiveData) {
  const dailyGoal = effectiveData?.daily_goal?.value
  return {
    daily_goal: dailyGoal === null || dailyGoal === undefined ? "" : String(dailyGoal),
    editor_font: effectiveData?.editor_font?.value || EDITOR_FONT_OPTIONS[0],
    default_focus_mode: Boolean(effectiveData?.default_focus_mode?.value),
  }
}

/** 由全局作者偏好对象构造表单初值（全局设置页，无 source 概念）。 */
export function authorFormFromDefaults(prefs) {
  const dailyGoal = prefs?.daily_goal
  return {
    daily_goal: dailyGoal === null || dailyGoal === undefined ? "" : String(dailyGoal),
    editor_font: prefs?.editor_font || EDITOR_FONT_OPTIONS[0],
    default_focus_mode: Boolean(prefs?.default_focus_mode),
  }
}
