/**
 * 导入历史纯逻辑 — 从 projectView._renderImportHistory 移植。
 */
import { sanitizeTaskErrorMessage } from "../../../../shared/workflowProgress.js"

export const IMPORT_FAILURE_FALLBACK = "导入失败，请检查文件后重试。"
export const IMPORT_FAILURE_MESSAGE_MAX_LENGTH = 300

export const IMPORT_STATUS_LABELS = {
  done: "完成",
  processing: "处理中",
  failed: "失败",
  pending: "等待",
}

export function importStatusLabel(status) {
  return IMPORT_STATUS_LABELS[status] || status || ""
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

export function importFailureMessage(record) {
  if (record?.status !== "failed") return null

  const message = sanitizeTaskErrorMessage(record.error_message, "import")
  const normalized = typeof message === "string" ? message.replace(/\s+/g, " ").trim() : ""
  if (!normalized) return IMPORT_FAILURE_FALLBACK
  const characters = Array.from(normalized)
  if (characters.length <= IMPORT_FAILURE_MESSAGE_MAX_LENGTH) return normalized
  return `${characters.slice(0, IMPORT_FAILURE_MESSAGE_MAX_LENGTH - 1).join("")}…`
}
