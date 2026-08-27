const CARD_KINDS = new Set(["all", "page", "entity"])

function textSummary(source) {
  const freeText = String(source?.free_text || "").trim()
  if (freeText) return freeText.slice(0, 240)
  const section = (source?.sections_json || []).find((item) => String(item?.body_markdown || "").trim())
  return String(section?.body_markdown || source?.summary || source?.public_info || "").trim().slice(0, 240)
}

function timestamp(source) {
  return String(source?.updated_at || source?.created_at || "")
}

export function worldCardFiltersFromQuery(query) {
  const kind = String(query?.get?.("kind") || "all")
  const type = String(query?.get?.("type") || "").trim().slice(0, 64)
  return {
    q: String(query?.get?.("q") || "").trim().slice(0, 120),
    kind: CARD_KINDS.has(kind) ? kind : "all",
    type: type === "custom" ? "" : type,
  }
}

export function worldCardQuery(filters) {
  const query = new URLSearchParams()
  const q = String(filters?.q || "").trim()
  if (q) query.set("q", q)
  if (filters?.kind && filters.kind !== "all") query.set("kind", filters.kind)
  if (filters?.type) query.set("type", filters.type)
  return query
}

export function buildWorldCards({ pages = [], drafts = [], entities = [], filters = {} }) {
  const draftsByPage = new Map(drafts.filter((item) => item?.page_id).map((item) => [item.page_id, item]))
  const pageCards = pages
    .filter((page) => page?.status !== "archived")
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
        typeKey: source.page_type || "custom",
        state: draft ? "working" : "active",
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
      typeKey: draft.page_type || "custom",
      state: "working",
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
    state: entity.display_state || "active",
    updatedAt: timestamp(entity),
    hasImage: Boolean(entity.has_image),
  }))
  const q = String(filters.q || "").trim().toLocaleLowerCase("zh-CN")
  const kind = CARD_KINDS.has(filters.kind) ? filters.kind : "all"
  const type = String(filters.type || "")
  return [...freeDraftCards, ...pageCards, ...entityCards]
    .filter((card) => kind === "all" || card.kind === kind)
    .filter((card) => !type || card.typeKey === type)
    .filter((card) => !q || `${card.title}\n${card.summary}`.toLocaleLowerCase("zh-CN").includes(q))
    .sort((left, right) => (
      Number(right.state === "working") - Number(left.state === "working")
      || right.updatedAt.localeCompare(left.updatedAt)
      || left.title.localeCompare(right.title, "zh-CN")
      || left.key.localeCompare(right.key)
    ))
}
