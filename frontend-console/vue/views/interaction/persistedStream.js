/** Server offsets count Unicode code points (Python len), not UTF-16 units. */
export function mergePersistedChunk(text, offset, payload) {
  const end = payload?.offset
  if (!Number.isSafeInteger(offset) || offset < 0
    || !Number.isSafeInteger(end) || end < 0 || typeof payload?.text !== "string") {
    return { needsSnapshot: true }
  }
  const incoming = Array.from(payload.text)
  const start = end - incoming.length
  if (start < 0 || start > offset) return { needsSnapshot: true }
  if (start < offset) {
    const overlap = Math.min(offset, end) - start
    const current = Array.from(text).slice(start, start + overlap).join("")
    if (current !== incoming.slice(0, overlap).join("")) return { needsSnapshot: true }
  }
  if (end <= offset) return { text, offset, needsSnapshot: false }
  return {
    text: text + incoming.slice(offset - start).join(""),
    offset: end,
    needsSnapshot: false,
  }
}
