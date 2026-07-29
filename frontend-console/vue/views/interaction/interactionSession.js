export const RP_OPENING_DRAFT_KEY = "novel_rp_opening_draft"
const seeSeaGraceTimers = new Map()

function journeyKey(kind, journeyId) {
  return `novel_rp_${kind}:${journeyId}`
}

export function interactionOperationKey(prefix = "rp") {
  const id = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${id}`
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
  if (!journeyId) return ""
  try {
    return globalThis.localStorage?.getItem(journeyKey("draft", journeyId)) || ""
  } catch {
    return ""
  }
}

export function writeJourneyDraft(journeyId, value) {
  if (!journeyId) return
  try {
    const key = journeyKey("draft", journeyId)
    if (value) globalThis.localStorage?.setItem(key, value)
    else globalThis.localStorage?.removeItem(key)
  } catch {}
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
