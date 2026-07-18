/**
 * settings 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 *
 * 替代原 views/settings/ 两个 vanilla 视图；注册契约不变：
 * router.registerView(name, { onEnter, render, onRendered, onLeave })。
 * 数据在 island onEnter 阶段经 load() 预取，保证首屏即带数据。
 *
 * 同时接管原 projectSettingsView.js 注册的 #/llm 兼容别名（D15）。
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

function normalizeTemplates(templates) {
  return Array.isArray(templates) ? templates : templates?.items || []
}

async function loadGlobalSettings() {
  const api = getApi()
  try {
    const [llm, prefs, projects, templates] = await Promise.all([
      api.settings.listGlobalLLMDefaults(),
      api.settings.listGlobalAuthorPrefs(),
      api.settings.listProjectsUsingDefaults({ limit: 50 }),
      api.projects.listLlmProviderTemplates(),
    ])
    return {
      llmDefaults: llm,
      authorPrefs: prefs || {},
      projectsUsingDefaults: projects || { items: [], total: 0, truncated: false },
      templates: normalizeTemplates(templates),
    }
  } catch (err) {
    console.error("加载全局设置失败:", err)
    getToast()("加载全局设置失败", "error")
    return {
      llmDefaults: null,
      authorPrefs: {},
      projectsUsingDefaults: { items: [], total: 0, truncated: false },
      templates: [],
    }
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
    const [llm, prefs, templates] = await Promise.all([
      api.settings.getEffectiveLLMSettings(projectId),
      api.settings.getEffectiveAuthorPrefs(projectId),
      api.projects.listLlmProviderTemplates(),
    ])
    return {
      projectId,
      projectTitle,
      effectiveLLM: llm,
      effectivePrefs: prefs,
      templates: normalizeTemplates(templates),
    }
  } catch (err) {
    console.error("加载项目设置失败:", err)
    getToast()("加载项目设置失败", "error")
    return {
      projectId,
      projectTitle,
      effectiveLLM: null,
      effectivePrefs: null,
      templates: [],
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

  // #/llm 向后兼容别名（D15）：有项目跳项目设置，否则跳全局设置
  router.registerView("llm", {
    async onEnter() {
      if (getAppState()?.currentProjectId) {
        getRouter().navigate("project-settings")
      } else {
        getRouter().navigate("settings")
        getToast()("请先选择项目", "warning")
      }
    },
    async render() {
      return ""
    },
  })
}

registerSettingsIslands()
