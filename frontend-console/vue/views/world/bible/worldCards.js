import { worldAssetDisplay } from "../../../../shared/assetDisplayState.js"

const CARD_KINDS = new Set(["all", "page", "entity"])
const CARD_STATES = new Set(["", "working", "active", "review", "archived"])
const CARD_LAYOUTS = new Set(["cards", "list"])
const CARD_SORTS = new Set(["updated", "recent", "title", "created"])
const GROUP_VIEWS = new Set(["affiliation", "location", "possessions", "event", "custom"])
const GROUP_SIDES = new Set(["source", "target"])

export const LIBRARY_PAGE_SIZE = 50

/** 关系分组维护单批成员上限（与后端 membership-batch 契约一致）。 */
export const RELATION_MEMBERSHIP_MAX = 50

function trimmedParam(query, key, max = 64) {
  return String(query?.get?.(key) || "").trim().slice(0, max)
}

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
  const layout = String(query?.get?.("layout") || "list")
  const sort = String(query?.get?.("sort") || "updated")
  const skip = Number.parseInt(String(query?.get?.("skip") || "0"), 10)
  const groupViewRaw = String(query?.get?.("group_view") || "").trim()
  // 未知视角键直接忽略（服务端会 422），避免把无效配置带进浏览态。
  const groupView = GROUP_VIEWS.has(groupViewRaw) ? groupViewRaw : ""
  const groupSideRaw = String(query?.get?.("group_side") || "").trim()
  return {
    q: String(query?.get?.("q") || "").trim().slice(0, 120),
    kind: CARD_KINDS.has(kind) ? kind : "all",
    type: type === "custom" ? "" : type,
    state: CARD_STATES.has(state) ? state : "",
    layout: CARD_LAYOUTS.has(layout) ? layout : "list",
    sort: CARD_SORTS.has(sort) ? sort : "updated",
    topicId: String(query?.get?.("topic_id") || "").trim().slice(0, 64),
    favorite: String(query?.get?.("fav") || "") === "1",
    unclassified: String(query?.get?.("unclassified") || "") === "1",
    skip: Number.isFinite(skip) && skip > 0 ? skip : 0,
    source: String(query?.get?.("source") || "").trim().slice(0, 64),
    workflowId: String(query?.get?.("workflow_id") || "").trim().slice(0, 128),
    needsReview: String(query?.get?.("needs_review") || "").trim(),
    autoIngested: String(query?.get?.("auto_ingested") || "").trim(),
    groupView,
    groupId: groupView ? trimmedParam(query, "group_id") : "",
    groupUnlinked: groupView ? String(query?.get?.("group_unlinked") || "") === "1" : false,
    // 组列表搜索（q，按组名/别名）与组内成员搜索（member_q）各自独立恢复。
    memberQ: groupView
      ? String(query?.get?.("member_q") || "").trim().slice(0, 120)
      : "",
    groupType: groupView ? trimmedParam(query, "group_type") : "",
    memberType: groupView ? trimmedParam(query, "member_type") : "",
    relationType: groupView ? trimmedParam(query, "relation_type") : "",
    groupSide: groupView && GROUP_SIDES.has(groupSideRaw) ? groupSideRaw : "",
  }
}

export function worldCardQuery(filters) {
  const query = new URLSearchParams()
  const q = String(filters?.q || "").trim()
  if (q) query.set("q", q)
  if (filters?.kind && filters.kind !== "all") query.set("kind", filters.kind)
  if (filters?.type) query.set("type", filters.type)
  if (filters?.state) query.set("state", filters.state)
  if (filters?.layout && filters.layout !== "list") query.set("layout", filters.layout)
  if (filters?.sort && filters.sort !== "updated") query.set("sort", filters.sort)
  if (filters?.topicId) query.set("topic_id", filters.topicId)
  if (filters?.favorite) query.set("fav", "1")
  if (filters?.unclassified) query.set("unclassified", "1")
  if (filters?.skip > 0) query.set("skip", String(filters.skip))
  if (filters?.source) query.set("source", filters.source)
  if (filters?.workflowId) query.set("workflow_id", filters.workflowId)
  if (filters?.needsReview) query.set("needs_review", filters.needsReview)
  if (filters?.autoIngested) query.set("auto_ingested", filters.autoIngested)
  if (filters?.groupView) {
    query.set("group_view", filters.groupView)
    if (filters.groupId) query.set("group_id", filters.groupId)
    if (filters.groupUnlinked) query.set("group_unlinked", "1")
    if (filters.memberQ) query.set("member_q", filters.memberQ)
    if (filters.groupType) query.set("group_type", filters.groupType)
    if (filters.memberType) query.set("member_type", filters.memberType)
    if (filters.relationType) query.set("relation_type", filters.relationType)
    if (filters.groupSide) query.set("group_side", filters.groupSide)
  }
  return query
}

/** 是否处于服务端统一列表负责结果集的浏览状态（首页除外）。 */
export function usesServerLibrary(filters) {
  return Boolean(
    filters?.groupView
    || filters?.q
    || filters?.type
    || filters?.state
    || filters?.topicId
    || filters?.favorite
    || filters?.unclassified
    || filters?.skip > 0
    || (filters?.kind && filters.kind !== "all"),
  )
}

/** 当前是否处于关系分组视角的组内成员页（选组或未关联）。 */
export function isRelationMembersPage(filters) {
  return Boolean(filters?.groupView && (filters.groupId || filters.groupUnlinked))
}

/**
 * custom 视角配置是否完整（group_type + relation_type + group_side）。
 * 不完整时浏览态显示配置表单，不发起注定 422 的请求。
 */
export function isCustomViewConfigured(filters) {
  return Boolean(
    filters?.groupView === "custom"
    && filters.groupType
    && filters.relationType
    && filters.groupSide,
  )
}

export const LIBRARY_STATE_LABELS = { active: "已采用", review: "待完善", archived: "已归档" }

/** 把服务端统一资料条目映射成资料卡读模型。 */
export function cardsFromLibraryItems(items) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const working = Boolean(item?.working)
    const state = working ? "working" : String(item?.state || "review")
    const kind = item?.kind === "entity" ? "entity" : "page"
    return {
      key: `${item?.kind}:${item?.id}`,
      kind,
      id: kind === "entity" ? item.id : (item?.kind === "draft" ? null : item.id),
      targetKind: item?.kind,
      targetId: item?.id,
      draftId: item?.draft_id || (item?.kind === "draft" ? item.id : null),
      title: item?.title || "未命名资料",
      summary: String(item?.summary || ""),
      searchText: "",
      typeKey: item?.item_type || "custom",
      state,
      stateLabel: working ? "工作稿" : LIBRARY_STATE_LABELS[state] || "待完善",
      updatedAt: String(item?.updated_at || item?.created_at || ""),
      isFavorite: Boolean(item?.is_favorite),
      lastOpenedAt: item?.last_opened_at || null,
      relationRefs: Array.isArray(item?.relation_refs) ? item.relation_refs : [],
    }
  })
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
    searchText: searchableText(entity),
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

// ============================================================
// 关系分组视角（G0 契约：预设与服务端 relation-groups 响应 views 对齐）
// ============================================================

/**
 * 预设视角的客户端回退（与服务端 PRESET_VIEWS / relation-groups 响应一致）。
 * 服务端 views 可用时始终优先；此表只用于元数据请求失败时保持浏览与
 * 添加面板可用，不改变任何请求参数语义。
 */
export const RELATION_VIEW_PRESETS = [
  {
    key: "affiliation",
    title: "势力成员",
    description: "按势力／组织查看成员人物，维护成员归属。",
    group_types: ["faction", "organization"],
    member_types: ["character"],
    match_relations: [
      { relation_type: "member_of", label: "成员", relation_kind: "social", group_side: "target" },
      { relation_type: "leader_of", label: "领导者", relation_kind: "social", group_side: "target" },
      { relation_type: "belongs_to", label: "属于", relation_kind: "state", group_side: "target" },
    ],
    default_relation: { relation_type: "member_of", label: "成员", relation_kind: "social", group_side: "target" },
    custom: false,
  },
  {
    key: "location",
    title: "地点关联",
    description: "按地点查看位于其中的人与物，含子地点与包含关系。",
    group_types: ["location"],
    member_types: null,
    match_relations: [
      { relation_type: "located_at", label: "位于", relation_kind: "spatial", group_side: "target" },
      { relation_type: "located_in", label: "位于（内）", relation_kind: "spatial", group_side: "target" },
      { relation_type: "位于", label: "位于", relation_kind: "spatial", group_side: "target" },
      { relation_type: "contains", label: "包含", relation_kind: "spatial", group_side: "source" },
      { relation_type: "包含", label: "包含", relation_kind: "spatial", group_side: "source" },
    ],
    default_relation: { relation_type: "located_at", label: "位于", relation_kind: "spatial", group_side: "target" },
    custom: false,
  },
  {
    key: "possessions",
    title: "人物持有",
    description: "按人物查看持有的物品与资源。",
    group_types: ["character"],
    member_types: ["item", "object", "artifact", "resource"],
    match_relations: [
      { relation_type: "belongs_to", label: "属于", relation_kind: "state", group_side: "target" },
      { relation_type: "携带", label: "携带", relation_kind: "spatial", group_side: "source" },
    ],
    default_relation: { relation_type: "belongs_to", label: "属于", relation_kind: "state", group_side: "target" },
    custom: false,
  },
  {
    key: "event",
    title: "事件参与",
    description: "按事件查看参与人物。",
    group_types: ["event"],
    member_types: ["character"],
    match_relations: [
      { relation_type: "participates_in", label: "参与", relation_kind: "state", group_side: "target" },
      { relation_type: "参与", label: "参与", relation_kind: "state", group_side: "target" },
    ],
    default_relation: { relation_type: "participates_in", label: "参与", relation_kind: "state", group_side: "target" },
    custom: false,
  },
]

/** 按视角 key 取元数据；服务端 views 优先，custom 无法回退时返回 null。 */
export function relationViewMeta(views, filters) {
  const key = filters?.groupView || ""
  if (!key) return null
  if (key === "custom") {
    const serverView = (Array.isArray(views) ? views : []).find((view) => view?.key === "custom")
    if (serverView) return serverView
    if (!isCustomViewConfigured(filters)) return null
    return {
      key: "custom",
      title: "自定义视角",
      description: "按你选择的对象类型与关系维护成员。",
      group_types: [filters.groupType],
      member_types: filters.memberType ? [filters.memberType] : null,
      match_relations: [{
        relation_type: filters.relationType,
        label: filters.relationType,
        relation_kind: "",
        group_side: filters.groupSide,
      }],
      default_relation: null,
      custom: true,
    }
  }
  return (Array.isArray(views) ? views : []).find((view) => view?.key === key)
    || RELATION_VIEW_PRESETS.find((view) => view.key === key)
    || null
}

/** 视角下可添加的关系选项（match_relations 去重；custom 需作者显式填写）。 */
export function relationAddOptions(viewMeta) {
  const relations = Array.isArray(viewMeta?.match_relations) ? viewMeta.match_relations : []
  const seen = new Set()
  const options = []
  for (const relation of relations) {
    const signature = `${relation?.relation_type}|${relation?.group_side}`
    if (!relation?.relation_type || seen.has(signature)) continue
    seen.add(signature)
    options.push({
      relation_type: relation.relation_type,
      label: relation.label || relation.relation_type,
      relation_kind: relation.relation_kind || "",
      group_side: relation.group_side || "target",
    })
  }
  return options
}

/** 组内条目的关系标签：优先视角 match_relations 的 label，回退 relation_type。 */
export function relationRefLabel(viewMeta, ref) {
  const type = String(ref?.relation?.relation_type || "")
  const match = (Array.isArray(viewMeta?.match_relations) ? viewMeta.match_relations : [])
    .find((item) => item?.relation_type === type)
  return match?.label || type
}

// ============================================================
// membership-batch payload 构造与失败文案（纯函数，供组件与测试复用）
// ============================================================

function cleanMemberIds(memberIds) {
  const ids = []
  const seen = new Set()
  for (const id of Array.isArray(memberIds) ? memberIds : []) {
    const value = String(id || "").trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    ids.push(value)
  }
  return ids.slice(0, RELATION_MEMBERSHIP_MAX)
}

function customViewParams(filters, { keepRelation = true } = {}) {
  if (filters?.groupView !== "custom") return {}
  const params = {}
  if (filters.groupType) params.group_type = filters.groupType
  if (filters.memberType) params.member_type = filters.memberType
  if (keepRelation) {
    if (filters.relationType) params.relation_type = filters.relationType
    if (filters.groupSide) params.group_side = filters.groupSide
  }
  return params
}

/**
 * 构造 add 请求体。预设视角 relation 缺省时使用视角默认关系；
 * custom 视角要求 relation 三元组（relation_type/kind/side）完整。
 * 返回 { payload } 或 { error }（作者可读的校验错误）。
 */
export function buildMembershipAddPayload({
  projectId, filters, memberIds, relation = null, groupId = null,
}) {
  const members = cleanMemberIds(memberIds)
  if (!members.length) return { error: "请先选择要添加的成员。" }
  // 未关联页发起添加时由对话框显式选择目标组（groupId 覆盖）。
  const targetGroupId = String(groupId || filters?.groupId || "").trim()
  if (!filters?.groupView || !targetGroupId) {
    return { error: "请先选择要加入的分组。" }
  }
  const view = relationViewMeta(null, filters)
  const selected = relation ? {
    relation_type: String(relation.relation_type || "").trim(),
    relation_kind: String(relation.relation_kind || "").trim(),
    group_side: relation.group_side === "source" ? "source" : "target",
  } : null
  const resolved = selected?.relation_type
    ? selected
    : view?.default_relation
      ? {
        relation_type: view.default_relation.relation_type,
        relation_kind: view.default_relation.relation_kind || "",
        group_side: view.default_relation.group_side || "target",
      }
      : null
  if (filters.groupView === "custom") {
    if (!filters.groupType || !resolved?.relation_type || !resolved.relation_kind || !filters.groupSide) {
      return { error: "自定义视角需要先选择分组对象类型、关系分类、详细关系和方向。" }
    }
  } else if (!resolved?.relation_type) {
    return { error: "请选择要建立的关系。" }
  }
  const payload = {
    novel_id: projectId,
    action: "add",
    group_view: filters.groupView,
    group_id: targetGroupId,
    member_ids: members,
    confirmed: true,
    relation_type: resolved.relation_type,
    group_side: resolved.group_side,
    // custom 视角的 relation_type/group_side 同时定义本次请求的视角匹配，
    // 必须以对话框实际选择为准；URL 旧配置只补充 group_type/member_type，
    // 不能在后面展开把作者刚改的关系与方向静默覆盖回去。
    ...customViewParams(filters, { keepRelation: false }),
  }
  // 预设视角的 kind 缺省交给服务端解析；空字符串会被后端 Literal 拒绝。
  if (resolved.relation_kind) payload.relation_kind = resolved.relation_kind
  return { payload }
}

/**
 * 构造 remove 请求体：relation_refs 是作者勾选的精确清单
 * （[{id, expected_execution_fingerprint}]），清单为空时拒绝提交。
 */
export function buildMembershipRemovePayload({ projectId, filters, memberIds, relationRefs }) {
  const members = cleanMemberIds(memberIds)
  if (!members.length) return { error: "请先选择要移出的成员。" }
  if (!filters?.groupView || !filters.groupId) return { error: "缺少分组信息，请返回分组列表后重试。" }
  const refs = []
  const seen = new Set()
  for (const ref of Array.isArray(relationRefs) ? relationRefs : []) {
    const id = String(ref?.relation?.id || ref?.id || "").trim()
    const fingerprint = String(ref?.execution_fingerprint || ref?.expected_execution_fingerprint || "").trim()
    if (!id || !fingerprint || seen.has(id)) continue
    seen.add(id)
    refs.push({ id, expected_execution_fingerprint: fingerprint })
  }
  if (!refs.length) return { error: "请至少勾选一条要结束的关系。" }
  return {
    payload: {
      novel_id: projectId,
      action: "remove",
      group_view: filters.groupView,
      group_id: filters.groupId,
      member_ids: members,
      confirmed: true,
      relation_refs: refs,
      ...customViewParams(filters),
    },
  }
}

/**
 * membership-batch 失败的作者可懂文案与后续入口。
 * action: retry（刷新重试）/ review（去关系审核）/ validation（去校验工具）/ none。
 */
export function relationMembershipErrorInfo(error) {
  // request() 封装抛出的错误：错误码在 err.body.error（后端 DomainError 序列化）。
  const code = String(
    error?.code
    || error?.body?.error
    || error?.data?.code
    || error?.error?.code
    || "",
  )
  const detail = String(error?.detail || error?.data?.detail || error?.message || "")
  if (code === "stale_execution") {
    return {
      title: "关系已在别处更新",
      message: detail || "分组关系刚被其他修改更新，本次操作没有生效。刷新后按最新关系重试。",
      action: "retry",
      actionLabel: "刷新重试",
    }
  }
  if (code === "relation_exists_as_candidate") {
    return {
      title: "已有待处理的候选关系",
      message: detail || "要添加的关系已有候选记录，先在世界关系审核中处理，再回来维护分组。",
      action: "review",
      actionLabel: "去关系审核",
    }
  }
  if (code === "required_validation") {
    return {
      title: "需要先完成世界校验",
      message: detail || "项目已启用世界校验策略，正史关系修改前请先完成校验。",
      action: "validation",
      actionLabel: "去校验工具",
    }
  }
  // Pydantic 422 的 detail 是字段错误数组，String() 会得到不可读对象串。
  const readableDetail = Array.isArray(error?.body?.detail) || Array.isArray(error?.detail)
    ? "部分字段没有通过校验，请调整后重试。"
    : detail
  return {
    title: "分组维护没有保存",
    message: readableDetail || "本次修改没有保存，你的选择和输入仍保留，可稍后重试。",
    action: "retry",
    actionLabel: "重试",
  }
}

/** 一次批量维护成功的 toast 文案。 */
export function membershipResultMessage(result) {
  const added = Number(result?.added_count || 0)
  const reused = Number(result?.reused_count || 0)
  const removed = Number(result?.removed_count || 0)
  const parts = []
  if (added) parts.push(`新增 ${added} 条关系`)
  if (reused) parts.push(`复用已有 ${reused} 条`)
  if (removed) parts.push(`结束 ${removed} 条关系`)
  return parts.length ? `分组已更新：${parts.join("，")}。` : "分组没有需要变更的成员。"
}

/**
 * 关系视角成员选择作用域：项目 + 视角 + 分组 + 已应用查询。
 * 作用域变化即视为结果集变化，旧选择自然失效（配合 reconcile 只保留当前页）。
 */
export function relationSelectionScope(projectId, filters) {
  // 排序与布局不改变结果集，不纳入作用域（避免无谓清空选择）。
  const signature = worldCardQuery({
    ...filters,
    q: filters?.q || "",
    skip: 0,
    layout: "",
    sort: "updated",
  }).toString()
  return `world-relation-members:${projectId || "none"}:${signature}`
}
