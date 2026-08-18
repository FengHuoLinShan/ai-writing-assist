export const ACCOUNT_MARKER_KEY = "novel_accountId"
export const ACCOUNT_INVALIDATED_EVENT = "novel:account-invalidated"
const THEME_STORAGE_KEY = "novel_theme"

const LOCAL_STORAGE_PREFIXES = Object.freeze([
  "novel_",
  "draft_backup_",
  "generate_world_workspace_state_v2_",
  "writing_scene_cockpit_order:",
  "writing_resume_pointer:v1:",
  "worldBible:",
  "worldBibleProjection:",
  "_errorLog:",
])

const LOCAL_STORAGE_KEYS = new Set(["_errorLog"])
const SESSION_STORAGE_PREFIXES = Object.freeze([
  "novel_",
  "workspace-rail:",
  "workflow-progress-card:",
  "workflow-progress-details:",
])

function storageKeys(storage) {
  if (!storage) return []
  try {
    const keys = []
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (key !== null) keys.push(key)
    }
    return keys
  } catch {
    return []
  }
}

function clearMatchingStorage(storage, prefixes, {
  exactKeys = new Set(),
  preservedKeys = new Set(),
} = {}) {
  let removed = 0
  for (const key of storageKeys(storage)) {
    const owned = exactKeys.has(key) || prefixes.some((prefix) => key.startsWith(prefix))
    if (preservedKeys.has(key) || !owned) continue
    try {
      storage.removeItem(key)
      removed += 1
    } catch {
      // Storage may be unavailable in privacy mode; continue clearing the remaining keys.
    }
  }
  return removed
}

export function clearAccountScopedBrowserStorage({
  local = globalThis.localStorage,
  session = globalThis.sessionStorage,
  preserveAccountMarker = false,
} = {}) {
  const preservedLocalKeys = new Set([THEME_STORAGE_KEY])
  if (preserveAccountMarker) preservedLocalKeys.add(ACCOUNT_MARKER_KEY)
  return {
    local: clearMatchingStorage(local, LOCAL_STORAGE_PREFIXES, {
      exactKeys: LOCAL_STORAGE_KEYS,
      preservedKeys: preservedLocalKeys,
    }),
    session: clearMatchingStorage(session, SESSION_STORAGE_PREFIXES),
  }
}

export function invalidateAccountBrowserState({
  reason = "account-invalidated",
  local = globalThis.localStorage,
  session = globalThis.sessionStorage,
  preserveAccountMarker = false,
  eventTarget = globalThis.window ?? globalThis,
} = {}) {
  const removed = clearAccountScopedBrowserStorage({
    local,
    session,
    preserveAccountMarker,
  })
  let handled = false
  if (typeof eventTarget?.dispatchEvent === "function" && typeof CustomEvent === "function") {
    const event = new CustomEvent(ACCOUNT_INVALIDATED_EVENT, {
      cancelable: true,
      detail: { reason },
    })
    handled = eventTarget.dispatchEvent(event) === false
  }
  return { ...removed, handled }
}

export function forceAccountSafeReload({
  reload = () => globalThis.location?.reload?.(),
  ...options
} = {}) {
  const result = invalidateAccountBrowserState(options)
  if (!result.handled) reload()
  return result
}

export function scopeBrowserStorageToAccount(accountId, {
  local = globalThis.localStorage,
  session = globalThis.sessionStorage,
} = {}) {
  if (!accountId) return false
  const nextAccountId = String(accountId)
  let previousAccountId = null
  try { previousAccountId = local?.getItem(ACCOUNT_MARKER_KEY) ?? null } catch {}
  if (previousAccountId === nextAccountId) return false

  clearAccountScopedBrowserStorage({ local, session })
  try { local?.setItem(ACCOUNT_MARKER_KEY, nextAccountId) } catch {}
  return true
}
