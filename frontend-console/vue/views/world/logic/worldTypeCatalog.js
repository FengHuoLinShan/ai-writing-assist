import {
  REVIEW_ALIAS_KIND_FALLBACK,
  REVIEW_ALIAS_TYPE_FALLBACK,
  REVIEW_RELATION_KIND_FALLBACK,
  REVIEW_RELATION_TYPE_FALLBACK,
} from "./worldQuery.js"

export const CUSTOM_DETAIL_TYPE_VALUE = "__custom_detail_type__"

export function catalogKindItems(catalog, domain) {
  const key = domain === "alias" ? "alias_kinds" : "relation_kinds"
  const fallback = domain === "alias" ? REVIEW_ALIAS_KIND_FALLBACK : REVIEW_RELATION_KIND_FALLBACK
  return catalog?.[key]?.length ? catalog[key] : fallback
}

export function catalogTypeItems(catalog, domain) {
  const key = domain === "alias" ? "alias_types" : "relation_types"
  const fallback = domain === "alias" ? REVIEW_ALIAS_TYPE_FALLBACK : REVIEW_RELATION_TYPE_FALLBACK
  return catalog?.[key]?.length ? catalog[key] : fallback
}

export function kindItem(catalog, domain, value) {
  return catalogKindItems(catalog, domain).find((item) => item.value === value) || null
}

export function kindLabel(catalog, domain, value) {
  return kindItem(catalog, domain, value)?.label || "待分类"
}

export function detailTypeLabel(catalog, domain, value) {
  if (!value) return "未填写"
  const known = catalogTypeItems(catalog, domain).find((item) => item.value === value)
  if (known?.label) return known.label
  return /[\u3400-\u9fff]/u.test(String(value)) ? String(value) : "自定义详细类型"
}

export function defaultKindForType(catalog, domain, value) {
  return catalogTypeItems(catalog, domain).find((item) => item.value === value)?.default_kind || ""
}

export function kindOrTypeDefault(catalog, domain, explicitKind, typeValue) {
  return explicitKind || defaultKindForType(catalog, domain, typeValue)
}

export function kindOptionsHtml(catalog, domain, selected, escapeHtml) {
  const esc = escapeHtml || ((value) => String(value))
  return [
    `<option value="">请选择分类</option>`,
    ...catalogKindItems(catalog, domain).map((item) => (
      `<option value="${esc(item.value)}" ${item.value === selected ? "selected" : ""}>${esc(item.label)}</option>`
    )),
  ].join("")
}

export function detailTypeOptionsHtml(catalog, domain, selected, escapeHtml) {
  const esc = escapeHtml || ((value) => String(value))
  const items = catalogTypeItems(catalog, domain)
  const known = items.some((item) => item.value === selected)
  const options = items.map((item) => (
    `<option value="${esc(item.value)}" ${item.value === selected ? "selected" : ""}>${esc(item.label)}</option>`
  ))
  if (selected && !known) options.unshift(`<option value="${CUSTOM_DETAIL_TYPE_VALUE}" selected>当前自定义详细类型</option>`)
  else options.push(`<option value="${CUSTOM_DETAIL_TYPE_VALUE}">自定义详细类型…</option>`)
  return options.join("")
}

export function bindTypeKindControls({ typeSelect, customInput, customContainer, kindSelect, kindHelp, catalog, domain, onChange }) {
  if (!typeSelect || !kindSelect) return
  const sync = () => {
    const custom = typeSelect.value === CUSTOM_DETAIL_TYPE_VALUE
    if (customContainer) customContainer.hidden = !custom
    if (customInput) customInput.required = custom
    if (!kindSelect.value && !custom) {
      kindSelect.value = defaultKindForType(catalog, domain, typeSelect.value)
    }
    if (kindHelp) kindHelp.textContent = kindItem(catalog, domain, kindSelect.value)?.description || "先选择用于 AI 检索的通用分类。"
    onChange?.()
  }
  typeSelect.addEventListener("change", sync)
  kindSelect.addEventListener("change", sync)
  customInput?.addEventListener("input", () => onChange?.())
  sync()
}

export function readDetailType(typeSelect, customInput) {
  if (!typeSelect) return ""
  return typeSelect.value === CUSTOM_DETAIL_TYPE_VALUE ? String(customInput?.value || "").trim() : typeSelect.value
}
