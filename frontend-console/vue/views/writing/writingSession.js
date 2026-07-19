/**
 * Writing 的显式会话层。
 *
 * Vue island 不依赖 router 的 DocumentFragment keep-alive；尚未提交的输入按
 * project + chapter 隔离保存在这里，并由 editorController 同步写入本地备份。
 * 本模块只保存浏览器会话状态，不发请求、不操作 DOM。
 */

const sessions = new Map()

function newSession(projectId) {
  return {
    projectId,
    currentChapter: null,
    currentDraftId: null,
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
}

export function readChapterSnapshot(projectId, chapter) {
  const item = getWritingSession(projectId)?.chapters.get(Number(chapter))
  return item ? { ...item } : null
}

export function clearChapterSnapshot(projectId, chapter) {
  const session = sessions.get(projectId)
  if (!session) return
  session.chapters.delete(Number(chapter))
  if (session.currentChapter === Number(chapter)) {
    session.currentChapter = null
    session.currentDraftId = null
  }
}

/** 测试及项目永久移除后的清理入口。 */
export function clearWritingSession(projectId = null) {
  if (projectId) sessions.delete(projectId)
  else sessions.clear()
}
