import { getLocalDraftAccountScope } from '../bridge/index.js'

function key(projectId) {
  const account = getLocalDraftAccountScope()
  return account && projectId ? `writing_object_return:${account}:${projectId}` : null
}

export async function writingContentHash(content) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(content))
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}

export function rememberWritingObjectReturn(projectId, location) {
  const storageKey = key(projectId)
  if (!storageKey) throw new Error('无法核对账户，正文位置尚未保存。')
  sessionStorage.setItem(storageKey, JSON.stringify(location))
}

export function readWritingObjectReturn(projectId, entityId) {
  try {
    const storageKey = key(projectId)
    const location = storageKey ? JSON.parse(sessionStorage.getItem(storageKey) || 'null') : null
    if (location?.entityId !== entityId || !Number.isInteger(location.chapterIndex) || location.chapterIndex < 1
      || !Number.isInteger(location.start) || !Number.isInteger(location.end) || location.start < 0 || location.end < location.start
      || !/^[a-f0-9]{64}$/.test(location.contentHash || '')) return null
    return location
  } catch { return null }
}
