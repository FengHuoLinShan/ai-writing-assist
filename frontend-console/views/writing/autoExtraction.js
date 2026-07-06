/**
 * 自动提取 / 深度导入表单模块
 *
 * 负责分阶段自动提取、深度导入表单与章节卡提取的弹窗提交。
 * 任务提交成功后通过 onTaskStarted 回调交给 deepImportRecovery 轮询。
 */

import { confirmAiReference } from "../../shared/aiReferenceModal.js"

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
        <label style="display:flex;gap:8px;align-items:center;font-size:12px;color:var(--text-body);margin-top:8px;">
          <input id="auto-extract-high-quality" type="checkbox" />
          更高质量 <span style="color:var(--text-dim);">需要标准提取约8倍时间</span>
        </label>
      ` : ""}
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        ${escapeHtml(config.label)}会在所选章节范围内创建或补充对应结构资产。
      </p>
    `
    modalApi.showModalHtml(config.label, formHtml, [{
      text: "开始提取",
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

  function showDeepImportForm() {
    showForm("scenes")
  }

  async function submitStage(stage, startChapter, endChapter, force = false, highQuality = false) {
    const projectId = currentProjectId()
    const config = stageConfig(stage)
    try {
      const result = await api.imports.startStage(
        stage, projectId, startChapter, endChapter, force, highQuality,
      )
      if (result.requires_confirmation) {
        const confirmed = await new Promise((resolve) => {
          modalApi.confirmAction(result.warning, () => resolve(true), "确认覆盖")
          setTimeout(() => {
            const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
            if (cancelBtn) cancelBtn.onclick = () => resolve(false)
          }, 50)
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

  async function extractChapterCards() {
    const projectId = currentProjectId()
    const chapterList = projectState._chapterList || []
    if (!chapterList.length) { toast?.("没有可分析的章节", "warning"); return }
    const firstCh = chapterList[0]
    const lastCh = chapterList[chapterList.length - 1]
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="extract-start" type="number" min="1" value="${firstCh}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="extract-end" type="number" min="1" value="${lastCh}" />
      </div>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        调用 AI 分析章节内容，生成 Scene 卡（场景目标、冲突、情感节奏等）。
      </p>
    `
    modalApi.showModalHtml("AI 提取章节卡", formHtml, [{
      text: "开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("extract-end")?.value || "10", 10)
        if (end < start) { toast?.("结束章节必须 ≥ 起始章节", "warning"); return }
        modalApi.closeModal()
        try {
          const confirmation = await confirmAiReference({
            novel_id: projectId,
            action: "outline.chapter_scenes.extract",
            task: "章节/Scene 卡提取",
            scope: "chapter",
            chapter_index: start,
            include_pending_objects: true,
          })
          toast?.("章节/Scene 卡提取任务已提交", "info")
          const result = await api.outline.extractChapterScenes({
            novel_id: projectId,
            context_confirmation_id: confirmation.id,
            chapter_index: start,
            start_chapter: start,
            end_chapter: end,
          })
          const updatedScenes = await api.outline.listScenesOrdered(projectId) || []
          onTaskStarted?.({
            taskId: result.task_id || result.id,
            workflowType: "chapter_card_generation",
            stage: "chapter_cards",
            label: "章节/Scene 卡提取",
            startChapter: start,
            endChapter: end,
          })
          onRefresh?.(updatedScenes)
          toast?.("章节/Scene 卡提取已进入后台", "success")
        } catch (err) {
          toast?.(err.message || "提取失败", "error")
        }
      },
    }])
  }

  function dispose() {
    // 本模块无持久化定时器
  }

  return {
    showForm,
    showDeepImportForm,
    extractChapterCards,
    dispose,
  }
}
