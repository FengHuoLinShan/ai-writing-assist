/**
 * Route-level Vue island loaders.
 *
 * This module deliberately registers import functions only.  Calling
 * registerViewLoaders() must never fetch a business island: the hash router
 * invokes the matching loader only after the authenticated workspace exists
 * and that normalized route is actually rendered.
 */
const viewLoaders = {
  home: () => import("./interactionIsland.js"),
  journeys: () => import("./interactionIsland.js"),
  interaction: () => import("./interactionIsland.js"),
  settings: () => import("./settingsIslands.js"),
  "project-settings": () => import("./settingsIslands.js"),
  project: () => import("./projectIsland.js"),
  today: () => import("./todayIsland.js"),
  rag: () => import("./ragIsland.js"),
  world: () => import("./worldIsland.js"),
  outline: () => import("./outlineIsland.js"),
  generate: () => import("./generateIsland.js"),
  writing: () => import("./writingIsland.js"),
  map: () => import("./mapIsland.js"),
}

/**
 * Register lazy view loaders with the existing hash-router seam.
 * The optional arguments make the registration behavior independently testable
 * without importing any island modules.
 */
export function registerViewLoaders(router = globalThis.router, loaders = viewLoaders) {
  if (typeof router?.registerViewLoader !== "function") return
  for (const [viewName, loader] of Object.entries(loaders)) {
    router.registerViewLoader(viewName, loader)
  }
}
