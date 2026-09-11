import { getToast } from "../../bridge/index.js"
import { createWorkflowManager } from "../../shared/workflowManager.js"

const manager = createWorkflowManager({
  workflowType: "scene_auto_extraction",
  label: "从正文整理场景",
  view: "outline",
  pollNovelId: (_state, projectId) => projectId,
  restartActiveOnRecover: true,
  requireActiveProjectOnAdopt: false,
  claimProjectOnRecover: true,
  clearOnFailed: false,
  matchRecovered: (workflows) => workflows.find(
    (item) => item.workflowType === "scene_auto_extraction",
  ),
  transformRecoveredMeta: (meta) => ({
    start_chapter: meta?.start_chapter ?? meta?.startChapter ?? 1,
    end_chapter: meta?.end_chapter ?? meta?.endChapter ?? 10,
    highQuality: Boolean(meta?.highQuality),
  }),
  onTerminal: (progress) => {
    if (progress.done) {
      getToast()("场景已从正文整理完成", "success")
      return
    }
    getToast()(
      progress.cancelled
        ? "当前正文场景整理已取消"
        : `从正文整理场景失败：${progress.errorMessage || "未知错误"}`,
      progress.cancelled ? "warning" : "error",
    )
  },
})

export const sceneAutoExtractManager = {
  ...manager,
  resetMemory: manager.resetMemoryScope,
}
