/**
 * 右侧 Scene 面板模块
 *
 * 负责 Scene 驾驶舱渲染、当前 Scene 检测、地图摘要加载、Cockpit 拖拽排序。
 */

import { renderSceneCockpitPanel, saveSceneCockpitOrder } from "../../views/sceneCockpitPanel.js"
import { findCurrentScene as locateCurrentScene } from "../../shared/sceneLocator.js"
import { buildSceneAlerts } from "./sceneAlerts.js"

const COCKPIT_TABS = ["alerts", "people", "place", "lore", "map"]

export function createScenePanel({
  state,
  api,
  toast,
  esc,
  onOpenMap,
  onSwitchTab,
  onRunConflictCheck,
  onOpenConflictCheck,
}) {
  const projectState = state
  const escapeHtml = esc

  let scenes = []
  let currentSceneId = null
  let currentChapter = null
  let cursorOffset = 0
  let activeTab = "lore"
  let boundContainer = null
  let disposed = false

  let sceneMapSummary = null
  let sceneMapSummaryError = null
  let sceneMapSummarySceneId = null
  let sceneMapSummaryProjectId = null
  let sceneMapSummaryPendingSceneId = null
  let sceneMapSummaryPendingProjectId = null
  let sceneMapSummaryLoading = false
  let sceneMapRequestGeneration = 0
  let sceneReferencePeople = []
  let sceneReferenceLocation = null

  let writingContext = {
    content: "",
    draftId: null,
    versionNumber: null,
    isDirty: false,
  }
  let latestConflictCheck = null
  let sceneAlertError = null
  let sceneAlertLoading = false
  let sceneAlertLoadedScopeKey = null
  let sceneAlertPendingScopeKey = null
  let sceneAlertRequestGeneration = 0
  let sceneAlertLoadTimer = null
  let panelRenderTimer = null

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function setScenes(value) {
    if (disposed) return
    scenes = Array.isArray(value) ? value : []
  }

  function setCursorOffset(value) {
    if (disposed) return
    cursorOffset = Number(value) || 0
  }

  function setWritingContext(value = {}) {
    if (disposed) return
    const next = {
      content: String(value.content || ""),
      draftId: value.draftId || null,
      versionNumber: value.versionNumber ?? null,
      isDirty: value.isDirty === true,
    }
    const identityChanged = (
      next.draftId !== writingContext.draftId ||
      next.versionNumber !== writingContext.versionNumber
    )
    const displayChanged = (
      identityChanged ||
      next.content !== writingContext.content ||
      next.isDirty !== writingContext.isDirty
    )
    writingContext = next
    if (identityChanged) {
      invalidateAlertRequest()
      scheduleAlertLoad(findCurrentScene())
    }
    if (displayChanged) schedulePanelRender(160)
  }

  function findCurrentScene() {
    return locateCurrentScene({
      scenes,
      chapterIndex: currentChapter,
      cursorOffset,
    })
  }

  async function update(nextSceneId, nextChapter) {
    if (disposed) return
    const previousSceneId = currentSceneId
    const previousChapter = currentChapter
    currentChapter = nextChapter
    currentSceneId = nextSceneId
    const currentScene = findCurrentScene()
    currentSceneId = currentScene?.id || nextSceneId || null
    const sceneChanged = currentSceneId !== previousSceneId
    const alertScopeChanged = sceneChanged || currentChapter !== previousChapter
    if (sceneChanged) {
      sceneMapSummary = null
      sceneMapSummaryError = null
      sceneMapSummarySceneId = null
      sceneMapSummaryProjectId = null
      sceneMapSummaryPendingSceneId = null
      sceneMapSummaryPendingProjectId = null
      sceneMapSummaryLoading = false
      sceneReferencePeople = []
      sceneReferenceLocation = null
    }
    if (alertScopeChanged) {
      latestConflictCheck = null
      sceneAlertError = null
      invalidateAlertRequest()
    }
    scheduleMapSummaryLoad(currentScene)
    scheduleAlertLoad(currentScene)
  }

  function render() {
    if (currentChapter == null) {
      return `
        <div class="empty-state writing-scene-panel-empty">
          <strong>写作参考</strong>
          <p>请先从左侧选择章节，再查看对应 Scene、人物和地图参考。</p>
        </div>
      `
    }
    const currentScene = findCurrentScene()
    scheduleMapSummaryLoad(currentScene)
    scheduleAlertLoad(currentScene)
    const visibleCheck = visibleLatestConflictCheck(currentScene)
    const visibleMapSummary = currentMapSummary(currentScene)
    const visibleMapError = currentMapError(currentScene)
    const visibleAlertError = currentAlertError(currentScene)
    const visibleAlertLoading = currentAlertLoading(currentScene)
    const alerts = buildSceneAlerts({
      scene: currentScene,
      chapterIndex: currentChapter,
      content: writingContext.content,
      mapSummary: visibleMapSummary,
      mapError: visibleMapError,
      latestCheck: visibleCheck,
      checkError: visibleAlertError,
      checkLoading: visibleAlertLoading,
      draftId: writingContext.draftId,
      versionNumber: writingContext.versionNumber,
      isDirty: writingContext.isDirty,
    })
    return renderSceneCockpitPanel({
      projectId: currentProjectId(),
      scene: currentScene,
      people: visibleMapSummary !== undefined ? sceneReferencePeople : [],
      location: visibleMapSummary !== undefined ? sceneReferenceLocation : null,
      mapSummaryHtml: renderMapSummary(currentScene),
      compact: typeof window !== "undefined" && window.innerHeight < 760,
      activeTab,
      alerts,
      alertLoading: visibleAlertLoading,
      alertError: visibleAlertError,
      latestCheck: visibleCheck,
    })
  }

  function renderMapSummary(currentScene) {
    const projectId = currentProjectId()
    const emptyText = currentScene ? "当前 Scene 暂无地图位置" : "当前章节未关联地图 Scene"
    const error = currentMapError(currentScene)
    if (error) {
      return `
        <div class="writing-map-summary">
          <div class="writing-map-summary__title">地图摘要</div>
          <div class="writing-map-summary__warning">${escapeHtml(error)}</div>
        </div>
      `
    }
    const summary = currentMapSummary(currentScene)
    const loadingCurrentScope = (
      sceneMapSummaryLoading &&
      sceneMapSummaryPendingSceneId === currentScene?.id &&
      sceneMapSummaryPendingProjectId === projectId
    )
    if (loadingCurrentScope && !summary) {
      return `
        <div class="writing-map-summary">
          <div class="writing-map-summary__title">地图摘要</div>
          <div class="writing-map-summary__empty">地图摘要加载中...</div>
        </div>
      `
    }
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
    if (sceneMapSummarySceneId === currentScene.id && sceneMapSummaryProjectId === projectId) return
    if (
      sceneMapSummaryPendingSceneId === currentScene.id &&
      sceneMapSummaryPendingProjectId === projectId
    ) return
    sceneMapSummaryPendingSceneId = currentScene.id
    sceneMapSummaryPendingProjectId = projectId
    sceneMapSummaryLoading = true
    const requestGeneration = ++sceneMapRequestGeneration
    setTimeout(async () => {
      if (disposed || requestGeneration !== sceneMapRequestGeneration) return
      await loadMapSummary(currentScene, projectId, requestGeneration)
      if (
        disposed ||
        requestGeneration !== sceneMapRequestGeneration ||
        currentSceneId !== currentScene.id ||
        currentProjectId() !== projectId
      ) return
      renderPanelNow()
    }, 0)
  }

  async function loadMapSummary(scene, requestedProjectId, requestGeneration) {
    const projectId = requestedProjectId || currentProjectId()
    if (!projectId || !scene?.id) {
      sceneMapSummary = null
      sceneMapSummaryError = null
      sceneMapSummarySceneId = null
      sceneMapSummaryProjectId = null
      sceneMapSummaryPendingSceneId = null
      sceneMapSummaryPendingProjectId = null
      sceneMapSummaryLoading = false
      return null
    }
    sceneMapSummaryError = null
    sceneMapSummaryLoading = true
    const isStillCurrent = () => (
      !disposed &&
      requestGeneration === sceneMapRequestGeneration &&
      currentSceneId === scene.id &&
      currentProjectId() === projectId
    )
    const isActiveRequest = () => requestGeneration === sceneMapRequestGeneration
    try {
      const query = (entityType) => api.world.listEntities({
        novel_id: projectId,
        scene_id: scene.id,
        entity_type: entityType,
        display_state: "active",
        skip: 0,
        limit: 12,
      })
      const [summaryResult, peopleResult, locationsResult] = await Promise.allSettled([
        api.world.getMapSceneSummary(projectId, scene.id),
        query("character"),
        query("location"),
      ])
      if (!isStillCurrent() || !isActiveRequest()) return null

      const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null
      const sourcedPeople = peopleResult.status === "fulfilled" ? listItems(peopleResult.value) : []
      const sourcedLocations = locationsResult.status === "fulfilled" ? listItems(locationsResult.value) : []
      sceneMapSummary = summary
      sceneMapSummaryError = summaryResult.status === "rejected" ? "地图摘要暂不可用" : null
      sceneReferencePeople = dedupeReferences([
        ...(Array.isArray(scene.scene_characters) ? scene.scene_characters : []),
        ...(Array.isArray(summary?.characters) ? summary.characters : []),
        ...sourcedPeople,
      ])
      sceneReferenceLocation = scene.primary_location ||
        scene.location ||
        summary?.primary_location ||
        sourcedLocations[0] ||
        null
      sceneMapSummarySceneId = scene.id
      sceneMapSummaryProjectId = projectId
      if (summaryResult.status === "rejected") {
        toast("地图摘要暂不可用", "warning")
      }
      return summary
    } catch {
      if (!isStillCurrent() || !isActiveRequest()) return null
      sceneMapSummary = null
      sceneMapSummaryError = "地图摘要暂不可用"
      sceneMapSummarySceneId = scene.id
      sceneMapSummaryProjectId = projectId
      toast("地图摘要暂不可用", "warning")
      return null
    } finally {
      if (isActiveRequest()) {
        sceneMapSummaryLoading = false
        sceneMapSummaryPendingSceneId = null
        sceneMapSummaryPendingProjectId = null
      }
    }
  }

  function alertScope(currentScene = findCurrentScene()) {
    const projectId = currentProjectId()
    if (!projectId || currentChapter == null || !currentScene?.id) return null
    const draftPart = writingContext.draftId || "no-draft"
    const versionPart = writingContext.versionNumber ?? "no-version"
    return {
      projectId,
      chapterIndex: currentChapter,
      sceneId: currentScene.id,
      key: [projectId, currentChapter, currentScene.id, draftPart, versionPart].join(":"),
    }
  }

  function scheduleAlertLoad(currentScene) {
    if (disposed) return
    const scope = alertScope(currentScene)
    if (!scope) return
    if (sceneAlertLoadedScopeKey === scope.key || sceneAlertPendingScopeKey === scope.key) return
    if (sceneAlertLoadTimer) clearTimeout(sceneAlertLoadTimer)
    sceneAlertPendingScopeKey = scope.key
    sceneAlertLoading = true
    sceneAlertLoadTimer = setTimeout(() => {
      sceneAlertLoadTimer = null
      loadAlertScope(scope)
    }, 0)
  }

  async function refreshAlerts() {
    if (disposed) return null
    const scope = alertScope()
    if (!scope) {
      latestConflictCheck = null
      sceneAlertError = null
      sceneAlertLoading = false
      invalidateAlertRequest()
      schedulePanelRender()
      return null
    }
    if (sceneAlertLoadTimer) {
      clearTimeout(sceneAlertLoadTimer)
      sceneAlertLoadTimer = null
    }
    return loadAlertScope(scope)
  }

  async function loadAlertScope(scope) {
    if (disposed) return null
    const requestGeneration = ++sceneAlertRequestGeneration
    sceneAlertPendingScopeKey = scope.key
    sceneAlertLoading = true
    sceneAlertError = null
    try {
      const result = await api.writing.listConflictChecks({
        novel_id: scope.projectId,
        chapter_index: scope.chapterIndex,
        scene_id: scope.sceneId,
        limit: 1,
      })
      if (!isCurrentAlertRequest(scope, requestGeneration)) return null
      const candidate = Array.isArray(result?.items) ? (result.items[0] || null) : null
      if (candidate && !conflictCheckMatchesScope(candidate, scope)) {
        latestConflictCheck = null
        sceneAlertError = "最近校验身份不匹配，已安全忽略"
      } else {
        latestConflictCheck = candidate
      }
      sceneAlertLoadedScopeKey = scope.key
      return latestConflictCheck
    } catch {
      if (!isCurrentAlertRequest(scope, requestGeneration)) return null
      latestConflictCheck = null
      sceneAlertError = "最近校验暂不可用"
      sceneAlertLoadedScopeKey = scope.key
      return null
    } finally {
      if (isCurrentAlertRequest(scope, requestGeneration)) {
        sceneAlertLoading = false
        sceneAlertPendingScopeKey = null
        schedulePanelRender()
      }
    }
  }

  function isCurrentAlertRequest(scope, requestGeneration) {
    return (
      !disposed &&
      requestGeneration === sceneAlertRequestGeneration &&
      alertScope()?.key === scope.key
    )
  }

  function invalidateAlertRequest() {
    sceneAlertRequestGeneration += 1
    sceneAlertLoadedScopeKey = null
    sceneAlertPendingScopeKey = null
    sceneAlertLoading = false
    if (sceneAlertLoadTimer) {
      clearTimeout(sceneAlertLoadTimer)
      sceneAlertLoadTimer = null
    }
  }

  function schedulePanelRender(delay = 0) {
    if (disposed) return
    if (panelRenderTimer) clearTimeout(panelRenderTimer)
    panelRenderTimer = setTimeout(() => {
      panelRenderTimer = null
      renderPanelNow()
    }, delay)
  }

  function renderPanelNow() {
    if (disposed) return
    const panelEl = document.getElementById("writing-panel-container")
    if (!panelEl) return
    panelEl.innerHTML = render()
    bindEvents(panelEl)
  }

  function openMap() {
    if (disposed) return
    const projectId = currentProjectId()
    if (!projectId) {
      toast("请先选择项目", "warning")
      return
    }
    const currentScene = findCurrentScene()
    const target = currentMapSummary(currentScene)?.open_target || {}
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
    if (disposed) return
    boundContainer = container
    container.querySelectorAll('[data-action="open-map"]').forEach((btn) => {
      btn.onclick = () => openMap()
    })
    container.querySelectorAll('[data-action="switch-cockpit-tab"]').forEach((btn) => {
      btn.onclick = () => {
        const tab = btn.getAttribute("data-tab")
        if (typeof onSwitchTab === "function") onSwitchTab(tab)
        switchTab(tab)
      }
    })
    container.querySelectorAll('[data-action="run-cockpit-conflict-check"]').forEach((btn) => {
      btn.onclick = () => onRunConflictCheck?.()
    })
    container.querySelectorAll('[data-action="open-cockpit-conflict-check"]').forEach((btn) => {
      btn.onclick = () => {
        const check = visibleLatestConflictCheck()
        if (check) onOpenConflictCheck?.(check)
      }
    })
    container.querySelectorAll('[data-action="toggle-cockpit-module"]').forEach((btn) => {
      btn.onclick = () => {
        const module = btn.closest(".scene-cockpit-module")
        if (module) module.classList.toggle("is-collapsed")
      }
    })
    bindCockpitDrag(container)
  }

  function switchTab(tab) {
    if (!COCKPIT_TABS.includes(tab)) return
    activeTab = tab
    const root = boundContainer?.querySelector?.(".scene-cockpit") || null
    const queryRoot = root || document
    queryRoot.querySelectorAll(".cockpit-tab").forEach((item) => {
      item.classList.toggle("active", item.getAttribute("data-tab") === tab)
    })
    queryRoot.querySelectorAll(".cockpit-panel").forEach((panel) => {
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
    return currentMapSummary() ?? null
  }

  function getAlerts() {
    const currentScene = findCurrentScene()
    return buildSceneAlerts({
      scene: currentScene,
      chapterIndex: currentChapter,
      content: writingContext.content,
      mapSummary: currentMapSummary(currentScene),
      mapError: currentMapError(currentScene),
      latestCheck: visibleLatestConflictCheck(currentScene),
      checkError: currentAlertError(currentScene),
      checkLoading: currentAlertLoading(currentScene),
      draftId: writingContext.draftId,
      versionNumber: writingContext.versionNumber,
      isDirty: writingContext.isDirty,
    })
  }

  function getLatestConflictCheck() {
    return visibleLatestConflictCheck()
  }

  function visibleLatestConflictCheck(currentScene = findCurrentScene()) {
    const scope = alertScope(currentScene)
    return scope && sceneAlertLoadedScopeKey === scope.key ? latestConflictCheck : null
  }

  function currentAlertError(currentScene = findCurrentScene()) {
    const scope = alertScope(currentScene)
    return scope && sceneAlertLoadedScopeKey === scope.key ? sceneAlertError : null
  }

  function currentAlertLoading(currentScene = findCurrentScene()) {
    const scope = alertScope(currentScene)
    return Boolean(
      scope &&
      sceneAlertLoading &&
      sceneAlertPendingScopeKey === scope.key
    )
  }

  function currentMapSummary(currentScene = findCurrentScene()) {
    if (!currentScene?.id) return undefined
    if (
      sceneMapSummaryProjectId !== currentProjectId() ||
      sceneMapSummarySceneId !== currentScene.id
    ) return undefined
    return sceneMapSummary
  }

  function currentMapError(currentScene = findCurrentScene()) {
    if (
      !currentScene?.id ||
      sceneMapSummaryProjectId !== currentProjectId() ||
      sceneMapSummarySceneId !== currentScene.id
    ) return null
    return sceneMapSummaryError
  }

  function dispose() {
    disposed = true
    boundContainer = null
    scenes = []
    currentSceneId = null
    currentChapter = null
    cursorOffset = 0
    sceneMapSummary = null
    sceneMapSummaryError = null
    sceneMapSummarySceneId = null
    sceneMapSummaryProjectId = null
    sceneMapSummaryPendingSceneId = null
    sceneMapSummaryPendingProjectId = null
    sceneMapSummaryLoading = false
    sceneMapRequestGeneration += 1
    sceneReferencePeople = []
    sceneReferenceLocation = null
    writingContext = { content: "", draftId: null, versionNumber: null, isDirty: false }
    latestConflictCheck = null
    sceneAlertError = null
    invalidateAlertRequest()
    if (panelRenderTimer) {
      clearTimeout(panelRenderTimer)
      panelRenderTimer = null
    }
    activeTab = "lore"
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
    setWritingContext,
    refreshAlerts,
    getCurrentScene,
    getMapSummary,
    getAlerts,
    getLatestConflictCheck,
  }
}

function listItems(value) {
  if (Array.isArray(value)) return value
  return Array.isArray(value?.items) ? value.items : []
}

function dedupeReferences(items) {
  const seen = new Set()
  return items.filter((item) => {
    if (!item || typeof item !== "object") return false
    const key = item.id || item.entity_id || item.name || item.title
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function conflictCheckMatchesScope(check, scope) {
  if (!check || typeof check !== "object") return false
  if (hasOwn(check, "novel_id") && String(check.novel_id || "") !== String(scope.projectId)) {
    return false
  }
  if (hasOwn(check, "chapter_index") && Number(check.chapter_index) !== Number(scope.chapterIndex)) {
    return false
  }
  if (hasOwn(check, "scene_id") && String(check.scene_id || "") !== String(scope.sceneId)) {
    return false
  }

  const checkScope = check.scope && typeof check.scope === "object" ? check.scope : null
  if (checkScope && hasOwn(checkScope, "chapter_index") && Number(checkScope.chapter_index) !== Number(scope.chapterIndex)) {
    return false
  }
  if (checkScope && hasOwn(checkScope, "scene_id") && String(checkScope.scene_id || "") !== String(scope.sceneId)) {
    return false
  }

  return !(Array.isArray(check.items) && check.items.some((item) => (
    (hasOwn(item, "novel_id") && String(item.novel_id || "") !== String(scope.projectId)) ||
    (hasOwn(item, "check_id") && String(item.check_id || "") !== String(check.id || ""))
  )))
}

function hasOwn(value, key) {
  return value != null && Object.prototype.hasOwnProperty.call(value, key)
}
