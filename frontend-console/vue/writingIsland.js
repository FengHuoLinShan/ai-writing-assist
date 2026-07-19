/** Writing Phase 4 Vue island. Router cutover is performed separately. */
import { mountIsland } from "./mountIsland.js"
import { getRouter } from "./bridge/index.js"
import WritingView from "./views/writing/WritingView.vue"
import { loadWritingProps } from "./views/writing/useWritingWorkspace.js"

export function createWritingIsland() {
  return mountIsland({
    viewName: "writing",
    component: WritingView,
    load: loadWritingProps,
  })
}

export function registerWritingIsland() {
  const router = getRouter()
  if (!router) {
    console.error("writingIsland: router 尚未就绪，island 注册跳过")
    return null
  }
  const island = createWritingIsland()
  router.registerView("writing", island)
  return island
}

registerWritingIsland()
