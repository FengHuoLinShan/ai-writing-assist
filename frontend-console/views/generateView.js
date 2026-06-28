/**
 * 生成中心视图
 */

import { bindWorkspaceClick } from "../shared/viewHelper.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import { confirmAiReference } from "../shared/aiReferenceModal.js"

const generateView = {
  onLeave() {
    this._currentType = null
    this._stopActivePolling()
  },
  _currentType: null,
  _activePoller: null,

  async render() {
    setTimeout(() => {
      this._bindEvents()
      this._recoverGenerateWorkflow()
    }, 0)
    return `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:16px;">
        从左侧菜单中选择模块，或使用下方的生成中心统一入口。
      </p>

      <div class="two-column-workspace generate-workspace">
        <div>
          <div class="card" style="margin-bottom:12px;">
            <div class="card-title">生成类型</div>
            <div class="generate-type-grid">
              <div class="clickable generate-card ${this._currentType === "world_character" ? "active" : ""}" data-action="select-type" data-type="world_character">
                <strong>1. 世界与人物结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">世界对象、人物、关系等</p>
              </div>
              <div class="clickable generate-card ${this._currentType === "plot" ? "active" : ""}" data-action="select-type" data-type="plot">
                <strong>2. 剧情结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">剧情线、篇章纲、伏笔计划</p>
              </div>
              <div class="clickable generate-card ${this._currentType === "chapter" ? "active" : ""}" data-action="select-type" data-type="chapter">
                <strong>3. 章节与场景结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">章节卡和场景卡</p>
              </div>
            </div>
          </div>

          <div class="card" id="generate-input-area" style="${this._currentType ? "" : "display:none;"}">
            <div class="card-title">输入意图</div>
            <div class="form-group">
              <label>创作意图/描述 *</label>
              <textarea class="form-textarea" id="generate-intent" rows="3"
                placeholder="描述你想要生成的内容..."></textarea>
            </div>
            <div class="form-group">
              <label>范围</label>
              <select class="form-select" id="generate-scope">
                <option value="arc">当前篇章</option>
                <option value="chapter">当前章节</option>
                <option value="full">全部</option>
              </select>
            </div>
            <div id="generate-extra-fields">
              <div class="form-group">
                <label>相关对象/人物 ID（可选）</label>
                <input class="form-input" id="generate-related" placeholder="逗号分隔" />
              </div>
            </div>
            <button class="btn btn-primary" data-action="start-generate">开始生成</button>
          </div>
        </div>

        <div>
          <div class="card" style="margin-bottom:12px;">
            <div class="card-title">生成流程</div>
            <div id="generate-steps" style="margin-top:8px;">
              <div class="step-item" data-step="1"><span class="step-indicator">1</span> 输入意图</div>
              <div class="step-item" data-step="2"><span class="step-indicator">2</span> 编译上下文</div>
              <div class="step-item" data-step="3"><span class="step-indicator">3</span> 生成候选</div>
              <div class="step-item" data-step="4"><span class="step-indicator">4</span> 预览结果</div>
              <div class="step-item" data-step="5"><span class="step-indicator">5</span> 结构复查</div>
              <div class="step-item" data-step="6"><span class="step-indicator">6</span> 确认写入正史</div>
            </div>
          </div>

          <div class="card" style="min-height:200px;">
            <div class="card-title">结果</div>
            <div id="generate-result">
              <p style="color:var(--text-dim);font-size:13px;">选择左侧生成类型并填写意图后，点击"开始生成"。</p>
            </div>
          </div>
        </div>
      </div>

      <style>
        .generate-card { padding:12px; border:1px solid var(--border); border-radius:4px; background:var(--panel); transition:border-color 0.2s; }
        .generate-card:hover { border-color:var(--accent); }
        .generate-card.active { border-color:var(--accent); background:var(--selected); }
        .step-item { display:flex; align-items:center; gap:8px; padding:6px 0; color:var(--text-dim); font-size:13px; }
        .step-item.active { color:var(--accent); }
        .step-item.done { color:var(--accent-dim); }
        .step-indicator { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:var(--border); color:var(--text-dim); font-size:12px; font-weight:bold; }
        .step-item.active .step-indicator { background:var(--accent); color:var(--bg); }
        .step-item.done .step-indicator { background:var(--accent-dim); color:var(--bg); }
      </style>
    `
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "select-type": (_e, t) => this._selectType(t.getAttribute("data-type")),
      "start-generate": () => this._startGenerate(),
    })
  },

  _selectType(type) {
    this._currentType = type
    const inputArea = document.getElementById("generate-input-area")
    if (inputArea) inputArea.style.display = ""

    const intentEl = document.getElementById("generate-intent")
    const typeNames = {
      world_character: "如：为旧档案缺页篇生成世界对象和人物候选",
      plot: "如：为旧档案缺页篇生成 10 章剧情结构和伏笔计划",
      chapter: "如：为旧档案缺页篇生成章节卡",
      review: "如：复查旧档案缺页篇的章节卡结构",
    }
    if (intentEl) intentEl.placeholder = typeNames[type] || "描述你想要生成的内容..."
    document.querySelectorAll(".generate-card").forEach((el) => {
      el.classList.toggle("active", el.getAttribute("data-type") === type)
    })
  },

  _updateStep(step, status) {
    document.querySelectorAll(".step-item").forEach((el) => {
      const s = parseInt(el.dataset.step, 10)
      el.classList.remove("active", "done")
      if (s === step) {
        if (status === "active") el.classList.add("active")
        if (status === "done") el.classList.add("done")
      } else if (s < step) {
        el.classList.add("done")
      }
    })
  },

  _stopActivePolling() {
    if (this._activePoller?.stop) this._activePoller.stop()
    this._activePoller = null
  },

  _workflowTypeFor(type) {
    return {
      world_character: "world_entity_extraction",
      plot: "plot_structure_generate",
      chapter: "chapter_scene_generate",
    }[type] || "task"
  },

  _destinationHintFor(type) {
    return {
      world_character: "完成后到 世界 > 候选清洗 查看候选对象。",
      plot: "完成后到 大纲 查看生成的剧情结构。",
      chapter: "完成后到 大纲 查看章节与场景结构。",
    }[type] || "完成后可在对应模块查看结果。"
  },

  _renderTaskProgress(progress, type) {
    const resultEl = document.getElementById("generate-result")
    if (!resultEl || !progress) return
    const typeNames = { world_character: "世界与人物结构", plot: "剧情结构", chapter: "章节卡" }
    resultEl.innerHTML = renderWorkflowCard(progress, {
      title: `生成${typeNames[type] || "内容"}`,
      destinationLabel: this._destinationHintFor(type),
    })
  },

  _startTaskPolling(taskId, workflowType, type) {
    this._stopActivePolling()
    this._activePoller = pollTaskProgress({
      taskId,
      workflowType,
      apiClient: api,
      onUpdate: (progress) => {
        this._renderTaskProgress(progress, type)
        if (progress.done) {
          this._updateStep(4, "done")
          this._updateStep(5, "active")
        } else if (progress.failed || progress.cancelled) {
          this._updateStep(3, "")
        } else {
          this._updateStep(3, "active")
        }
      },
      onDone: () => {
        clearActiveWorkflow(taskId)
      },
      onFailed: () => {
        clearActiveWorkflow(taskId)
      },
    })
  },

  _recoverGenerateWorkflow() {
    if (!state.currentProjectId || this._activePoller) return
    const workflows = recoverActiveWorkflows(state.currentProjectId)
    const workflow = workflows.find((item) => item.view === "generate")
    if (!workflow?.taskId) return

    const type = workflow.meta?.type || {
      world_entity_extraction: "world_character",
      plot_structure_generate: "plot",
      chapter_scene_generate: "chapter",
    }[workflow.workflowType] || this._currentType
    if (!type) return

    this._currentType = type
    this._renderTaskProgress(normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflow.workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflow.workflowType), type)
    this._startTaskPolling(workflow.taskId, workflow.workflowType, type)
  },

  async _startGenerate() {
    const intent = document.getElementById("generate-intent")?.value
    if (!intent || !intent.trim()) { toast("请输入创作意图描述", "warning"); return }
    if (!this._currentType) { toast("请先选择生成类型", "warning"); return }

    const resultEl = document.getElementById("generate-result")
    if (!resultEl) return

    const typeNames = { world_character: "世界与人物结构", plot: "剧情结构", chapter: "章节与场景结构" }

    this._updateStep(1, "done")
    this._updateStep(2, "active")
    resultEl.innerHTML = '<div class="loading">步骤 2/6：正在确认 AI 参考资料...</div>'

    try {
      const scope = document.getElementById("generate-scope")?.value || "arc"
      const related = document.getElementById("generate-related")?.value || ""
      const relatedIds = related ? related.split(",").map((s) => s.trim()).filter((s) => s) : undefined

      const config = this._actionConfig(intent, scope)
      const confirmation = await confirmAiReference({
        novel_id: state.currentProjectId,
        action: config.action,
        task: config.task,
        scope: config.scope,
        chapter_index: config.chapterIndex,
        include_pending_objects: true,
        entity_ids: relatedIds,
        character_ids: relatedIds,
        user_note: intent,
      })

      this._updateStep(2, "done")
      this._updateStep(3, "active")
      resultEl.innerHTML = `<div class="loading">步骤 3/6：正在生成${typeNames[this._currentType]}...</div>`

      const workflowType = this._workflowTypeFor(this._currentType)
      const resp = await config.submit(confirmation.id, intent)

      this._updateStep(3, resp ? "done" : "active")
      this._updateStep(4, "active")

      const responseId = resp && (resp.task_id || resp.id)
      if (responseId) {
        persistActiveWorkflow({
          taskId: responseId,
          workflowType,
          projectId: state.currentProjectId,
          view: "generate",
          meta: { type: this._currentType, intent },
        })
        this._renderTaskProgress(normalizeTaskProgress({
          ...resp,
          task_id: responseId,
          task_type: workflowType,
          meta: { workflowType },
        }, workflowType), this._currentType)
        this._startTaskPolling(responseId, workflowType, this._currentType)
      } else {
        resultEl.innerHTML = `
          <div class="card" style="border-color:var(--accent);">
          <p style="color:var(--accent);">&#10003; 生成请求已发送</p>
          <p style="color:var(--text-muted);font-size:12px;">请在对应模块中查看生成的候选对象。</p>
          </div>
        `
      }
      this._updateStep(4, "done")

      setTimeout(() => { this._updateStep(5, "active"); this._updateStep(6, "") }, 500)
    } catch (err) {
      this._updateStep(2, "")
      const errMsg = esc(err.message)
      resultEl.innerHTML = `
        <div style="color:var(--danger);padding:12px;border:1px solid var(--danger);border-radius:4px;">
          <strong>生成失败</strong>
          <p style="margin:4px 0 0 0;font-size:13px;">${errMsg}</p>
          <p style="color:var(--text-dim);font-size:12px;margin:4px 0 0 0;">请确认后端已启动，并且项目已选择。</p>
          <button class="btn btn-sm" style="margin-top:8px;" data-action="start-generate">重试</button>
        </div>
      `
      toast(`生成失败：${err.message}`, "error")
    }
  },

  _actionConfig(intent, scope) {
    const start = 1
    const end = 10
    if (this._currentType === "world_character") {
      return {
        action: "world.entities.extract",
        task: intent || "世界对象补抽",
        scope: scope === "full" ? "full" : "chapter",
        chapterIndex: start,
        submit: (confirmationId) => api.generate.worldCharacter({
          novel_id: state.currentProjectId,
          context_confirmation_id: confirmationId,
          start_chapter: start,
          end_chapter: end,
          instruction: intent,
        }),
      }
    }
    if (this._currentType === "chapter") {
      return {
        action: "outline.chapter_scenes.extract",
        task: intent || "章节/Scene 卡提取",
        scope: "chapter",
        chapterIndex: start,
        submit: (confirmationId) => api.generate.chapterScene({
          novel_id: state.currentProjectId,
          context_confirmation_id: confirmationId,
          chapter_index: start,
          start_chapter: start,
          end_chapter: end,
          instruction: intent,
        }),
      }
    }
    return {
      action: "outline.generate",
      task: intent || "剧情结构生成",
      scope: scope === "chapter" ? "chapter" : "full",
      chapterIndex: start,
      submit: (confirmationId) => api.generate.plotStructure({
        novel_id: state.currentProjectId,
        context_confirmation_id: confirmationId,
        start_chapter: start,
        end_chapter: end,
        instruction: intent,
      }),
    }
  },
}

router.registerView("generate", generateView)
window.generateView = generateView
export default generateView
