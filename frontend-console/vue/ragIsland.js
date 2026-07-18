/**
 * rag 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 * 替代原 views/ragView.js；load 对应 vanilla onEnter
 * （status/evidenceHealth/characters 分页/scenes + 检索会话重置）。
 */
import { mountIsland } from "./mountIsland.js"
import RagView from "./views/rag/RagView.vue"
import { getApi, getAppState, getRouter } from "./bridge/index.js"
import { resetRagSearchSession } from "./views/rag/ragSearchSession.js"
import { ensurePrewarm } from "./views/rag/prewarmManager.js"

const CHARACTER_PAGE_SIZE = 50

/** 对应 vanilla _loadAllCharacters：按 50/页拉全人物列表。 */
async function loadAllCharacters(novelId) {
  const api = getApi()
  const characters = []
  let skip = 0
  while (true) {
    const result = await api.world.listCharacters({
      novel_id: novelId,
      skip,
      limit: CHARACTER_PAGE_SIZE,
    })
    const page = Array.isArray(result) ? result : (result?.items || [])
    characters.push(...page)
    const total = Number(result?.total)
    if (
      !Number.isFinite(total)
      || characters.length >= total
      || page.length < CHARACTER_PAGE_SIZE
    ) {
      return characters
    }
    skip += page.length
  }
}

async function loadRag() {
  // 对应 vanilla onEnter 开头的 _resetSearchState()
  resetRagSearchSession()
  const state = getAppState()
  const projectId = state?.currentProjectId
  if (!projectId) {
    return { projectId: null, apiAvailable: false }
  }

  const api = getApi()
  let status = null
  let apiAvailable = false
  try {
    status = await api.rag.status(projectId)
    apiAvailable = true
  } catch {
    status = null
  }

  // vanilla onEnter 的后台预热触发点：island load 即 vanilla onEnter；
  // 请求由模块级 prewarmManager 去重，不随 island 重挂载反复重启（P2 评审）
  if (apiAvailable && (status?.total || 0) > 0 && !status?.embedding_runtime?.healthy) {
    void ensurePrewarm()
  }

  let evidenceHealth = null
  if (api.context?.evidenceHealth) {
    try {
      evidenceHealth = await api.context.evidenceHealth(projectId, "canonical", 24)
    } catch {
      evidenceHealth = null
    }
  }

  let characters = []
  if (api.world?.listCharacters) {
    try {
      characters = await loadAllCharacters(projectId)
    } catch {
      characters = []
    }
  }

  let scenes = []
  if (api.outline?.listScenesOrdered) {
    try {
      const result = await api.outline.listScenesOrdered(projectId)
      scenes = Array.isArray(result) ? result : (result?.items || [])
    } catch {
      scenes = []
    }
  }

  return { projectId, apiAvailable, status, evidenceHealth, characters, scenes }
}

export function registerRagIsland() {
  const router = getRouter()
  if (!router) {
    console.error("ragIsland: router 尚未就绪，island 注册跳过")
    return
  }
  router.registerView("rag", mountIsland({
    viewName: "rag",
    component: RagView,
    load: loadRag,
  }))
}

registerRagIsland()
