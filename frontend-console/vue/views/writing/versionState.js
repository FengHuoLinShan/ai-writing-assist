export function isVersionActive(version) {
  if (!version) return false
  return version.display_state
    ? version.display_state === "active"
    : !["candidate", "deprecated"].includes(version.status)
}
