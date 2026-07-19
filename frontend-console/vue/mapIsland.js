/** Map Phase 5 Vue island. Vue owns the route workspace; mapView remains viewport-only. */
import { mountIsland } from "./mountIsland.js"
import { getRouter } from "./bridge/index.js"
import MapWorkspaceView from "./views/map/MapWorkspaceView.vue"
import { loadMapProps } from "./views/map/mapModel.js"

export function createMapIsland() {
  return mountIsland({ viewName: "map", component: MapWorkspaceView, load: loadMapProps })
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
