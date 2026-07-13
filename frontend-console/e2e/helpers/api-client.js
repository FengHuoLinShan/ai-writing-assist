/**
 * 后端 API 客户端 — 供 E2E 测试的 setup / teardown 使用
 *
 * 绕过前端，直接调用后端 REST API 创建/清理测试数据。
 */

const backendPort = process.env.BACKEND_PORT || "8000"
const rawApiHost = process.env.API_HOST || `http://localhost:${backendPort}`
export const API_HOST = rawApiHost.endsWith("/api") ? rawApiHost.slice(0, -4) : rawApiHost
export const API_BASE = `${API_HOST}/api`

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase()
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...options.headers,
  }
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] ||= "XMLHttpRequest"
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`API ${path} failed (${resp.status}): ${text}`)
  }
  if (resp.status === 204) return null
  return resp.json()
}

export async function createProject(payload) {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify(payload),
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

export async function createAlias(novelId, data) {
  return request(`/world/aliases?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createCharacter(novelId, data) {
  return request(`/world/characters?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
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

export async function listMaps(novelId) {
  return request(`/world/maps?novel_id=${encodeURIComponent(novelId)}`)
}

export async function createMap(novelId, data) {
  return request(`/world/maps?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function getMapState(novelId, mapId, sceneId = null) {
  const params = new URLSearchParams({ novel_id: novelId })
  if (sceneId) params.set("scene_id", sceneId)
  return request(`/world/maps/${mapId}/state?${params.toString()}`)
}

export async function getMapDashboard(novelId, mapId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  if (params.sceneId) query.set("scene_id", params.sceneId)
  if (params.focusEntityId) query.set("focus_entity_id", params.focusEntityId)
  return request(`/world/maps/${mapId}/dashboard?${query.toString()}`)
}

export async function getMapPlayback(novelId, mapId, params = {}) {
  const query = new URLSearchParams({ novel_id: novelId })
  if (params.sceneId) query.set("scene_id", params.sceneId)
  if (params.focusEntityId) query.set("focus_entity_id", params.focusEntityId)
  if (params.includeCandidates !== undefined) {
    query.set("include_candidates", String(params.includeCandidates))
  }
  return request(`/world/maps/${mapId}/playback?${query.toString()}`)
}

export async function createMapObservation(novelId, mapId, data) {
  return request(`/world/maps/${mapId}/observations?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function confirmMapObservation(novelId, mapId, observationId) {
  return request(`/world/maps/${mapId}/observations/${observationId}/confirm?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
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
