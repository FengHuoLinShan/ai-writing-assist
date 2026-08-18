/**
 * Writing 的显式会话层。
 *
 * Vue island 不依赖 router 的 DocumentFragment keep-alive；尚未提交的输入按
 * project + chapter 隔离保存在这里，并由 editorController 同步写入本地备份。
 * 本模块只保存浏览器会话状态，不发请求、不操作 DOM。
 */

const sessions = new Map()
const POINTER_VERSION = 1

function pointerKey(projectId) {
  return `writing_resume_pointer:v${POINTER_VERSION}:${projectId}`
}

function validPointer(projectId, value) {
  const chapter = Number(value?.chapter)
  if (value?.projectId !== projectId || !Number.isInteger(chapter) || chapter < 1) return null
  return {
    projectId,
    chapter,
    draftId: typeof value.draftId === "string" && value.draftId ? value.draftId : null,
    sceneId: typeof value.sceneId === "string" && value.sceneId ? value.sceneId : null,
    cursorOffset: Math.max(0, Number(value.cursorOffset) || 0),
    updatedAt: Number(value.updatedAt) || 0,
  }
}

export function readWritingPointer(projectId) {
  if (!projectId) return null
  try {
    return validPointer(projectId, JSON.parse(localStorage.getItem(pointerKey(projectId)) || "null"))
  } catch {
    return null
  }
}

function persistPointer(projectId, patch = {}) {
  const previous = readWritingPointer(projectId) || { projectId }
  const pointer = validPointer(projectId, { ...previous, ...patch, updatedAt: Date.now() })
  if (!pointer) return
  try { localStorage.setItem(pointerKey(projectId), JSON.stringify(pointer)) } catch { /* storage unavailable */ }
}

function newSession(projectId) {
  const pointer = readWritingPointer(projectId)
  return {
    projectId,
    currentChapter: pointer?.chapter || null,
    currentDraftId: pointer?.draftId || null,
    currentSceneId: pointer?.sceneId || null,
    sceneByChapter: new Map(pointer?.sceneId ? [[pointer.chapter, pointer.sceneId]] : []),
    chapters: new Map(),
  }
}

export function getWritingSession(projectId) {
  if (!projectId) return null
  if (!sessions.has(projectId)) sessions.set(projectId, newSession(projectId))
  return sessions.get(projectId)
}

export function rememberWritingLocation(projectId, location = {}) {
  const session = getWritingSession(projectId)
  if (!session) return
  session.currentChapter = location.currentChapter ?? session.currentChapter
  session.currentDraftId = location.currentDraftId ?? session.currentDraftId
  if (Object.hasOwn(location, "currentSceneId")) {
    session.currentSceneId = location.currentSceneId || null
    const chapter = Number(location.currentChapter ?? session.currentChapter)
    if (Number.isInteger(chapter) && chapter > 0) {
      if (location.currentSceneId) session.sceneByChapter.set(chapter, location.currentSceneId)
      else session.sceneByChapter.delete(chapter)
    }
  }
  const chapter = Number(session.currentChapter)
  if (Number.isInteger(chapter) && chapter > 0) {
    persistPointer(projectId, {
      chapter,
      draftId: session.currentDraftId,
      sceneId: session.currentSceneId,
      ...(Object.hasOwn(location, "cursorOffset") ? { cursorOffset: location.cursorOffset } : {}),
    })
  }
}

export function rememberedSceneForChapter(projectId, chapter) {
  return getWritingSession(projectId)?.sceneByChapter.get(Number(chapter)) || null
}

export function rememberChapterSnapshot(projectId, snapshot = {}) {
  const chapter = Number(snapshot.chapter)
  const session = getWritingSession(projectId)
  if (!session || !Number.isInteger(chapter) || chapter < 1) return
  const next = {
    projectId,
    chapter,
    draftId: snapshot.draftId || null,
    versionNumber: snapshot.versionNumber ?? null,
    updatedAt: snapshot.updatedAt || null,
    status: snapshot.status || "draft",
    readonly: snapshot.readonly === true,
    title: String(snapshot.title || ""),
    content: String(snapshot.content || ""),
    lastSavedTitle: String(snapshot.lastSavedTitle || ""),
    lastSavedContent: String(snapshot.lastSavedContent || ""),
    dirty: snapshot.dirty === true,
    cursorOffset: Number(snapshot.cursorOffset) || 0,
    restoreSourceVersion: snapshot.restoreSourceVersion ?? null,
    restoreExpectedVersion: snapshot.restoreExpectedVersion ?? null,
    restoreExpectedUpdatedAt: snapshot.restoreExpectedUpdatedAt || null,
  }
  session.currentChapter = chapter
  session.currentDraftId = next.draftId
  session.chapters.set(chapter, next)
  persistPointer(projectId, {
    chapter,
    draftId: next.draftId,
    sceneId: session.sceneByChapter.get(chapter) || null,
    cursorOffset: next.cursorOffset,
  })
}

export function readChapterSnapshot(projectId, chapter) {
  const item = getWritingSession(projectId)?.chapters.get(Number(chapter))
  return item ? { ...item } : null
}

export function clearChapterSnapshot(projectId, chapter) {
  const session = sessions.get(projectId)
  if (!session) return
  session.chapters.delete(Number(chapter))
  session.sceneByChapter.delete(Number(chapter))
  if (session.currentChapter === Number(chapter)) {
    session.currentChapter = null
    session.currentDraftId = null
    session.currentSceneId = null
  }
}

/** 测试及项目永久移除后的清理入口。 */
export function clearWritingSession(projectId = null) {
  if (projectId) {
    sessions.delete(projectId)
    try { localStorage.removeItem(pointerKey(projectId)) } catch { /* noop */ }
  } else sessions.clear()
}

/** Simulate a page reload without deleting the durable pointer. */
export function forgetWritingSessionMemory(projectId = null) {
  if (projectId) sessions.delete(projectId)
  else sessions.clear()
}
