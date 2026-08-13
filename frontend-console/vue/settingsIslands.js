/**
 * settings 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 *
 * 替代原 views/settings/ 两个 vanilla 视图；注册契约不变：
 * router.registerView(name, { onEnter, render, onRendered, onLeave })。
 * 数据在 island onEnter 阶段经 load() 预取，保证首屏即带数据。
 *
 */
import { mountIsland } from "./mountIsland.js"
import GlobalSettingsView from "./views/settings/GlobalSettingsView.vue"
import ProjectSettingsView from "./views/settings/ProjectSettingsView.vue"
import {
  getApi,
  getAppState,
  getRouter,
  getToast,
  tryMigrateLocalAuthorPreferences,
} from "./bridge/index.js"

async function loadGlobalSettings() {
  const api = getApi()
  const [connections, balances, prefs] = await Promise.allSettled([
    api.settings.listLLMConnections(),
    api.settings.listLLMBalances(),
    api.settings.listGlobalAuthorPrefs(),
  ])
  if (connections.status === "rejected") {
    console.error("加载模型连接失败:", connections.reason)
    getToast()("加载全局设置失败", "error")
  }
  return {
    llmConnections: connections.status === "fulfilled"
      ? connections.value
      : null,
    llmBalances: balances.status === "fulfilled"
      ? balances.value
      : { items: [] },
    authorPrefs: prefs.status === "fulfilled" ? prefs.value || {} : {},
  }
}

async function loadProjectSettings() {
  const state = getAppState()
  const projectId = state?.currentProjectId || null
  if (!projectId) return { projectId: null }
  await tryMigrateLocalAuthorPreferences(projectId)
  const api = getApi()
  const projectTitle = state?.currentProject?.title || projectId
  try {
    const [llm, prefs] = await Promise.all([
      api.settings.getEffectiveLLMSettings(projectId),
      api.settings.getEffectiveAuthorPrefs(projectId),
    ])
    return {
      projectId,
      projectTitle,
      effectiveLLM: llm,
      effectivePrefs: prefs,
    }
  } catch (err) {
    console.error("加载项目设置失败:", err)
    getToast()("加载项目设置失败", "error")
    return {
      projectId,
      projectTitle,
      effectiveLLM: null,
      effectivePrefs: null,
    }
  }
}

export function registerSettingsIslands() {
  const router = getRouter()
  if (!router) {
    console.error("settingsIslands: router 尚未就绪，island 注册跳过")
    return
  }

  router.registerView("settings", mountIsland({
    viewName: "settings",
    component: GlobalSettingsView,
    load: loadGlobalSettings,
  }))

  router.registerView("project-settings", mountIsland({
    viewName: "project-settings",
    component: ProjectSettingsView,
    load: loadProjectSettings,
  }))
}

registerSettingsIslands()
