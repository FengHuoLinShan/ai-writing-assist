/**
 * world 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 * 替代原 views/worldView.js + views/worldBibleView.js。
 *
 * load() 对应 vanilla onEnter（worldView.js:234-283）+ render 阶段各子标签的
 * 数据加载（L713-742）：通用数据（entityTypes / reviewTypeCatalog / reviewCounts）
 * 全子标签执行，业务数据按当前子标签预取（vanilla 是全量预取+按标签渲染，
 * 未见差异——各标签只渲染自己的数据，标题计数见 WorldView computed）。
 */
import { mountIsland } from "./mountIsland.js"
import WorldView from "./views/world/WorldView.vue"
import { getApi, getAppState, getRouteQuery, getRouter, getToast } from "./bridge/index.js"
import { worldAssetDisplay } from "../shared/assetDisplayState.js"
import { markWorldLeft, reconcileWorldEntry, worldSession } from "./views/world/worldSession.js"
import { autoExtractManager, fusionManager } from "./views/world/workflowManagers.js"
import {
  REVIEW_ALIAS_KIND_FALLBACK,
  REVIEW_ALIAS_TYPE_FALLBACK,
  REVIEW_RELATION_KIND_FALLBACK,
  REVIEW_RELATION_TYPE_FALLBACK,
  SYSTEM_ENTITY_TYPE_FALLBACK,
  WORLD_ALIAS_FILTER_DEFAULTS,
  WORLD_ALIAS_QUERY_KEYS,
  WORLD_RELATION_FILTER_DEFAULTS,
  WORLD_RELATION_QUERY_KEYS,
  candidateFiltersFromQuery,
  hasAdvancedObjectFilters,
  normalizeReviewSubView,
  reviewKindFromRoute,
  objectFiltersFromQuery,
  reviewFiltersFromQuery,
} from "./views/world/logic/worldQuery.js"

/** 对应 vanilla _preferredDiscoveryMode（worldView.js:405-413）。 */
function preferredDiscoveryMode(projectId) {
  try {
    const stored = localStorage.getItem(`novel_view_mode:${projectId || "none"}:world-objects`)
    if (stored === "normal" || stored === "hot") return stored
  } catch {
    // localStorage 不可用时使用产品默认值。
  }
  return "hot"
}

/** 对应 vanilla _loadEntities 的参数构造（worldView.js:567-585）。 */
function entityListParams(projectId, filters, discoveryMode) {
  const params = {
    novel_id: projectId,
    skip: filters.skip,
    limit: filters.limit,
    view_mode: discoveryMode,
  }
  if (filters.entity_type) params.entity_type = filters.entity_type
  params.display_state = filters.display_state || "active"
  if (filters.q) params.q = filters.q
  if (filters.source) params.source = filters.source
  if (filters.workflow_id) params.workflow_id = filters.workflow_id
  if (filters.needs_review === "true") params.needs_review = true
  if (filters.needs_review === "false") params.needs_review = false
  if (filters.auto_ingested === "true") params.auto_ingested = true
  if (filters.auto_ingested === "false") params.auto_ingested = false
  if (discoveryMode === "hot" && filters.focus) params.focus = filters.focus
  return params
}

/** 对应 vanilla _loadCandidates 的参数构造（worldView.js:607-620）。 */
function candidateListParams(projectId, filters) {
  const params = {
    novel_id: projectId,
    display_state: "review",
    skip: filters.skip,
    limit: filters.limit,
  }
  if (filters.q) params.q = filters.q
  if (filters.entity_type) params.entity_type = filters.entity_type
  if (filters.suggested_action) params.suggested_action = filters.suggested_action
  if (filters.source) params.source = filters.source
  if (filters.workflow_id) params.workflow_id = filters.workflow_id
  for (const key of ["scene_index", "source_chapter_index", "confidence_min", "confidence_max"]) {
    if (filters[key] != null && filters[key] !== "") params[key] = Number(filters[key])
  }
  return params
}

/** 审查工作区参数构造（worldView.js:2132-2143 / 2768-2779），两个工作区共用形态。 */
function reviewGroupParams(projectId, filters, keys, numberKeys, boolKeys) {
  const params = { novel_id: projectId, skip: filters.skip, limit: filters.limit }
  for (const key of keys) {
    const value = filters[key]
    if (value === "" || value == null) continue
    if (numberKeys.includes(key)) params[key] = Number(value)
    else if (boolKeys.includes(key)) params[key] = value === true || value === "true"
    else params[key] = value
  }
  return params
}

async function findReviewGroup(fetchPage, params, groupId) {
  let skip = 0
  let total = Number.POSITIVE_INFINITY
  while (skip < total) {
    const page = await fetchPage({ ...params, skip, limit: 50 })
    const groups = Array.isArray(page?.groups) ? page.groups : []
    const match = groups.find((group) => group.group_id === groupId)
    if (match) return match
    total = Number(page?.group_total)
    if (!groups.length || !Number.isFinite(total)) return null
    skip += groups.length
  }
  return null
}

export async function loadWorld() {
  const appState = getAppState()
  const api = getApi()
  const toast = getToast()
  const projectId = appState?.currentProjectId || null
  const subView = appState?.currentSubView || "objects"
  const reviewSubView = normalizeReviewSubView(subView)
  const query = getRouteQuery()
  const requestedReviewKind = reviewKindFromRoute(subView, query)

  reconcileWorldEntry(projectId, subView)
  if (subView === "relations") {
    worldSession.relationListFilters = reviewFiltersFromQuery(
      { q: "", skip: 0, limit: 20 },
      ["q"],
      query,
    )
  }
  if (subView === "aliases") {
    worldSession.aliasListFilters = reviewFiltersFromQuery(
      { q: "", skip: 0, limit: 20 },
      ["q"],
      query,
    )
  }

  // URL 解码筛选（URL 为事实源；objects 解码语义见 worldView.js:467-487）
  const objectFilters = objectFiltersFromQuery(query)
  const objectViewMode = query.get("view") === "card" ? "card" : "table"
  const requestedMode = query.get("mode")
  const discoveryMode = requestedMode === "normal" || requestedMode === "hot"
    ? requestedMode
    : preferredDiscoveryMode(projectId)
  if (discoveryMode === "normal") objectFilters.focus = ""
  if (hasAdvancedObjectFilters(objectFilters)) worldSession.advancedFiltersOpen = true

  // 工作流恢复（模块级 manager，轮询不挂组件生命周期）
  autoExtractManager.recover(projectId)
  fusionManager.recover(projectId)

  const props = {
    projectId,
    subView,
    reviewSubView,
    reviewKind: requestedReviewKind,
    entityTypes: [...SYSTEM_ENTITY_TYPE_FALLBACK],
    reviewTypeCatalog: {
      custom_allowed: true,
      alias_kinds: REVIEW_ALIAS_KIND_FALLBACK,
      alias_types: REVIEW_ALIAS_TYPE_FALLBACK,
      relation_kinds: REVIEW_RELATION_KIND_FALLBACK,
      relation_types: REVIEW_RELATION_TYPE_FALLBACK,
    },
    reviewCounts: { objects: 0, aliases: 0, relations: 0 },
    objectFilters,
    objectViewMode,
    discoveryMode,
    entities: [],
    entitiesTotal: 0,
    entitiesLoadError: null,
    rankingFacets: null,
    rankingContext: null,
    batches: [],
    candidateFilters: candidateFiltersFromQuery(query),
    candidates: [],
    candidateTotal: 0,
    candidateLoadError: null,
    aliasReviewFilters: reviewFiltersFromQuery(WORLD_ALIAS_FILTER_DEFAULTS, WORLD_ALIAS_QUERY_KEYS, query),
    aliasGroups: [],
    aliasGroupTotal: 0,
    aliasItemTotal: 0,
    aliasReviewLoadError: null,
    relationReviewFilters: reviewFiltersFromQuery(WORLD_RELATION_FILTER_DEFAULTS, WORLD_RELATION_QUERY_KEYS, query),
    relationGroups: [],
    relationGroupTotal: 0,
    relationItemTotal: 0,
    relationReviewLoadError: null,
    relations: [],
    relationsTotal: 0,
    relationsLoadError: null,
    aliases: [],
    aliasesTotal: 0,
    aliasesLoadError: null,
    bible: null,
    bibleDeepLink: {
      draftId: query.get("draft_id") || "",
      pageId: query.get("page_id") || "",
      ownerAiSourcePageId: query.get("source_page_id") || "",
      openSuggestions: query.get("open") === "suggestions",
      suggestionId: query.get("suggestion_id") || "",
      openConflicts: query.get("open") === "conflicts",
      openWorldbookImport: query.get("open") === "worldbook-import",
      worldbookImportSuggestionId: query.get("suggestion_id") || "",
      conflictId: query.get("conflict_item_id") || "",
      adoptionPackageId: query.get("adoption_package_id") || "",
      ownerAiOpen: query.get("owner_ai") === "1",
      ownerAiMode: query.get("owner_ai_mode") || "world",
      ownerAiTarget: query.get("target") || "",
      ownerAiPreset: query.get("preset") || "",
      ownerAiCheckpointId: query.get("checkpoint_id") || "",
    },
    knowledgeCharacterId: query.get("knowledge_character_id") || "",
  }
  if (!projectId || !api?.world) return props

  await Promise.all([
    (async () => {
      try {
        const result = await api.world.listEntityTypes(projectId)
        if (Array.isArray(result?.items) && result.items.length) {
          const byValue = new Map(SYSTEM_ENTITY_TYPE_FALLBACK.map((item) => [item.value, item]))
          for (const item of result.items) byValue.set(item.value, item)
          props.entityTypes = Array.from(byValue.values())
        }
      } catch {
        toast("类型目录加载失败，暂时使用系统类型", "warning")
      }
    })(),
    (async () => {
      try {
        const catalog = await api.world.getReviewTypeCatalog()
        if (catalog?.alias_types?.length && catalog?.relation_types?.length) {
          props.reviewTypeCatalog = {
            ...props.reviewTypeCatalog,
            ...catalog,
            alias_kinds: catalog.alias_kinds?.length ? catalog.alias_kinds : props.reviewTypeCatalog.alias_kinds,
            relation_kinds: catalog.relation_kinds?.length ? catalog.relation_kinds : props.reviewTypeCatalog.relation_kinds,
          }
        }
      } catch {
        // 推荐目录不可用时保留开放字符串和本地常用项，不阻断复核。
      }
    })(),
    (async () => {
      try {
        const [objects, aliases, relations] = await Promise.all([
          api.world.listEntities({ novel_id: projectId, display_state: "review", skip: 0, limit: 1 }),
          api.world.listAliases({ novel_id: projectId, display_state: "review", skip: 0, limit: 1 }),
          api.world.listRelationships({ novel_id: projectId, status: "candidate", skip: 0, limit: 1 }),
        ])
        props.reviewCounts = {
          objects: Number(objects?.total || 0),
          aliases: Number(aliases?.total || 0),
          relations: Number(relations?.total || 0),
        }
      } catch {
        // vanilla 回退到各列表 total；per-tab 加载下保留 0（worldView.js:332-337）。
      }
    })(),
  ])

  // 子标签数据（vanilla render 阶段按子标签加载）
  if (subView === "objects") {
    await Promise.all([
      (async () => {
        try {
          const targetEntityId = query.get("entity_id") || ""
          const data = targetEntityId
            ? await api.world.getEntity(targetEntityId, projectId)
            : await api.world.listEntities(entityListParams(projectId, objectFilters, discoveryMode))
          props.entities = targetEntityId ? [data] : (data.items || data || [])
          props.entitiesTotal = targetEntityId ? 1 : (data.total ?? props.entities.length)
          props.rankingFacets = data.facets ?? null
          props.rankingContext = data.ranking_context ?? null
        } catch (err) {
          props.entitiesLoadError = err?.message || "加载失败"
          toast("世界对象加载失败，可稍后重试", "warning")
        }
      })(),
      (async () => {
        try {
          props.batches = await api.world.listEntityBatches({ novel_id: projectId })
        } catch {
          props.batches = []
        }
      })(),
    ])
  } else if (reviewSubView && requestedReviewKind === "objects") {
    try {
      const targetEntityId = query.get("entity_id") || ""
      const data = targetEntityId
        ? await api.world.getEntity(targetEntityId, projectId)
        : await api.world.listEntities(candidateListParams(projectId, props.candidateFilters))
      const items = targetEntityId
        ? (worldAssetDisplay(data).displayState === "review" ? [data] : [])
        : (data.items || data || [])
      // 对应 vanilla _uniqueEntitiesById
      const seen = new Set()
      props.candidates = items.filter((item) => {
        const id = item.id || item.entity_id
        if (!id || seen.has(id)) return false
        seen.add(id)
        return true
      })
      props.candidateTotal = targetEntityId ? props.candidates.length : (Number(data.total ?? props.candidates.length) || 0)
    } catch (err) {
      if (query.get("entity_id") && err?.status === 404) {
        props.candidates = []
        props.candidateTotal = 0
      } else {
        props.candidateLoadError = err?.message || "待处理对象加载失败"
        toast("待处理对象加载失败，可重试", "warning")
      }
    }
  } else if (reviewSubView && requestedReviewKind === "aliases") {
    try {
      const params = reviewGroupParams(
        projectId,
        props.aliasReviewFilters,
        ["q", "source", "workflow_id", "scene_index", "source_chapter_index", "confidence_min", "confidence_max", "has_quote", "type_kind", "alias_kind", "multi_alias_only"],
        ["scene_index", "source_chapter_index", "confidence_min", "confidence_max"],
        ["has_quote", "multi_alias_only"],
      )
      const targetGroupId = query.get("group_id") || ""
      const data = targetGroupId
        ? null
        : await api.world.listAliasReviewGroups(params)
      const target = targetGroupId
        ? await findReviewGroup((page) => api.world.listAliasReviewGroups(page), { novel_id: projectId }, targetGroupId)
        : null
      props.aliasGroups = targetGroupId ? (target ? [target] : []) : (data.groups || [])
      props.aliasItemTotal = targetGroupId ? Number(target?.member_count || 0) : Number(data.item_total || 0)
      props.aliasGroupTotal = targetGroupId ? props.aliasGroups.length : Number(data.group_total || 0)
    } catch (err) {
      props.aliasReviewLoadError = err?.message || "请稍后重试"
    }
  } else if (reviewSubView && requestedReviewKind === "relations") {
    try {
      const params = reviewGroupParams(
        projectId,
        props.relationReviewFilters,
        ["q", "relation_type", "relation_kind", "source_chapter_id", "scene_index", "source_chapter_index", "strength_min", "strength_max", "has_quote", "type_kind", "multi_type_only", "has_reverse_candidates", "has_canonical_relation"],
        ["scene_index", "source_chapter_index", "strength_min", "strength_max"],
        ["has_quote", "multi_type_only", "has_reverse_candidates", "has_canonical_relation"],
      )
      const targetGroupId = query.get("group_id") || ""
      const data = targetGroupId
        ? null
        : await api.world.listRelationReviewGroups(params)
      const target = targetGroupId
        ? await findReviewGroup((page) => api.world.listRelationReviewGroups(page), { novel_id: projectId }, targetGroupId)
        : null
      props.relationGroups = targetGroupId ? (target ? [target] : []) : (data.groups || [])
      props.relationItemTotal = targetGroupId ? Number(target?.member_count || 0) : Number(data.item_total || 0)
      props.relationGroupTotal = targetGroupId ? props.relationGroups.length : Number(data.group_total || 0)
    } catch (err) {
      props.relationReviewLoadError = err?.message || "请稍后重试"
    }
  } else if (subView === "relations") {
    try {
      const filters = worldSession.relationListFilters
      const data = await api.world.listRelationships({
        novel_id: projectId,
        q: filters.q,
        skip: filters.skip,
        limit: filters.limit,
        status: "canonical",
      })
      props.relations = data.items || data || []
      props.relationsTotal = Number(data.total ?? props.relations.length) || 0
    } catch {
      props.relationsLoadError = "加载关系失败。"
    }
  } else if (subView === "aliases") {
    try {
      const filters = worldSession.aliasListFilters
      const data = await api.world.listAliases({
        novel_id: projectId,
        q: filters.q,
        skip: filters.skip,
        limit: filters.limit,
        display_state: "active",
      })
      props.aliases = data.items || data || []
      props.aliasesTotal = Number(data.total ?? props.aliases.length) || 0
    } catch {
      props.aliasesLoadError = "加载别名失败。"
    }
  } else if (subView === "bible") {
    const [pages, categories, drafts, synopsis, pageTemplates, activationProfiles, validationRun, validationPolicy] = await Promise.all([
      api.world.listBiblePages({ novel_id: projectId }),
      api.world.listBibleCategories(projectId, true),
      api.world.listBibleDrafts(projectId),
      api.world.getBibleSynopsis(projectId),
      api.world.listBiblePageTemplates
        ? api.world.listBiblePageTemplates(projectId)
        : Promise.resolve({ items: [] }),
      api.context?.listActivationProfiles
        ? api.context.listActivationProfiles(projectId, true)
        : Promise.resolve({ items: [] }),
      api.world.getLatestWorldValidationRun
        ? api.world.getLatestWorldValidationRun(projectId).catch(() => null)
        : Promise.resolve(null),
      api.world.getWorldValidationPolicyStatus
        ? api.world.getWorldValidationPolicyStatus(projectId).catch(() => ({ active: false }))
        : Promise.resolve({ active: false }),
    ])
    props.bible = {
      pages: pages?.items || [],
      categories: categories?.items || [],
      drafts: drafts?.items || [],
      synopsis: synopsis || null,
      pageTemplates: pageTemplates?.items || [],
      activationProfiles: activationProfiles?.items || [],
      validationRun,
      validationPolicy,
    }
  }
  return props
}

export function registerWorldIsland() {
  const router = getRouter()
  if (!router) {
    console.error("worldIsland: router 尚未就绪，island 注册跳过")
    return
  }
  const island = mountIsland({
    viewName: "world",
    component: WorldView,
    load: loadWorld,
  })
  const baseOnLeave = island.onLeave
  island.onLeave = () => {
    // 对齐 vanilla onLeave（worldView.js:696-706）：离开 world 停两条轮询线；
    // island 重挂载（query-only/forceRefresh）不经过这里，轮询不受影响。
    autoExtractManager.stop()
    fusionManager.stop()
    markWorldLeft()
    baseOnLeave()
  }
  router.registerView("world", island)
}

registerWorldIsland()
