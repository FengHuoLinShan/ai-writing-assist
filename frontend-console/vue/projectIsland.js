/**
 * project 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 * 替代原 views/projectView.js；load 对应 vanilla onEnter（拉列表 + currentProject 校验）。
 */
import { mountIsland } from "./mountIsland.js"
import ProjectView from "./views/project/ProjectView.vue"
import { getRouter } from "./bridge/index.js"
import { loadProjectsIntoState } from "./views/project/logic/projectState.js"

async function loadProjects() {
  const { error } = await loadProjectsIntoState()
  return { loadError: error }
}

export function registerProjectIsland() {
  const router = getRouter()
  if (!router) {
    console.error("projectIsland: router 尚未就绪，island 注册跳过")
    return
  }
  router.registerView("project", mountIsland({
    viewName: "project",
    component: ProjectView,
    load: loadProjects,
  }))
}

registerProjectIsland()
