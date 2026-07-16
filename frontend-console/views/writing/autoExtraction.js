/**
 * 自动提取 / 深度导入表单模块
 *
 * 负责分阶段自动提取与深度导入表单。
 * 任务提交成功后通过 onTaskStarted 回调交给 deepImportRecovery 轮询。
 */

import { confirmAsync } from "../../shared/confirmAsync.js"
import {
  importAuthorizationNotice,
  importAuthorizationPayload,
} from "../../shared/importAuthorization.js"

const AUTO_EXTRACTION_STAGES = {
  scenes: {
    taskType: "scene_auto_extraction",
    label: "场景（scene）自动提取",
    initialStep: "scene_segmentation",
    initialMessage: "正在提取场景...",
  },
  world_objects: {
    taskType: "world_object_auto_extraction",
    label: "世界对象与别名/关系自动提取",
    initialStep: "entity_extraction",
    initialMessage: "正在提取世界对象与别名/关系...",
  },
  plot_structure: {
    taskType: "plot_structure_auto_extraction",
    label: "剧情线自动提取",
    initialStep: "structure_analysis",
    initialMessage: "正在提取剧情线...",
  },
}

function stageConfig(stage) {
  return AUTO_EXTRACTION_STAGES[stage] || AUTO_EXTRACTION_STAGES.scenes
}

export function createAutoExtraction({
  state,
  api,
  toast,
  modal,
  esc,
  onTaskStarted,
  onRefresh,
}) {
  const projectState = state
  const modalApi = modal
  const escapeHtml = esc

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function showForm(stage = "scenes") {
    const config = stageConfig(stage)
    const chapterList = projectState._chapterList || []
    const lastChapter = chapterList.length > 0 ? Math.max(...chapterList) : 10
    const firstChapter = chapterList.length > 0 ? Math.min(...chapterList) : 1
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="auto-extract-start" type="number" min="1" value="${firstChapter}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="auto-extract-end" type="number" min="1" value="${lastChapter}" />
      </div>
      ${stage === "scenes" ? `
        <label class="writing-checkbox-label writing-form-option">
          <input id="auto-extract-high-quality" type="checkbox" />
          <span>更高质量</span>
          <span class="writing-checkbox-hint">最大推理 + Phase 1c 融合，约需 2 倍时间</span>
        </label>
      ` : ""}
      <p class="writing-form-hint">
        ${escapeHtml(config.label)}会在所选章节范围内创建或补充对应结构资产。
      </p>
      <p class="writing-form-hint" role="note">
        ${escapeHtml(importAuthorizationNotice())}
      </p>
    `
    modalApi.showModalHtml(config.label, formHtml, [{
      text: "确认并开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("auto-extract-end")?.value || "10", 10)
        const highQuality = !!document.getElementById("auto-extract-high-quality")?.checked
        if (end < start) { toast?.("结束章节必须 ≥ 起始章节", "warning"); return }
        modalApi.closeModal()
        await submitStage(stage, start, end, false, highQuality)
      },
    }])
  }

  async function submitStage(stage, startChapter, endChapter, force = false, highQuality = false) {
    const projectId = currentProjectId()
    const config = stageConfig(stage)
    try {
      const result = await api.imports.startStage(
        stage, projectId, startChapter, endChapter, force, highQuality,
        importAuthorizationPayload(),
      )
      if (result.requires_confirmation) {
        const confirmed = await confirmAsync(result.warning, "确认覆盖", {
          confirmAction: modalApi.confirmAction,
          closeModal: modalApi.closeModal,
        })
        if (!confirmed) return
        await submitStage(stage, startChapter, endChapter, true, highQuality)
        return
      }

      if (!result.task_id) {
        toast?.(result.message || `${config.label}未启动`, "warning")
        return
      }

      onTaskStarted?.({
        taskId: result.task_id,
        workflowType: config.taskType,
        stage,
        label: config.label,
        startChapter,
        endChapter,
        highQuality,
      })
      toast?.(`${config.label}已启动`, "success")
    } catch (err) {
      toast?.(err.message || "提交失败", "error")
    }
  }

  function dispose() {
    // 本模块无持久化定时器
  }

  return {
    showForm,
    dispose,
  }
}
