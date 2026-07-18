/**
 * 导入历史纯逻辑 — 从 projectView._renderImportHistory 移植。
 */

export const IMPORT_STATUS_LABELS = {
  done: "完成",
  processing: "处理中",
  failed: "失败",
  pending: "等待",
}

export const IMPORT_STATUS_PILLS = {
  done: "pill-success",
  processing: "pill-warning",
  failed: "pill-error",
  pending: "",
}

export function importStatusLabel(status) {
  return IMPORT_STATUS_LABELS[status] || status || ""
}

export function importStatusPill(status) {
  return IMPORT_STATUS_PILLS[status] || ""
}

export function importStatusDot(status) {
  if (status === "done") return "success"
  if (status === "failed") return "error"
  if (status === "processing") return "warning"
  return "info"
}

export function importTimeText(record) {
  return record?.created_at ? new Date(record.created_at).toLocaleString("zh-CN") : ""
}
