/**
 * 右侧 Scene 面板模块
 *
 * 负责 Scene 驾驶舱渲染、当前 Scene 检测、地图摘要加载、Cockpit 拖拽排序。
 */

import { renderSceneCockpitPanel, saveSceneCockpitOrder } from "../../views/sceneCockpitPanel.js"
import { findCurrentScene as locateCurrentScene } from "../../shared/sceneLocator.js"

export function createScenePanel({
  state,
  api,
  toast,
  esc,
  onOpenMap,
  onSwitchTab,
}) {
  const projectState = state
  const escapeHtml = esc

  let scenes = []
  let currentSceneId = null
  let currentChapter = null
  let cursorOffset = 0

  let sceneMapSummary = null
  let sceneMapSummaryError = null
  let sceneMapSummarySceneId = null
  let sceneMapSummaryPendingSceneId = null
  let sceneMapSummaryLoading = false

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function setScenes(value) {
    scenes = Array.isArray(value) ? value : []
  }

  function setCursorOffset(value) {
    cursorOffset = Number(value) || 0
  }

  function findCurrentScene() {
    return locateCurrentScene({
      scenes,
      chapterIndex: currentChapter,
      cursorOffset,
    })
  }

  async function update(nextSceneId, nextChapter) {
    const sceneChanged = nextSceneId !== currentSceneId
    currentChapter = nextChapter
    currentSceneId = nextSceneId
    if (sceneChanged) {
      sceneMapSummary = null
      sceneMapSummaryError = null
      sceneMapSummarySceneId = null
      sceneMapSummaryPendingSceneId = null
      sceneMapSummaryLoading = false
    }
    const currentScene = findCurrentScene()
    scheduleMapSummaryLoad(currentScene)
  }

  function render() {
    const currentScene = findCurrentScene()
    scheduleMapSummaryLoad(currentScene)
    return renderSceneCockpitPanel({
      projectId: currentProjectId(),
      scene: currentScene,
      mapSummaryHtml: renderMapSummary(currentScene),
      compact: typeof window !== "undefined" && window.innerHeight < 760,
    })
  }

  function renderMapSummary(currentScene) {
    const projectId = currentProjectId()
    const emptyText = currentScene ? "当前 Scene 暂无地图位置" : "当前章节未关联地图 Scene"
    if (sceneMapSummaryError) {
      return `
        <div class="writing-map-summary">
          <div class="writing-map-summary__title">地图摘要</div>
          <div class="writing-map-summary__warning">${escapeHtml(sceneMapSummaryError)}</div>
        </div>
      `
    }
    if (sceneMapSummaryLoading && !sceneMapSummary) {
      return `
        <div class="writing-map-summary">
          <div class="writing-map-summary__title">地图摘要</div>
          <div class="writing-map-summary__empty">地图摘要加载中...</div>
        </div>
      `
    }
    const summary = sceneMapSummary
    if (!summary) {
      return `
        <div class="writing-map-summary">
          <div class="writing-map-summary__title">地图摘要</div>
          <div class="writing-map-summary__empty">${escapeHtml(emptyText)}</div>
        </div>
      `
    }
    const location = summary.primary_location?.name || "未绑定地点"
    const row = (label, items) => {
      const names = (items || []).map((item) => item.name).filter(Boolean)
      if (!names.length) return ""
      return `
        <div class="writing-map-summary__row">
          <span class="writing-map-summary__label">${escapeHtml(label)}：</span>${escapeHtml(names.slice(0, 3).join("、"))}
        </div>
      `
    }
    const warnings = (summary.warnings || []).map((warning) => `
      <div class="writing-map-summary__warning">${escapeHtml(mapWarningMessage(warning))}</div>
    `).join("")
    const risks = (summary.risks || []).map((risk) => `
      <div class="writing-map-summary__warning">${escapeHtml(mapWarningMessage(risk))}</div>
    `).join("")
    return `
      <div class="writing-map-summary">
        <div class="writing-map-summary__title">地图摘要</div>
        <div class="writing-map-summary__row"><span class="writing-map-summary__label">地点：</span>${escapeHtml(location)}</div>
        ${row("人物", summary.characters)}
        ${row("事件", summary.events)}
        ${row("势力", summary.factions)}
        ${row("危机", summary.crises)}
        ${risks}
        ${warnings}
        <div class="writing-map-summary__actions">
          <button class="btn btn-sm" data-action="open-map">打开地图</button>
        </div>
      </div>
    `
  }

  function mapWarningMessage(warning) {
    if (typeof warning === "string") return warning
    if (!warning || typeof warning !== "object") return ""
    if (warning.message) return warning.message
    const messages = {
      scene_without_map_context: "当前 Scene 暂无地图上下文",
      scene_without_location: "当前 Scene 暂无主地点",
      character_cross_map: "人物上一场在其他地图，需确认移动合理性",
    }
    return messages[warning.code] || "地图空间连续性需要人工检查"
  }

  function scheduleMapSummaryLoad(currentScene) {
    const projectId = currentProjectId()
    if (!projectId || !currentScene?.id) return
    if (sceneMapSummarySceneId === currentScene.id) return
    if (sceneMapSummaryPendingSceneId === currentScene.id) return
    sceneMapSummaryPendingSceneId = currentScene.id
    sceneMapSummaryLoading = true
    setTimeout(async () => {
      await loadMapSummary(currentScene)
      if (currentSceneId !== currentScene.id) return
      const panelEl = document.getElementById("writing-panel-container")
      if (panelEl) {
        panelEl.innerHTML = render()
        bindEvents(panelEl)
      }
    }, 0)
  }

  async function loadMapSummary(scene) {
    const projectId = currentProjectId()
    if (!projectId || !scene?.id) {
      sceneMapSummary = null
      sceneMapSummaryError = null
      sceneMapSummarySceneId = null
      sceneMapSummaryPendingSceneId = null
      sceneMapSummaryLoading = false
      return null
    }
    sceneMapSummaryError = null
    sceneMapSummaryLoading = true
    const isStillCurrent = () => currentSceneId === scene.id
    const isActiveRequest = () => sceneMapSummaryPendingSceneId === scene.id ||
      sceneMapSummaryPendingSceneId === null
    try {
      const summary = await api.world.getMapSceneSummary(projectId, scene.id)
      if (!isStillCurrent() || !isActiveRequest()) return null
      sceneMapSummary = summary
      sceneMapSummaryError = null
      sceneMapSummarySceneId = scene.id
      return summary
    } catch {
      if (!isStillCurrent() || !isActiveRequest()) return null
      sceneMapSummary = null
      sceneMapSummaryError = "地图摘要暂不可用"
      sceneMapSummarySceneId = scene.id
      toast("地图摘要暂不可用", "warning")
      return null
    } finally {
      if (isActiveRequest()) {
        sceneMapSummaryLoading = false
        sceneMapSummaryPendingSceneId = null
      }
    }
  }

  function openMap() {
    const projectId = currentProjectId()
    if (!projectId) {
      toast("请先选择项目", "warning")
      return
    }
    const currentScene = findCurrentScene()
    const target = sceneMapSummary?.open_target || {}
    if (target.fallback_message) {
      toast(target.fallback_message, "warning")
    }
    if (typeof onOpenMap === "function") {
      onOpenMap({
        ...target,
        scene_id: target.scene_id || currentScene?.id,
      })
    }
  }

  function bindEvents(container) {
    container.querySelectorAll('[data-action="open-map"]').forEach((btn) => {
      btn.addEventListener("click", () => openMap())
    })
    container.querySelectorAll('[data-action="switch-cockpit-tab"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-tab")
        if (typeof onSwitchTab === "function") onSwitchTab(tab)
        switchTab(tab)
      })
    })
    container.querySelectorAll('[data-action="toggle-cockpit-module"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const module = btn.closest(".scene-cockpit-module")
        if (module) module.classList.toggle("is-collapsed")
      })
    })
    bindCockpitDrag(container)
  }

  function switchTab(tab) {
    if (!tab) return
    document.querySelectorAll(".cockpit-tab").forEach((item) => {
      item.classList.toggle("active", item.getAttribute("data-tab") === tab)
    })
    document.querySelectorAll(".cockpit-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.getAttribute("data-panel") !== tab)
    })
  }

  function bindCockpitDrag(container) {
    const panel = container.querySelector(".scene-cockpit")
    if (!panel || !currentProjectId()) return
    let draggingKey = null
    panel.querySelectorAll(".scene-cockpit-module").forEach((module) => {
      module.ondragstart = (event) => {
        draggingKey = module.getAttribute("data-cockpit-module")
        event.dataTransfer?.setData("text/plain", draggingKey || "")
      }
      module.ondragover = (event) => event.preventDefault()
      module.ondrop = (event) => {
        event.preventDefault()
        const targetKey = module.getAttribute("data-cockpit-module")
        if (!draggingKey || !targetKey || draggingKey === targetKey) return
        const modules = [...panel.querySelectorAll(".scene-cockpit-module")]
        const order = modules.map((el) => el.getAttribute("data-cockpit-module"))
        const from = order.indexOf(draggingKey)
        const to = order.indexOf(targetKey)
        if (from < 0 || to < 0) return
        order.splice(to, 0, order.splice(from, 1)[0])
        saveSceneCockpitOrder(currentProjectId(), order.filter(Boolean))
        const panelEl = document.getElementById("writing-panel-container")
        if (panelEl) panelEl.innerHTML = render()
        bindEvents(panelEl)
      }
    })
  }

  function getCurrentScene() {
    return findCurrentScene()
  }

  function getMapSummary() {
    return sceneMapSummary
  }

  function dispose() {
    sceneMapSummary = null
    sceneMapSummaryError = null
    sceneMapSummarySceneId = null
    sceneMapSummaryPendingSceneId = null
    sceneMapSummaryLoading = false
  }

  return {
    update,
    render,
    bindEvents,
    bindCockpitDrag,
    switchTab,
    openMap,
    dispose,
    setScenes,
    setCursorOffset,
    getCurrentScene,
    getMapSummary,
  }
}
