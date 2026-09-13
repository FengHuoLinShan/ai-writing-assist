const STORAGE_KEY = "nc-entry-mode-after-auth"
const DEMO_COPY_INTENT_KEY = "nc-demo-copy-after-auth"
const MODES = new Set(["author", "rp"])

export function storeEntryMode(mode, storage = globalThis.sessionStorage) {
  try {
    if (MODES.has(mode)) storage?.setItem(STORAGE_KEY, mode)
    else storage?.removeItem(STORAGE_KEY)
  } catch {}
}

export function readEntryMode(storage = globalThis.sessionStorage) {
  let mode = null
  try { mode = storage?.getItem(STORAGE_KEY) || null } catch {}
  return MODES.has(mode) ? mode : null
}

export function consumeEntryMode(storage = globalThis.sessionStorage) {
  const mode = readEntryMode(storage)
  try { storage?.removeItem(STORAGE_KEY) } catch {}
  return mode
}

export function storeDemoCopyIntent(storage = globalThis.sessionStorage) {
  try { storage?.setItem(DEMO_COPY_INTENT_KEY, "1") } catch {}
}

export function hasDemoCopyIntent(storage = globalThis.sessionStorage) {
  try { return storage?.getItem(DEMO_COPY_INTENT_KEY) === "1" } catch { return false }
}

export function clearDemoCopyIntent(storage = globalThis.sessionStorage) {
  try { storage?.removeItem(DEMO_COPY_INTENT_KEY) } catch {}
}
