const SCHEMA_VERSION = 1
const SECTION_PATTERN = /^[a-z][a-z0-9-]{0,95}$/

function normalizeScope(scope = {}) {
  const normalized = {
    accountId: typeof scope.accountId === "string" ? scope.accountId.trim() : "",
    projectId: typeof scope.projectId === "string" ? scope.projectId.trim() : "",
    objectId: typeof scope.objectId === "string" ? scope.objectId.trim() : "",
    section: typeof scope.section === "string" ? scope.section.trim() : "",
  }
  if (!normalized.accountId || !normalized.projectId || !normalized.objectId || !SECTION_PATTERN.test(normalized.section)) return null
  return normalized
}

function keyFor(scope) {
  return "author-workspace-draft:v1:" + [scope.accountId, scope.projectId, scope.objectId, scope.section].map(encodeURIComponent).join(":")
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

export function readLocalDraftBackup(storage, requestedScope) {
  const scope = normalizeScope(requestedScope)
  if (!scope) return { ok: false, reason: "invalid_scope" }
  if (!storage) return { ok: false, reason: "storage_unavailable" }
  const key = keyFor(scope)
  try {
    const serialized = storage.getItem(key)
    if (serialized == null) return { ok: true, key, draft: null }
    const record = JSON.parse(serialized)
    if (!isRecord(record) || record.schema_version !== SCHEMA_VERSION
      || !isRecord(record.scope) || Object.entries(scope).some(([name, value]) => record.scope[name] !== value)
      || !(record.base_version === null || typeof record.base_version === "string")
      || !isRecord(record.payload)) {
      return { ok: false, reason: "invalid_record", key }
    }
    return { ok: true, key, draft: { ...record, key, serialized } }
  } catch {
    return { ok: false, reason: "read_failed", key }
  }
}

export function writeLocalDraftBackup(storage, requestedScope, baseVersion, payload) {
  const scope = normalizeScope(requestedScope)
  if (!scope) return { ok: false, reason: "invalid_scope" }
  if (!storage) return { ok: false, reason: "storage_unavailable" }
  if (!(baseVersion === null || typeof baseVersion === "string") || !isRecord(payload)) return { ok: false, reason: "invalid_record" }
  const key = keyFor(scope)
  const record = {
    schema_version: SCHEMA_VERSION,
    scope,
    base_version: baseVersion,
    saved_at: new Date().toISOString(),
    payload: { ...payload },
  }
  const serialized = JSON.stringify(record)
  try {
    storage.setItem(key, serialized)
    return { ok: true, draft: { ...record, key, serialized } }
  } catch {
    return { ok: false, reason: "write_failed", key }
  }
}

export function clearLocalDraftBackup(storage, draft) {
  if (!storage || !draft?.key || typeof draft.serialized !== "string") return { ok: false, reason: "invalid_draft" }
  try {
    const current = storage.getItem(draft.key)
    if (current == null) return { ok: true, removed: false }
    if (current !== draft.serialized) return { ok: true, removed: false, changed: true }
    storage.removeItem(draft.key)
    return { ok: true, removed: true }
  } catch {
    return { ok: false, reason: "clear_failed" }
  }
}
