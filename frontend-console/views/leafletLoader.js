/**
 * Load the pinned Leaflet runtime only when the map viewport is entered.
 *
 * Both imports stay behind this function so Vite emits on-demand JS/CSS
 * chunks. The retryable wrapper clears only failed attempts; successful and
 * in-flight loads are shared for the lifetime of the page.
 */
async function importLeafletBundle() {
  // Leaflet's published UMD entry assigns globals in some DOM runtimes even
  // when it is imported as a module. Keep that compatibility side effect
  // inside this boundary: the map consumes only the returned module API and
  // unrelated pages retain the exact global state they had before loading it.
  const hadLeafletGlobal = Object.prototype.hasOwnProperty.call(globalThis, "L")
  const previousLeafletGlobal = globalThis.L
  const hadNamedGlobal = Object.prototype.hasOwnProperty.call(globalThis, "leaflet")
  const previousNamedGlobal = globalThis.leaflet

  try {
    const [leafletModule] = await Promise.all([
      import("leaflet"),
      import("leaflet/dist/leaflet.css"),
    ])
    return leafletModule.default || leafletModule
  } finally {
    if (hadLeafletGlobal) globalThis.L = previousLeafletGlobal
    else delete globalThis.L

    if (hadNamedGlobal) globalThis.leaflet = previousNamedGlobal
    else delete globalThis.leaflet
  }
}

export function createRetryableLeafletLoader(importer = importLeafletBundle) {
  let loadPromise = null
  return function loadLeaflet() {
    if (loadPromise) return loadPromise
    loadPromise = Promise.resolve()
      .then(() => importer())
      .then((leaflet) => {
        if (!leaflet || typeof leaflet.map !== "function" || !leaflet.CRS?.Simple) {
          throw new Error("Leaflet module does not expose the expected viewport API")
        }
        return leaflet
      })
      .catch((error) => {
        loadPromise = null
        throw error
      })
    return loadPromise
  }
}

export const loadLeafletForMapView = createRetryableLeafletLoader()
