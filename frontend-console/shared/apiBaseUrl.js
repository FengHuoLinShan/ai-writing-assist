export function resolveApiBaseUrl(apiHost = "") {
  const normalizedHost = typeof apiHost === "string"
    ? apiHost.trim().replace(/\/+$/, "")
    : ""
  if (!normalizedHost) return "/api"
  return normalizedHost.endsWith("/api") ? normalizedHost : `${normalizedHost}/api`
}
