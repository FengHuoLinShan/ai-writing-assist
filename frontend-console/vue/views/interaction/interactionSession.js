export const RP_OPENING_DRAFT_KEY = "novel_rp_opening_draft"
const seeSeaGraceTimers = new Map()
const openingKeys = new Map()

export function openingOperationKey(openingId) {
  const storageKey = `novel_rp_opening_operation:${openingId}`
  let key = openingKeys.get(openingId)
  try { key ||= globalThis.sessionStorage?.getItem(storageKey) } catch {}
  key ||= interactionOperationKey('opening')
  openingKeys.set(openingId, key)
  try { globalThis.sessionStorage?.setItem(storageKey, key) } catch {}
  return key
}

export function clearOpeningOperation(openingId) {
  openingKeys.delete(openingId)
  try { globalThis.sessionStorage?.removeItem(`novel_rp_opening_operation:${openingId}`) } catch {}
}

function journeyKey(kind, journeyId) {
  return `novel_rp_${kind}:${journeyId}`
}

export function interactionOperationKey(prefix = "rp") {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `${prefix}-${globalThis.crypto.randomUUID()}`
  }
  if (typeof globalThis.crypto?.getRandomValues !== "function") {
    throw new Error("当前浏览器无法安全生成操作标识，请更换浏览器后重试")
  }
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  const token = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")
  return `${prefix}-${token}`
}

export function readOpeningDraft() {
  try { return globalThis.localStorage?.getItem(RP_OPENING_DRAFT_KEY) || "" }
  catch { return "" }
}

export function writeOpeningDraft(value) {
  try {
    if (value) globalThis.localStorage?.setItem(RP_OPENING_DRAFT_KEY, value)
    else globalThis.localStorage?.removeItem(RP_OPENING_DRAFT_KEY)
  } catch {}
}

export function readJourneyDraft(journeyId) {
  return readJourneyInput(journeyId).content
}

export function readJourneyInput(journeyId) {
  const empty = { content: "" }
  if (!journeyId) return empty
  try {
    const raw = globalThis.localStorage?.getItem(journeyKey("draft", journeyId)) || ""
    if (raw.startsWith('{"format":"rp-input-v2"')) {
      const value = JSON.parse(raw)
      return typeof value.content === "string" ? value : empty
    }
    return { content: raw }
  } catch {
    return empty
  }
}

export function writeJourneyDraft(journeyId, value, input = null) {
  if (!journeyId) return false
  try {
    if (!globalThis.localStorage) return false
    const key = journeyKey("draft", journeyId)
    const stored = input ? JSON.stringify({ format: "rp-input-v2", ...input, content: value }) : value
    if (value) globalThis.localStorage.setItem(key, stored)
    else globalThis.localStorage.removeItem(key)
    return true
  } catch { return false }
}

export function readJourneyScroll(journeyId) {
  if (!journeyId) return null
  try {
    const value = JSON.parse(
      globalThis.sessionStorage?.getItem(journeyKey("scroll", journeyId)) || "null",
    )
    if (!value || typeof value !== "object") return null
    return {
      anchorId: typeof value.anchorId === "string" ? value.anchorId : null,
      scrollTop: Number.isFinite(value.scrollTop) ? value.scrollTop : 0,
      atBottom: value.atBottom === true,
    }
  } catch {
    return null
  }
}

export function writeJourneyScroll(journeyId, value) {
  if (!journeyId || !value) return
  try {
    globalThis.sessionStorage?.setItem(
      journeyKey("scroll", journeyId),
      JSON.stringify(value),
    )
  } catch {}
}

export function clearJourneyScroll(journeyId) {
  if (!journeyId) return
  try {
    globalThis.sessionStorage?.removeItem(journeyKey("scroll", journeyId))
  } catch {}
}

function overviewDraftKey(journeyId, branchId) {
  return journeyKey("overview_draft", `${journeyId}:${branchId || "root"}`)
}

export function readOverviewDraft(journeyId, branchId) {
  if (!journeyId) return null
  try {
    return JSON.parse(
      globalThis.localStorage?.getItem(overviewDraftKey(journeyId, branchId))
        || "null",
    )
  } catch {
    return null
  }
}

export function writeOverviewDraft(journeyId, branchId, value) {
  if (!journeyId) return
  try {
    const key = overviewDraftKey(journeyId, branchId)
    if (value) globalThis.localStorage?.setItem(key, JSON.stringify(value))
    else globalThis.localStorage?.removeItem(key)
  } catch {}
}

export function cancelSeeSeaGrace(journeyId) {
  const timer = seeSeaGraceTimers.get(journeyId)
  if (timer != null) clearTimeout(timer)
  seeSeaGraceTimers.delete(journeyId)
}

export function scheduleSeeSeaGrace(journeyId, disable, delayMs = 60_000) {
  if (!journeyId || typeof disable !== "function") return
  cancelSeeSeaGrace(journeyId)
  const timer = setTimeout(() => {
    seeSeaGraceTimers.delete(journeyId)
    void Promise.resolve(disable()).catch(() => {})
  }, delayMs)
  seeSeaGraceTimers.set(journeyId, timer)
}
