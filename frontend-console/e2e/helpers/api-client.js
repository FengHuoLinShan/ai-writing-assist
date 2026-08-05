/**
 * 后端 API 客户端 — 供 E2E 测试的 setup / teardown 使用
 *
 * 绕过前端，直接调用后端 REST API 创建/清理测试数据。
 */

import "../../apiContracts.js"

const backendPort = process.env.BACKEND_PORT || "8000"
const rawApiHost = process.env.API_HOST || `http://localhost:${backendPort}`
export const API_HOST = rawApiHost.endsWith("/api") ? rawApiHost.slice(0, -4) : rawApiHost
export const API_BASE = `${API_HOST}/api`
const DEFAULT_TIMEOUT = 15000

async function request(path, options = {}) {
  const { timeout, signal: externalSignal, ...fetchOptions } = options
  const method = (fetchOptions.method || "GET").toUpperCase()
  const headers = {
    Accept: "application/json",
  }
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] = "XMLHttpRequest"
  }
  const isFormData = typeof FormData !== "undefined"
    && fetchOptions.body instanceof FormData
  if (method !== "GET" && method !== "DELETE" && !isFormData) {
    headers["Content-Type"] = "application/json"
  }

  const controller = new AbortController()
  const timeoutMs = timeout || DEFAULT_TIMEOUT
  let timeoutFired = false
  const timeoutId = setTimeout(() => {
    timeoutFired = true
    controller.abort()
  }, timeoutMs)
  let signal = controller.signal
  let externalAbortHandler = null
  if (externalSignal) {
    if (typeof AbortSignal !== "undefined" && AbortSignal.any) {
      signal = AbortSignal.any([controller.signal, externalSignal])
    } else {
      externalAbortHandler = () => controller.abort()
      if (externalSignal.aborted) controller.abort()
      else externalSignal.addEventListener("abort", externalAbortHandler, { once: true })
    }
  }

  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: { ...headers, ...fetchOptions.headers },
      signal,
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(`API ${path} failed (${resp.status}): ${text}`)
    }
    if (resp.status === 204) return null
    return resp.json()
  } catch (err) {
    if (timeoutFired && err?.name === "AbortError") {
      throw new Error(`API ${path} timed out after ${timeoutMs}ms`)
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
    if (externalAbortHandler && externalSignal) {
      externalSignal.removeEventListener("abort", externalAbortHandler)
    }
  }
}

async function requestContract(name, params = {}, query = {}, options = {}) {
  const requestSpec = globalThis.apiContracts.contractRequest(
    name,
    params,
    query,
    options,
  )
  return request(requestSpec.path, requestSpec.options)
}

export async function createProject(payload) {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function connectAccountLLMProvider(providerId, apiKey) {
  return request(`/settings/llm-connections/${providerId}`, {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  })
}

export async function clearAccountLLMProvider(providerId) {
  return request(`/settings/llm-connections/${providerId}`, {
    method: "DELETE",
  })
}

export async function deleteProject(id) {
  return request(`/projects/${id}`, { method: "DELETE" })
}

/** 永久删除项目（先软删再硬删，用于测试清理，不留回收站残留） */
export async function cleanupProject(id) {
  try { await deleteProject(id) } catch {}
  try { await request(`/projects/${id}/permanent?confirmed=true`, { method: "DELETE" }) } catch {}
}

/** 严格清理真实凭据 E2E 项目；任一步失败都必须让测试失败。 */
export async function cleanupProjectStrict(id) {
  await deleteProject(id)
  await request(`/projects/${id}/permanent?confirmed=true`, { method: "DELETE" })
}

export async function healthCheck() {
  try {
    const resp = await fetch(`${API_BASE}/health`)
    return resp.ok
  } catch {
    return false
  }
}

export async function waitForBackend(maxWaitMs = 30000) {
  const start = Date.now()
  while (Date.now() - start < maxWaitMs) {
    if (await healthCheck()) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error("Backend did not become healthy in time")
}

export async function getTask(taskId, novelId) {
  const query = novelId ? `?novel_id=${encodeURIComponent(novelId)}` : ""
  const resp = await fetch(`${API_BASE}/tasks/${taskId}${query}`)
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`Task ${taskId} failed (${resp.status}): ${text}`)
  }
  return resp.json()
}

// ---- Writing helpers ----

export async function createDraft(novelId, chapterIndex, title, content) {
  return request(`/writing/drafts?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, chapter_index: chapterIndex, title, content }),
  })
}

export async function createAutosavedDraft(novelId, chapterIndex, title, content) {
  return request("/writing/drafts/autosave", {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, chapter_index: chapterIndex, title, content }),
  })
}

export async function deleteDraft(novelId, draftId) {
  return request(`/writing/drafts/${draftId}?novel_id=${encodeURIComponent(novelId)}`, {
    method: "DELETE",
  })
}

export async function getLatestDraft(novelId, chapterIndex) {
  return request(`/writing/chapters/${chapterIndex}/draft?novel_id=${encodeURIComponent(novelId)}`)
}

export async function listChapters(novelId) {
  return request(`/writing/chapters?novel_id=${encodeURIComponent(novelId)}`)
}

export async function listConflictChecks(novelId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) query.set(key, String(value))
  }
  return request(`/writing/conflict-checks?${query.toString()}`)
}

// ---- Outline helpers ----

export async function createScene(novelId, data) {
  return request(`/outline/scenes?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function listScenesOrdered(novelId) {
  return request(`/outline/scenes/ordered?novel_id=${encodeURIComponent(novelId)}`)
}

export async function listScenes(novelId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value))
  }
  return request(`/outline/scenes?${query.toString()}`)
}

export async function createThread(novelId, data) {
  return request(`/outline/threads?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createArc(novelId, data) {
  return request(`/outline/arcs?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createStoryOutlineRevision(novelId, data) {
  return request(
    `/outline/story-outline/revisions?novel_id=${encodeURIComponent(novelId)}`,
    {
      method: "POST",
      body: JSON.stringify(data),
    },
  )
}

export async function createForeshadowing(novelId, data) {
  return request(`/outline/foreshadowing?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createReveal(novelId, data) {
  return request(`/outline/reveals?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

// ---- World helpers ----

export async function createEntity(novelId, data) {
  return request(`/world/entities?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function listEntityTypes(novelId) {
  return request(`/world/entity-types?novel_id=${encodeURIComponent(novelId)}`)
}

export async function createAlias(novelId, data) {
  return request(`/world/aliases?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createRelation(novelId, data) {
  return request(`/world/relations?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function listRelations(novelId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value))
  }
  return request(`/world/relations?${query.toString()}`)
}

export async function listAliases(novelId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value))
  }
  return request(`/world/aliases?${query.toString()}`)
}

export async function createCharacter(novelId, data) {
  return request(`/world/characters?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createWorldBiblePage(novelId, data) {
  return request("/world/bible/pages", {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, ...data }),
  })
}

export async function getWorldBiblePage(novelId, pageId) {
  return request(`/world/bible/pages/${pageId}?novel_id=${encodeURIComponent(novelId)}`)
}

export async function createWorldBibleDraft(novelId, data) {
  return request("/world/bible/drafts", {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, ...data }),
  })
}

export async function listWorldBibleDrafts(novelId) {
  return request(`/world/bible/drafts?novel_id=${encodeURIComponent(novelId)}`)
}

/** 为实体插入 TextArchive 记录（E2E 回滚测试种子） */
export async function seedEntityArchive(novelId, entityId, textContent, opts = {}) {
  const { fieldName = "summary", sceneIndex = 5 } = opts
  return request(`/world/_test/entities/${entityId}/text-archive`, {
    method: "POST",
    body: JSON.stringify({
      novel_id: novelId,
      field_name: fieldName,
      text_content: textContent,
      scene_index: sceneIndex,
    }),
  })
}

// ---- Map helpers ----

export async function listMaps(novelId, params = {}) {
  return requestContract("world.listMaps", {}, { novel_id: novelId, ...params })
}

export async function applyMapEditor(novelId, mapId, data) {
  return requestContract("world.applyMapEditor", { mapId }, { novel_id: novelId }, {
    body: data,
  })
}

export async function getMapLayerTree(novelId, mapId) {
  return requestContract("world.getMapLayerTree", { mapId }, { novel_id: novelId })
}

export async function getMapPaths(novelId, mapId, status = "active") {
  return requestContract("world.getMapPaths", { mapId }, { novel_id: novelId, status })
}

export async function getEntityMapPresence(novelId, entityId, includeCandidates = false) {
  return requestContract("world.getEntityMapPresence", { id: entityId }, {
    novel_id: novelId,
    include_candidates: includeCandidates || undefined,
  })
}

export async function createMap(novelId, data) {
  return request(`/world/maps?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function getMapState(novelId, mapId, sceneId = null) {
  return requestContract("world.getMapState", { mapId }, {
    novel_id: novelId,
    scene_id: sceneId,
  })
}

export async function getMapDashboard(novelId, mapId, params = {}) {
  return requestContract("world.getMapDashboard", { mapId }, {
    novel_id: novelId,
    scene_id: params.sceneId,
    focus_entity_id: params.focusEntityId,
  })
}

export async function getMapPlayback(novelId, mapId, params = {}) {
  return requestContract("world.getMapPlayback", { mapId }, {
    novel_id: novelId,
    scene_id: params.sceneId,
    focus_entity_id: params.focusEntityId,
    include_candidates: params.includeCandidates,
  })
}

export async function createMapObservation(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/observations?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function assignProjectMapObservation(novelId, observation, mapId) {
  const observationId = typeof observation === "object" ? observation.id : observation
  const expectedUpdatedAt = typeof observation === "object" ? observation.updated_at : null
  if (!expectedUpdatedAt) {
    throw new Error("assignProjectMapObservation requires observation.updated_at")
  }
  return requestContract("world.assignProjectMapObservation", { observationId }, { novel_id: novelId }, {
    body: {
      map_id: mapId || null,
      expected_updated_at: expectedUpdatedAt,
    },
  })
}

export async function listMapFacts(novelId, mapId) {
  return request(`/world/maps/${mapId}/facts?novel_id=${encodeURIComponent(novelId)}`)
}

export async function confirmMapObservation(novelId, mapId, observation) {
  const observationId = typeof observation === "object" ? observation.id : observation
  const expectedUpdatedAt = typeof observation === "object" ? observation.updated_at : null
  if (!expectedUpdatedAt) throw new Error("confirmMapObservation requires observation.updated_at")
  return requestContract("world.confirmMapObservation", { mapId, observationId }, { novel_id: novelId }, {
    body: { expected_updated_at: expectedUpdatedAt },
  })
}

export async function runMapBatchAction(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/batch-actions?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function generateMap(novelId, mapId) {
  return request(`/world/maps/${mapId}/generate?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
  })
}

export async function batchUpdateTiles(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/tiles?novel_id=${encodeURIComponent(novelId)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  })
}

export async function createLocationBindings(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/location-bindings?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createMapMarker(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/markers?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function updateMapTerrainLayer(novelId, mapId, layerId, data) {
  return requestContract("world.updateTerrainLayer", { mapId, layerId }, { novel_id: novelId }, {
    body: data,
  })
}

export async function listTerritories(novelId, mapId) {
  return request(`/world/maps/${mapId}/territories?novel_id=${encodeURIComponent(novelId)}`)
}

export async function createTerritories(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/territories?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function deleteTerritoriesByFaction(novelId, mapId, factionEntityId) {
  const params = new URLSearchParams({
    novel_id: novelId,
    faction_entity_id: factionEntityId,
  })
  return request(`/world/maps/${mapId}/territories?${params.toString()}`, {
    method: "DELETE",
  })
}

export async function getFocusState(novelId, mapId, factionEntityId) {
  const params = new URLSearchParams({
    novel_id: novelId,
    faction_entity_id: factionEntityId,
  })
  return request(`/world/maps/${mapId}/focus?${params.toString()}`)
}
