/** Author-only AI map-atlas workspace. */
import { mountIsland } from "./mountIsland.js"
import { getAppState, getRouter } from "./bridge/index.js"
import MapWorkspaceView from "./views/map/MapWorkspaceView.vue"

export function createMapIsland() {
  return mountIsland({
    viewName: "map",
    component: MapWorkspaceView,
    load: async () => ({ projectId: getAppState()?.currentProjectId || null }),
  })
}

export function registerMapIsland() {
  const router = getRouter()
  if (!router) {
    console.error("mapIsland: router 尚未就绪，island 注册跳过")
    return null
  }
  const island = createMapIsland()
  router.registerView("map", island)
  return island
}

registerMapIsland()
