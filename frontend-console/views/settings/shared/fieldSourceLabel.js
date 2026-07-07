import { SOURCE_LABELS } from "./constants.js"

export function renderSourceLabel({ source, value }) {
  const label = SOURCE_LABELS[source] || "未知"
  const cls = source === "project"
    ? "source-label source-project"
    : source === "global"
      ? "source-label source-global"
      : source === "unset"
        ? "source-label source-unset"
        : "source-label source-system"
  const valStr = value === null || value === undefined ? "—" : String(value)
  return `<span class="${cls}">${label}</span><small class="source-value">${valStr}</small>`
}

export function resettableField(fieldName, opts = {}) {
  const label = opts.label || "恢复到全局默认"
  return `<button class="btn btn-sm btn-link llm-reset-field" data-field="${fieldName}" type="button">${label}</button>`
}