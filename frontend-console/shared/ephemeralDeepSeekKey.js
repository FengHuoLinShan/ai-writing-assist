export const EPHEMERAL_DEEPSEEK_KEY = "ephemeralDeepSeekKey"

export function readEphemeralDeepSeekKey(storage = globalThis.sessionStorage) {
  try { return storage?.getItem(EPHEMERAL_DEEPSEEK_KEY) || "" } catch { return "" }
}

export function writeEphemeralDeepSeekKey(value, storage = globalThis.sessionStorage) {
  const key = String(value || "").trim()
  try {
    if (key) storage?.setItem(EPHEMERAL_DEEPSEEK_KEY, key)
    else storage?.removeItem(EPHEMERAL_DEEPSEEK_KEY)
  } catch {}
  return key
}

export function clearEphemeralDeepSeekKey(storage = globalThis.sessionStorage) {
  try { storage?.removeItem(EPHEMERAL_DEEPSEEK_KEY) } catch {}
}
