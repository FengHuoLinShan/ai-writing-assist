let ephemeralDeepSeekKey = ""

export function readEphemeralDeepSeekKey() {
  return ephemeralDeepSeekKey
}

export function writeEphemeralDeepSeekKey(value) {
  ephemeralDeepSeekKey = String(value || "").trim()
  return ephemeralDeepSeekKey
}

export function clearEphemeralDeepSeekKey() {
  ephemeralDeepSeekKey = ""
}
