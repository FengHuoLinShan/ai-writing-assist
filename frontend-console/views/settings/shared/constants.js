// Source labels match backend source enum (D1)
export const SOURCE_PROJECT = "project"
export const SOURCE_GLOBAL = "global"
export const SOURCE_SYSTEM = "system"
export const SOURCE_UNSET = "unset"

export const SOURCE_LABELS = {
  [SOURCE_PROJECT]: "已覆盖",
  [SOURCE_GLOBAL]: "继承全局",
  [SOURCE_SYSTEM]: "系统默认",
  [SOURCE_UNSET]: "未配置",
}

// 全局作者偏好硬默认（前端 fallback，与后端 AUTHOR_PREFS_DEFAULTS 对齐）
export const AUTHOR_PREFS_DEFAULTS = {
  daily_goal: null,
  editor_font: "system",
  default_focus_mode: false,
}

export const EDITOR_FONT_OPTIONS = ["system", "serif", "sans", "mono"]