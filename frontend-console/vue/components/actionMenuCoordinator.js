let activeCloser = null

export function claimActionMenu(closer) {
  if (activeCloser && activeCloser !== closer) activeCloser()
  activeCloser = closer
}

export function releaseActionMenu(closer) {
  if (activeCloser === closer) activeCloser = null
}

export function hasAnotherActionMenu(closer) {
  return activeCloser !== null && activeCloser !== closer
}
