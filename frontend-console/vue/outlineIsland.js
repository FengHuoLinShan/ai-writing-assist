/**
 * outline 视图 Vue island 注册入口 — 由 app.js（ESM）import。
 * 替代原 outline、story-outline 与 scene vanilla 主链。
 *
 * 设计依据 ADR-0009 附录 A（docs/adr/0009-appendix-a-keep-alive-policy.md）：
 * - outline 已移出 router keep-alive（多 subView 与 mountIsland 单 app 引用冲突），
 *   离开即全量卸载、返回即全量重进；三条 AI 轮询线在 onLeave 停止、load 时 recover。
 * - subView=scenes 与其他子视图共用同一个 OutlineView 根 app；主 DOM 由 Vue
 *   模板拥有，复杂融合/拆分流程只在外壳 modal controller 中使用转义后的 HTML。
 * - subnav 滚动位置按 vanilla 语义存/取 state.viewStates.outline.scrollTop。
 */
import { mountIsland } from "./mountIsland.js"
import OutlineView from "./views/outline/OutlineView.vue"
import {
  outlineAnalysisManager,
  outlineGenerateManager,
  plotAutoExtractManager,
} from "./views/outline/ai/outlineWorkflowManagers.js"
import { loadStoryOutlineProps, storyOutlineTaskManager } from "./views/outline/story/storyOutlineData.js"
import { loadStructureProps, structureFiltersFromQuery } from "./views/outline/logic/outlineStructure.js"
import { loadSceneWorkbenchProps } from "./views/scene/sceneModel.js"
import { sceneAutoExtractManager } from "./views/scene/sceneAutoExtractManager.js"
import { sceneRuntimeManager } from "./views/scene/sceneRuntimeManager.js"
import { scopeBulkSelectionsToProject } from "./views/outline/logic/outlineBulkSelection.js"
import { getAppState, getRouter } from "./bridge/index.js"

function stopAiManagers() {
  outlineGenerateManager.stop()
  outlineAnalysisManager.stop()
  plotAutoExtractManager.stop()
}

function recoverAiManagers(projectId) {
  outlineGenerateManager.recover(projectId)
  outlineAnalysisManager.recover(projectId)
  plotAutoExtractManager.recover(projectId)
}

/** outline island 数据预取：四个子标签都返回 Vue 根组件 props。 */
async function loadOutline() {
  const appState = getAppState()
  const router = getRouter()
  const projectId = appState?.currentProjectId || null
  const subView = appState?.currentSubView || "story-outline"
  const query = new URLSearchParams(router?.getCurrentQuery?.()?.toString() || "")
  scopeBulkSelectionsToProject(projectId)

  if (subView === "scenes") {
    outlineGenerateManager.recover(projectId)
    if (query.get("review") === "ai") {
      return { projectId, subView, outlineGenerateReview: true }
    }
    sceneAutoExtractManager.recover(projectId)
    sceneRuntimeManager.recover(projectId, query.get("scene_id") || null)
    try {
      const sceneProps = await loadSceneWorkbenchProps(projectId)
      return { projectId, subView, ...sceneProps }
    } catch (err) {
      return {
        projectId,
        subView,
        workbench: null,
        fusionSuggestions: [],
        sceneLoadError: err.message || "场景工作台加载失败",
      }
    }
  }

  recoverAiManagers(projectId)

  if (subView === "story-outline") {
    const storyProps = await loadStoryOutlineProps(projectId)
    return { projectId, subView, editorMode: query.get("edit") === "1", ...storyProps }
  }

  // threads / arcs
  const filters = structureFiltersFromQuery(subView, query)
  const structureProps = await loadStructureProps({ projectId, subView, filters })
  return {
    projectId,
    subView,
    outlineGenerateReview: query.get("review") === "ai" && (subView === "threads" || subView === "arcs"),
    structureFilters: filters,
    informationFocus: query.get("information") || null,
    ...structureProps,
  }
}

function saveSubnavScroll() {
  const container = document.querySelector("#workspace-content .subnav")
  if (!container) return
  const appState = getAppState()
  if (!appState) return
  appState.viewStates = appState.viewStates || {}
  appState.viewStates.outline = { scrollTop: container.scrollTop }
}

function restoreSubnavScroll() {
  const saved = getAppState()?.viewStates?.outline
  if (saved?.scrollTop == null) return
  const container = document.querySelector("#workspace-content .subnav")
  if (container) container.scrollTop = saved.scrollTop
}

export function registerOutlineIsland() {
  const router = getRouter()
  if (!router) {
    console.error("outlineIsland: router 尚未就绪，island 注册跳过")
    return
  }
  const island = mountIsland({
    viewName: "outline",
    component: OutlineView,
    load: loadOutline,
  })
  const baseOnRendered = island.onRendered
  const baseOnLeave = island.onLeave

  island.onRendered = async () => {
    await baseOnRendered()
    restoreSubnavScroll()
  }

  island.onLeave = () => {
    saveSubnavScroll()
    stopAiManagers()
    sceneAutoExtractManager.stop()
    sceneRuntimeManager.stop()
    storyOutlineTaskManager.stop()
    baseOnLeave()
  }

  router.registerView("outline", island)
}

registerOutlineIsland()
