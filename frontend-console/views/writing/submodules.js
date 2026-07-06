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
    onPublished: () => orchestrator._onPublished(),
  })

  const deepImportRecovery = createDeepImportRecovery({
    state,
    api,
    toast,
    modal,
    esc,
    onPrompt: () => orchestrator._rerender(),
    onStatusChange: () => orchestrator._rerender(),
    onDone: () => router.refresh?.(),
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
  })

  const conflictCheck = createConflictCheck({
    state,
    api,
    toast,
    modal,
    esc,
    onInsertText: (text) => editor.insertTextAtCursor(text),
    onOpenMap: () => scenePanel.openMap(),
    onNavigateOutline: (hint) => {
      router.navigate("outline", null)
      if (hint) toast(hint, "info")
    },
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
