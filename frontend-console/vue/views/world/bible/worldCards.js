import { worldAssetDisplay } from "../../../../shared/assetDisplayState.js"

const CARD_KINDS = new Set(["all", "page", "entity"])
const CARD_STATES = new Set(["", "working", "active", "review", "archived"])
const CARD_LAYOUTS = new Set(["cards", "list"])

function textSummary(source) {
  const freeText = String(source?.free_text || "").trim()
  if (freeText) return freeText.slice(0, 240)
  const section = (source?.sections_json || []).find((item) => String(item?.body_markdown || "").trim())
  return String(section?.body_markdown || source?.summary || source?.public_info || "").trim().slice(0, 240)
}

function timestamp(source) {
  return String(source?.updated_at || source?.created_at || "")
}

function searchableText(source) {
  return [
    source?.title,
    source?.name,
    source?.free_text,
    ...(source?.sections_json || []).flatMap((section) => [section?.title, section?.body_markdown]),
    source?.summary,
    source?.public_info,
  ].filter(Boolean).join("\n").toLocaleLowerCase("zh-CN")
}

function cardState(source, working = false) {
  if (working || (!source?.display_state && source?.status === "draft")) {
    return { state: "working", stateLabel: "工作稿" }
  }
  const display = worldAssetDisplay(source)
  return { state: display.displayState, stateLabel: display.label }
}

export function worldCardFiltersFromQuery(query) {
  const kind = String(query?.get?.("kind") || "all")
  const type = String(query?.get?.("type") || "").trim().slice(0, 64)
  const state = String(query?.get?.("state") || "")
  const layout = String(query?.get?.("layout") || "cards")
  return {
    q: String(query?.get?.("q") || "").trim().slice(0, 120),
    kind: CARD_KINDS.has(kind) ? kind : "all",
    type: type === "custom" ? "" : type,
    state: CARD_STATES.has(state) ? state : "",
    layout: CARD_LAYOUTS.has(layout) ? layout : "cards",
    source: String(query?.get?.("source") || "").trim().slice(0, 64),
    workflowId: String(query?.get?.("workflow_id") || "").trim().slice(0, 128),
    needsReview: String(query?.get?.("needs_review") || "").trim(),
    autoIngested: String(query?.get?.("auto_ingested") || "").trim(),
  }
}

export function worldCardQuery(filters) {
  const query = new URLSearchParams()
  const q = String(filters?.q || "").trim()
  if (q) query.set("q", q)
  if (filters?.kind && filters.kind !== "all") query.set("kind", filters.kind)
  if (filters?.type) query.set("type", filters.type)
  if (filters?.state) query.set("state", filters.state)
  if (filters?.layout && filters.layout !== "cards") query.set("layout", filters.layout)
  if (filters?.source) query.set("source", filters.source)
  if (filters?.workflowId) query.set("workflow_id", filters.workflowId)
  if (filters?.needsReview) query.set("needs_review", filters.needsReview)
  if (filters?.autoIngested) query.set("auto_ingested", filters.autoIngested)
  return query
}

export function buildWorldCards({ pages = [], drafts = [], entities = [], filters = {} }) {
  const draftsByPage = new Map(drafts.filter((item) => item?.page_id).map((item) => [item.page_id, item]))
  const pageCards = pages
    .filter((page) => !worldAssetDisplay(page).isHistory)
    .map((page) => {
      const draft = draftsByPage.get(page.id)
      const source = draft || page
      return {
        key: `page:${page.id}`,
        kind: "page",
        id: page.id,
        draftId: draft?.id || null,
        title: source.title || "未命名资料页",
        summary: textSummary(source),
        searchText: searchableText(source),
        typeKey: source.page_type || "custom",
        ...cardState(source, Boolean(draft)),
        updatedAt: timestamp(source),
      }
    })
  const freeDraftCards = drafts
    .filter((draft) => !draft?.page_id)
    .map((draft) => ({
      key: `draft:${draft.id}`,
      kind: "page",
      id: null,
      draftId: draft.id,
      title: draft.title || "未命名工作稿",
      summary: textSummary(draft),
      searchText: searchableText(draft),
      typeKey: draft.page_type || "custom",
      state: "working",
      stateLabel: "工作稿",
      updatedAt: timestamp(draft),
    }))
  const entityCards = entities.map((entity) => ({
    key: `entity:${entity.id || entity.entity_id}`,
    kind: "entity",
    id: entity.id || entity.entity_id,
    draftId: null,
    title: entity.name || "未命名人物或设定",
    summary: textSummary(entity),
    typeKey: entity.entity_type || "custom",
    ...cardState(entity),
    updatedAt: timestamp(entity),
    hasImage: Boolean(entity.has_image),
  }))
  const q = String(filters.q || "").trim().toLocaleLowerCase("zh-CN")
  const kind = CARD_KINDS.has(filters.kind) ? filters.kind : "all"
  const type = String(filters.type || "")
  const state = CARD_STATES.has(filters.state) ? filters.state : ""
  return [...freeDraftCards, ...pageCards, ...entityCards]
    .filter((card) => kind === "all" || card.kind === kind)
    .filter((card) => !type || card.typeKey === type)
    .filter((card) => !state || card.state === state)
    // Entity rows are already the server's bounded q result (including aliases and hidden fields).
    // Re-filtering their 240-char preview here would discard valid matches.
    .filter((card) => !q || card.kind === "entity" || card.searchText.includes(q))
    .sort((left, right) => (
      Number(right.state === "working") - Number(left.state === "working")
      || right.updatedAt.localeCompare(left.updatedAt)
      || left.title.localeCompare(right.title, "zh-CN")
      || left.key.localeCompare(right.key)
    ))
}
