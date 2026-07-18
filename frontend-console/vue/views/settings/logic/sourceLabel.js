/**
 * 字段来源标签纯逻辑 — 从 views/settings/shared/fieldSourceLabel.js
 * 与 constants.js 移植；class 与文案契约保持一致。
 */

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

export function sourceLabelText(source) {
  return SOURCE_LABELS[source] || "未知"
}

export function sourceLabelClass(source) {
  switch (source) {
    case SOURCE_PROJECT:
      return "source-label source-project"
    case SOURCE_GLOBAL:
      return "source-label source-global"
    case SOURCE_UNSET:
      return "source-label source-unset"
    default:
      return "source-label source-system"
  }
}

export function formatSourceValue(value) {
  if (value === null || value === undefined) return "—"
  if (typeof value === "object") {
    try {
      return JSON.stringify(value)
    } catch {
      return "—"
    }
  }
  return String(value)
}
