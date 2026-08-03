export const PAGE_PROPOSAL_DRAFT_SCHEMA_VERSION = 1

function stringifyJson(value) {
  return JSON.stringify(value ?? [], null, 2)
}

export function pageProposalSuggestionId(result) {
  if (!result || !["world_bible_page", "world_bible_new_page"].includes(result.kind)) return ""
  return typeof result.suggestion?.id === "string" && result.suggestion.id ? result.suggestion.id : ""
}

export function editorFromPageProposal(result) {
  const page = result?.proposal?.page || {}
  return {
    title: typeof page.title === "string" ? page.title : "",
    pageType: typeof page.page_type === "string" ? page.page_type : "custom",
    freeText: typeof page.free_text === "string" ? page.free_text : "",
    sectionsText: stringifyJson(page.sections_json),
    assetsText: stringifyJson(page.linked_asset_refs_json),
  }
}

export function normalizePageProposalDraft(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  if (value.schemaVersion !== PAGE_PROPOSAL_DRAFT_SCHEMA_VERSION || typeof value.suggestionId !== "string" || !value.suggestionId) return null
  const editor = value.editor
  if (!editor || typeof editor !== "object" || Array.isArray(editor)) return null
  const fields = ["title", "pageType", "freeText", "sectionsText", "assetsText"]
  if (!fields.every((field) => typeof editor[field] === "string")) return null
  return {
    schemaVersion: PAGE_PROPOSAL_DRAFT_SCHEMA_VERSION,
    suggestionId: value.suggestionId,
    editor: Object.fromEntries(fields.map((field) => [field, editor[field]])),
  }
}

export function pageProposalDraftMatches(result, value) {
  const draft = normalizePageProposalDraft(value)
  if (result?.suggestion?.status !== "pending") return null
  return draft && draft.suggestionId === pageProposalSuggestionId(result) ? draft : null
}

export function capturePageProposalDraft(result, editor) {
  const suggestionId = pageProposalSuggestionId(result)
  if (!suggestionId) return null
  return normalizePageProposalDraft({
    schemaVersion: PAGE_PROPOSAL_DRAFT_SCHEMA_VERSION,
    suggestionId,
    editor,
  })
}

export function buildPageProposalApplyPayload(editor) {
  const normalized = normalizePageProposalDraft({
    schemaVersion: PAGE_PROPOSAL_DRAFT_SCHEMA_VERSION,
    suggestionId: "apply-preview",
    editor,
  })
  if (!normalized) throw new Error("invalid page proposal editor")
  return {
    page: {
      title: normalized.editor.title,
      page_type: normalized.editor.pageType,
      free_text: normalized.editor.freeText,
      sections_json: JSON.parse(normalized.editor.sectionsText || "[]"),
      linked_asset_refs_json: JSON.parse(normalized.editor.assetsText || "[]"),
    },
  }
}
