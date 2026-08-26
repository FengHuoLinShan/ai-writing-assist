/**
 * generate Vue island 注册入口。由 app.js import 并注册到现有 hash router。
 */
import { mountIsland } from "./mountIsland.js"
import { getApi, getAppState, getRouteQuery, getRouter, getToast } from "./bridge/index.js"
import GenerateView from "./views/generate/GenerateView.vue"
import {
  clearCreativeContinuation,
  generateSessionKey,
  readCreativeContinuation,
  readGenerateSession,
} from "./views/generate/generateSession.js"
import { OBJECT_TEMPLATES, PAGE_SIZE, convergenceDraftFromCheckpoint, listItems, normalizeTemplate } from "./views/generate/logic/generateLogic.js"

const VALID_TABS = new Set(["world", "task", "preview", "pov_prose"])
const VALID_TARGETS = new Set(["core_entity", "world_bible_page", "world_bible_new_page"])

async function loadAll(fetchPage) {
  const output = []
  let skip = 0
  while (true) {
    const data = await fetchPage(skip)
    const page = Array.isArray(data?.items) ? data.items : []
    output.push(...page)
    const total = Number(data?.total)
    if (page.length < PAGE_SIZE || (Number.isFinite(total) && output.length >= total)) return output
    if (!page.length) return output
    skip += page.length
  }
}

async function findSuggestion(api, projectId, suggestionId, status) {
  let skip = 0
  const limit = 200
  while (true) {
    const data = await api.world.listSuggestions({
      novel_id: projectId,
      source_module: "world",
      review_group: "generation_center",
      status,
      skip,
      limit,
    })
    const items = listItems(data)
    const match = items.find((item) => item.id === suggestionId)
    if (match) return match
    skip += items.length
    if (!items.length || skip >= Number(data?.total || 0)) return null
  }
}

function suggestionResult(item, sourcePageId, targetKind) {
  if (!item) return null
  const payload = item.payload_json || {}
  if (item.target_type === "core_entity_draft" && targetKind === "core_entity") {
    return { kind: "core_entity", suggestion: item, proposal: payload }
  }
  if (
    item.target_type === "world_bible_page_draft"
    && payload.operation === "replace_existing"
    && targetKind === "world_bible_page"
    && payload.target_page_id === sourcePageId
  ) return { kind: "world_bible_page", suggestion: item, proposal: payload }
  if (
    item.target_type === "world_bible_page_draft"
    && payload.operation === "create_new"
    && targetKind === "world_bible_new_page"
  ) return { kind: "world_bible_new_page", suggestion: item, proposal: payload }
  return null
}

async function restoreSuggestion(api, projectId, suggestionId, sourcePageId, targetKind) {
  if (!suggestionId || !api?.world?.listSuggestions) return null
  const current = await findSuggestion(api, projectId, suggestionId, "pending")
  const result = suggestionResult(current, sourcePageId, targetKind)
  if (!result) return null
  const predecessorId = current.revision_link?.predecessor_suggestion_id
  const predecessor = predecessorId
    ? await findSuggestion(api, projectId, predecessorId, "rejected")
    : null
  return {
    result,
    previousResult: suggestionResult(predecessor, sourcePageId, targetKind),
  }
}

export async function loadGenerate(options = {}) {
  const api = getApi()
  const appState = getAppState()
  const toast = getToast()
  const projectId = options.projectId ?? appState?.currentProjectId ?? null
  const query = options.query
    ? new URLSearchParams(options.query)
    : getRouteQuery()
  const tab = VALID_TABS.has(options.tab) ? options.tab : VALID_TABS.has(query.get("tab")) ? query.get("tab") : "world"
  const preset = options.preset === "world_core"
    ? "world_core"
    : options.preset || (query.get("preset") === "world_core" ? "world_core" : query.get("preset") || "custom")
  const sourcePageId = preset === "world_core" ? null : (options.sourcePageId ?? (query.get("source_page_id") || null))
  const targetKind = preset === "world_core"
    ? "core_entity"
    : VALID_TARGETS.has(options.targetKind) ? options.targetKind : VALID_TARGETS.has(query.get("target")) ? query.get("target") : "core_entity"
  const checkpointId = preset === "world_core" ? (options.checkpointId ?? (query.get("checkpoint_id") || null)) : null
  const sessionKey = generateSessionKey(projectId, sourcePageId, targetKind, preset)
  const notices = new Set()
  const readSession = (key) => readGenerateSession(key, {
    notify(code, message) {
      if (notices.has(code)) return
      notices.add(code)
      toast(message, "warning")
    },
  })
  const session = readSession(sessionKey)
  if (preset === "world_core") session.selectedTemplateId = "builtin:none"
  const props = {
    projectId,
    tab,
    preset,
    sourcePageId,
    targetKind,
    sessionKey,
    initialSession: session,
    templates: [...OBJECT_TEMPLATES],
    activationProfiles: [],
    sourcePage: null,
    sourceDraft: null,
    worldCategories: [],
    worldPageTemplates: [],
    worldPages: [],
    worldScenes: [],
    worldThreads: [],
    worldCharacters: [],
    worldEntities: [],
    worldWorkspaceWarning: null,
    worldSourceUnavailable: false,
    restoredWorldResult: null,
    restoredPreviousWorldResult: null,
    povChapters: [],
    povCharacters: [],
    povLoadWarning: null,
  }
  if (!projectId || !api) return props

  let checkpointWarning = null
  const checkpointPromise = (async () => {
    if (!checkpointId || !api.world?.getAdoptionArtifact) return
    try {
      const artifact = await api.world.getAdoptionArtifact(checkpointId, projectId)
      const restored = convergenceDraftFromCheckpoint(artifact)
      if (!restored) throw new Error("阶段成果类型不匹配")
      session.checkpointId = checkpointId
      session.successfulRounds = Math.max(session.successfulRounds || 0, Number(artifact.payload_json?.round_no || 0))
      session.checkpointRound = Math.max(session.checkpointRound || 0, Number(artifact.payload_json?.round_no || 0))
      session.checkpointDepth = artifact.payload_json?.depth || null
      if (!session.convergenceDraft) session.convergenceDraft = restored
    } catch (err) {
      checkpointWarning = `已保存的阶段成果无法恢复：${err?.message || "未知错误"}`
    }
  })()

  let templateWarning = null
  const templatesPromise = (async () => {
    try {
      const data = await api.generate.listPromptTemplates(projectId)
      const items = listItems(data)
      props.templates = items.length ? items.map(normalizeTemplate) : [...OBJECT_TEMPLATES]
    } catch (err) {
      templateWarning = `模板加载失败：${err?.message || "未知错误"}`
      toast(templateWarning, "warning")
    }
  })()
  const profilesPromise = (async () => {
    try {
      const data = await api.context.listActivationProfiles(projectId)
      props.activationProfiles = listItems(data).filter((item) => item.status === "published")
    } catch (err) {
      toast(`AI 参考规则加载失败：${err?.message || "未知错误"}`, "warning")
    }
  })()

  let tabPromise = Promise.resolve()
  if (tab === "world") {
    tabPromise = (async () => {
      try {
        const [pages, drafts, categories, pageTemplates, scenes, threads, characters, entities] = await Promise.all([
          api.world.listBiblePages({ novel_id: projectId }),
          api.world.listBibleDrafts(projectId),
          api.world.listBibleCategories(projectId),
          api.world.listBiblePageTemplates(projectId),
          api.outline.listScenesOrdered(projectId),
          api.outline.listThreads(projectId, { limit: 50 }),
          loadAll((skip) => api.world.listCharacters({ novel_id: projectId, skip, limit: PAGE_SIZE })),
          loadAll((skip) => api.world.listEntities({ novel_id: projectId, display_state: "active", skip, limit: PAGE_SIZE })),
        ])
        const pageItems = listItems(pages)
        const draftItems = listItems(drafts)
        props.sourcePage = sourcePageId ? pageItems.find((item) => item.id === sourcePageId) || null : null
        props.sourceDraft = sourcePageId ? draftItems.find((item) => item.page_id === sourcePageId) || null : null
        props.worldCategories = listItems(categories)
        props.worldPageTemplates = listItems(pageTemplates)
        props.worldPages = pageItems.filter((item) => ["canonical", "confirmed"].includes(item.status))
        props.worldScenes = listItems(scenes)
        props.worldThreads = listItems(threads)
        props.worldCharacters = characters
        const characterIds = new Set(characters.flatMap((item) => [item.id, item.entity_id].filter(Boolean)))
        props.worldEntities = entities.filter((item) => item.entity_type !== "character" && !characterIds.has(item.id))
        if (sourcePageId && !props.sourcePage) {
          props.worldSourceUnavailable = true
          props.worldWorkspaceWarning = "原来源页面已变化。本地对话和未发送内容仍保留，请返回世界笔记选择新的目标。"
          const continuation = readCreativeContinuation(projectId)
          if (
            continuation?.destination === "generate"
            && continuation.route.source_page_id === sourcePageId
            && continuation.route.target === targetKind
            && (continuation.route.preset || "custom") === preset
          ) {
            clearCreativeContinuation(projectId)
          }
        } else {
          const restored = await restoreSuggestion(api, projectId, session.suggestionId, sourcePageId, targetKind)
          props.restoredWorldResult = restored?.result || null
          props.restoredPreviousWorldResult = restored?.previousResult || null
        }
      } catch (err) {
        props.worldSourceUnavailable = Boolean(sourcePageId)
        props.worldWorkspaceWarning = sourcePageId
          ? `原来源与生成上下文暂时无法核对：${err?.message || "未知错误"}。本地对话和未发送内容仍保留，请稍后重试或返回世界笔记。`
          : `生成上下文加载不完整：${err?.message || "未知错误"}`
      }
    })()
  }

  if (tab === "pov_prose") {
    tabPromise = (async () => {
      try {
        const [chapters, characters] = await Promise.all([
          api.writing.listChapters(projectId),
          loadAll((skip) => api.world.listCharacters({ novel_id: projectId, skip, limit: PAGE_SIZE })),
        ])
        props.povChapters = Array.isArray(chapters?.chapters) ? chapters.chapters : []
        props.povCharacters = characters
      } catch {
        props.povLoadWarning = "章节或角色暂时无法加载，请稍后重试。"
      }
    })()
  }
  await Promise.all([checkpointPromise, templatesPromise, profilesPromise, tabPromise])
  props.worldWorkspaceWarning ||= templateWarning || checkpointWarning
  return props
}

export const generateIsland = mountIsland({ viewName: "generate", component: GenerateView, load: loadGenerate })

export function registerGenerateIsland() {
  getRouter()?.registerView?.("generate", generateIsland)
}

registerGenerateIsland()
