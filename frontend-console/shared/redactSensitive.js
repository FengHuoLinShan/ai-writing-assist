export function isSensitiveKey(key) {
  const normalized = String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "")
  return normalized === "auth"
    || normalized.includes("authorization")
    || normalized.includes("apikey")
    || normalized.endsWith("token")
    || normalized.includes("secret")
    || normalized.includes("password")
    || normalized.includes("passwd")
    || normalized.includes("credential")
    || normalized.includes("cookie")
}

export function redactSensitiveText(value) {
  return String(value)
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "[REDACTED]")
    .replace(
      /((?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|credential)\s*[:=]\s*["']?)([^"',;\s}&]+)/gi,
      "$1[REDACTED]",
    )
}

function hasSensitiveLocation(value) {
  return Array.isArray(value?.loc)
    && value.loc.some((segment) => isSensitiveKey(segment))
}

export function redactSensitiveValue(value, seen = new WeakSet()) {
  if (typeof value === "string") return redactSensitiveText(value)
  if (value == null || typeof value !== "object") return value
  if (seen.has(value)) return "[Circular]"
  seen.add(value)
  if (Array.isArray(value)) {
    return value.map((item) => redactSensitiveValue(item, seen))
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key,
    isSensitiveKey(key) || (key === "input" && hasSensitiveLocation(value))
      ? "[REDACTED]"
      : redactSensitiveValue(item, seen),
  ]))
}
