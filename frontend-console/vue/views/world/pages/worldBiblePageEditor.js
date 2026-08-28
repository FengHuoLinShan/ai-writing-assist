export function editorSourceKey(source) {
  if (!source) return null
  if (source.id && (Object.prototype.hasOwnProperty.call(source, "page_id") || source.base_version_number != null)) {
    return `draft:${source.id}:${source.updated_at || ""}`
  }
  return `page:${source.id || ""}:${source.version_number || 0}`
}

export function editorPayloadFromSource(source) {
  return {
    title: source?.title || "",
    page_type: source?.page_type || "custom",
    free_text: source?.free_text || "",
    sort_order: Number(source?.sort_order || 0),
    linked_asset_refs_json: source?.linked_asset_refs_json || [],
    sections_json: source?.sections_json || [],
  }
}

export function normalizeEditorPayload(payload = {}) {
  const sections = Array.isArray(payload.sections_json) ? [...payload.sections_json] : []
  sections.sort((a, b) => Number(a?.sort_order || 0) - Number(b?.sort_order || 0)
    || String(a?.section_id || "").localeCompare(String(b?.section_id || "")))
  return {
    title: String(payload.title || ""),
    page_type: String(payload.page_type || "custom"),
    free_text: String(payload.free_text || ""),
    sort_order: Number(payload.sort_order || 0),
    linked_asset_refs_json: Array.isArray(payload.linked_asset_refs_json) ? payload.linked_asset_refs_json : [],
    sections_json: sections.map((item, i) => ({
      section_id: item?.section_id || "",
      section_type: item?.section_type || "markdown",
      title: item?.title || "",
      body_markdown: item?.body_markdown || "",
      sort_order: (i + 1) * 10,
      linked_asset_ref_hashes: Array.isArray(item?.linked_asset_ref_hashes) ? item.linked_asset_ref_hashes : [],
      projection_policy: item?.projection_policy || "eligible",
      sensitivity_hint: item?.sensitivity_hint || "author_safe",
    })),
  }
}

export function parseAssetRefs(value) {
  const raw = String(value || "").trim()
  if (!raw) return []
  if (raw.startsWith("[")) {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
      throw new Error("无效资产引用")
    }
    return parsed.map((item) => ({ ...item }))
  }
  return raw.split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const sep = line.indexOf(":")
    if (sep < 1 || sep === line.length - 1) throw new Error(`无效资产引用：${line}`)
    return { type: line.slice(0, sep).trim(), id: line.slice(sep + 1).trim() }
  })
}

export function formatAssetRefs(refs) {
  return JSON.stringify(Array.isArray(refs) ? refs : [])
}

export function readDraftFromDom(title, pageType, freeText, sortOrder, assetRefs, sections) {
  if (!title?.trim()) throw new Error("标题不能为空")
  return {
    title: title.trim(),
    page_type: pageType || "custom",
    free_text: freeText || "",
    sort_order: Number(sortOrder || 0),
    linked_asset_refs_json: parseAssetRefs(assetRefs || ""),
    sections_json: sections || [],
  }
}
