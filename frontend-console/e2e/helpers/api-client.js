/**
 * 后端 API 客户端 — 供 E2E 测试的 setup / teardown 使用
 *
 * 绕过前端，直接调用后端 REST API 创建/清理测试数据。
 */

const API_BASE = "http://localhost:8000/api"

async function request(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...options.headers,
    },
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
  try { await request(`/projects/${id}/permanent`, { method: "DELETE" }) } catch {}
}

export async function listProjects() {
  return request("/projects")
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

export async function getTask(taskId) {
  const resp = await fetch(`${API_BASE}/tasks/${taskId}`)
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

export async function listChapters(novelId) {
  return request(`/writing/chapters?novel_id=${encodeURIComponent(novelId)}`)
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

// ---- World helpers ----

export async function createEntity(novelId, data) {
  return request(`/world/entities?novel_id=${encodeURIComponent(novelId)}`, {
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
