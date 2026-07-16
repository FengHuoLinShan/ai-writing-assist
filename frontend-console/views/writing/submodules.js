/**
 * writingView 子模块工厂
 *
 * 集中创建 writing/ 目录下的子模块，避免 orchestrator 文件过于臃肿。
 * 所有跨模块回调仍由 orchestrator 提供，子模块实例最终挂在 orchestrator 上。
 */
import { createChapterTree } from "./chapterTree.js"
import { createEditor } from "./editor.js"
import { createVersionManager } from "./versions.js"
import { createPublishManager } from "./publish.js"
import { createDeepImportRecovery } from "./deepImportRecovery.js"
import { createAutoExtraction } from "./autoExtraction.js"
import { createConflictCheck } from "./conflictCheck.js"
import { createScenePanel } from "./scenePanel.js"
import { createOutlineFloat } from "./outlineFloat.js"
import { createFocusModeManager } from "./focusMode.js"
import { createWritingTools } from "./tools.js"
import { createMobileQuickNote } from "./mobileQuickNote.js"
import mapQuickCreateView from "../mapQuickCreateView.js"
import { buildMapUrl } from "../mapRouteContext.js"

export function createWritingSubModules(orchestrator, deps) {
  const { state, api, toast, esc, modal, router } = deps

  const chapterTree = createChapterTree({
    state,
    api,
    esc,
    onSelect: (chapterIndex) => orchestrator._selectChapter(chapterIndex),
    onSceneSelect: (sceneId) => orchestrator._selectScene(sceneId),
    onBulkChange: (scope) => orchestrator._onBulkChange(scope),
  })

  const editor = createEditor({
    state,
    api,
    toast,
    onWordcountUpdate: (stats) => orchestrator._onWordcountUpdate(stats),
    onSaveStatusChange: (text) => orchestrator._onSaveStatusChange(text),
    onDraftAdopted: async () => {
      await orchestrator._versions?.load?.(orchestrator._currentChapter)
      orchestrator._syncChapterMetaToTree?.(orchestrator._currentChapter)
      orchestrator._syncSharedStateToSubModules?.()
      await orchestrator._rerender?.()
    },
    onVersionChanged: async () => {
      await orchestrator._versions?.load?.(orchestrator._currentChapter)
      orchestrator._syncChapterMetaToTree?.(orchestrator._currentChapter)
      orchestrator._syncSharedStateToSubModules?.()
      await orchestrator._rerender?.()
    },
    onSceneChange: (sceneId) => {
      orchestrator._syncSharedStateToSubModules()
      orchestrator._scenePanel.update(sceneId, orchestrator._currentChapter)
      orchestrator._rerender()
    },
  })

  const versions = createVersionManager({
    state,
    api,
    toast,
    modal,
    esc,
    onSwitch: (info) => orchestrator._onVersionSwitch(info),
  })

  const publish = createPublishManager({
    state,
    api,
    toast,
    modal,
    esc,
    onStatusChange: (status) => {
      editor.setPublishStatus(status)
      orchestrator._rerender()
    },
    onPublished: (result) => orchestrator._onPublished(result),
  })

  const deepImportRecovery = createDeepImportRecovery({
    state,
    api,
    toast,
    modal,
    esc,
    onPrompt: () => orchestrator._rerender(),
    onStatusChange: () => orchestrator._rerender(),
    onDone: () => orchestrator._onDeepImportDone?.(),
    mapNextStep: {
      openQuickCreate: async (next = {}) => {
        const { projectId: taskProjectId } = next
        const projectId = taskProjectId || state.currentProjectId
        if (!projectId || state.currentProjectId !== projectId) return false
        return mapQuickCreateView.open({
          projectId,
          onCreated: async (createdMap) => {
            if (state.currentProjectId !== projectId) return false
            let remaining = 0
            try {
              const inbox = await api.world.listProjectMapObservationInbox(
                projectId,
                { limit: 1 },
              )
              remaining = Number(inbox?.total || 0)
            } catch {
              remaining = 0
            }
            if (state.currentProjectId !== projectId) return false
            const mapUrl = buildMapUrl({
              projectId,
              mapId: createdMap?.id || null,
              mode: createdMap?.id ? "dashboard" : "overview",
            })
            const opened = window.open(mapUrl, "_blank")
            if (opened) opened.opener = null
            else window.location.assign(mapUrl)
            toast(
              remaining > 0
                ? `地图已创建，收件箱还有 ${remaining} 条待处理动态`
                : "地图已创建",
              "success",
            )
            return deepImportRecovery.completeMapNextStep(next)
          },
        })
      },
      openReviewLocations: async ({ workflowId }) => {
        const query = new URLSearchParams({
          entity_type: "location",
          source: "deep_import",
        })
        if (workflowId) query.set("workflow_id", workflowId)
        return router.navigate("world", "review-objects", true, query)
      },
      openInbox: async ({ projectId: taskProjectId } = {}) => {
        const projectId = taskProjectId || state.currentProjectId
        if (!projectId || state.currentProjectId !== projectId) return false
        const opened = window.open(buildMapUrl({
          projectId,
          mode: "overview",
        }), "_blank")
        if (opened) opened.opener = null
        if (!opened) toast("浏览器阻止了新窗口，请允许后重试", "warning")
        return Boolean(opened)
      },
    },
  })

  const autoExtraction = createAutoExtraction({
    state,
    api,
    toast,
    modal,
    esc,
    onTaskStarted: (taskInfo) => orchestrator._onTaskStarted(taskInfo),
    onRefresh: (result) => orchestrator._onToolsRefresh(result),
  })

  const scenePanel = createScenePanel({
    state,
    api,
    toast,
    esc,
    onOpenMap: (sceneId) => orchestrator._openMap(sceneId),
    onSwitchTab: (tab) => orchestrator._onCockpitTabSwitch(tab),
    onRunConflictCheck: () => orchestrator._runConflictCheck(),
    onOpenConflictCheck: (check) => orchestrator._conflictCheck?.open?.(check),
  })

  const conflictCheck = createConflictCheck({
    state,
    api,
    toast,
    modal,
    esc,
    onInsertText: (text) => editor.insertTextAtCursor(text),
    onOpenMap: (target) => orchestrator._openMap(target),
    onNavigateOutline: (hint) => {
      router.navigate("outline", null)
      if (hint) toast(hint, "info")
    },
    onCheckChanged: () => scenePanel.refreshAlerts(),
  })

  const outlineFloat = createOutlineFloat({ state, api, esc })

  const focusModeManager = createFocusModeManager({
    state,
    onChange: (focusMode, options = {}) => {
      orchestrator._focusMode = focusMode
      if (options?.forceDesktopMode) {
        orchestrator._forceDesktopMode = true
      }
      orchestrator._syncSharedStateToSubModules()
      orchestrator._rerender()
    },
  })

  const tools = createWritingTools({
    state,
    api,
    toast,
    modal,
    esc,
    editor,
    onInsertText: (text) => editor.insertTextAtCursor(text),
    onRefresh: (result) => orchestrator._onToolsRefresh(result),
  })

  const mobileQuickNote = createMobileQuickNote({
    state,
    api,
    toast,
    esc,
    editor,
    onSaved: () => {
      orchestrator._syncChapterMetaToTree(orchestrator._currentChapter)
      orchestrator._syncSharedStateToSubModules()
      orchestrator._rerender()
    },
  })

  return {
    _chapterTree: chapterTree,
    _editor: editor,
    _versions: versions,
    _publish: publish,
    _deepImportRecovery: deepImportRecovery,
    _autoExtraction: autoExtraction,
    _conflictCheck: conflictCheck,
    _scenePanel: scenePanel,
    _outlineFloat: outlineFloat,
    _focusModeManager: focusModeManager,
    _tools: tools,
    _mobileQuickNote: mobileQuickNote,
  }
}
