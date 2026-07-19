/**
 * useStoryOutline — 小说总纲子标签的状态与操作 composable。
 *
 * DOM 事件由 Vue 模板绑定；模态框操作仍走 showModalHtml。
 *
 * 使用方：OutlineStoryTab.vue
 */
import { computed, onScopeDispose, ref, watch } from "vue"
import { confirmAsync } from "../../../../shared/confirmAsync.js"
import { clearActiveWorkflow } from "../../../../shared/workflowProgress.js"
import {
  getApi,
  getAppState,
  getToast,
  getEsc,
  getShowModalHtml,
  getCloseModal,
} from "../../../bridge/index.js"
import {
  clone,
  idempotencyKey,
  SOURCE_LABELS,
  loadStoryOutlineProps,
  storyOutlineTaskManager,
  validateStoryOutlineContent,
  validateStoryOutlineTaskResult,
} from "./storyOutlineData.js"

const ARRAY_FIELD_LABELS = {
  major_storylines: "主要剧情线",
  macro_movements: "宏观推进",
  open_decisions: "开放决策",
}

export function useStoryOutline(props) {
  const api = getApi()
  const toast = getToast()
  const esc = getEsc()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()

  // ---- 从 props 派生的响应式引用 ----

  const projectId = computed(() => props.projectId)
  const current = ref(props.current)
  const history = ref(props.history)
  const historyTotal = ref(props.historyTotal)
  const characters = ref(props.characters)
  const entities = ref(props.entities)
  const loadError = ref(props.loadError)
  const assetLoadError = ref(props.assetLoadError)

  watch(() => props.current, (value) => { current.value = value })
  watch(() => props.history, (value) => { history.value = value })
  watch(() => props.historyTotal, (value) => { historyTotal.value = value })
  watch(() => props.characters, (value) => { characters.value = value })
  watch(() => props.entities, (value) => { entities.value = value })
  watch(() => props.loadError, (value) => { loadError.value = value })
  watch(() => props.assetLoadError, (value) => { assetLoadError.value = value })

  const currentRevision = computed(() => current.value?.revision || null)
  const hasCurrentRevision = computed(() => Boolean(currentRevision.value))

  // ---- 视图级响应式状态 ----

  const preview = ref(null)       // { taskId, content, baseRevisionId, idempotencyKey, lastApplyFingerprint }
  const applyError = ref(null)    // string | null
  const restoreKeys = new Map()

  // ---- 管理器状态派生 ----

  const taskManager = storyOutlineTaskManager
  const taskProgress = computed(() => taskManager.state.progress)
  const taskNotice = computed(() => taskManager.state.taskNotice)
  const cancelPending = computed(() => taskManager.state.cancelPending)
  const hasRunningTask = computed(() => taskProgress.value && !taskProgress.value.terminal)
  const canCancelTask = computed(() => taskProgress.value
    && !taskProgress.value.terminal
    && taskProgress.value.availableActions?.includes("cancel"))
  const showDismissTask = computed(() => taskProgress.value?.terminal && !preview.value)

  // ---- 任务终态处理 ----

  /** 设置任务终态处理器（由 load 时调用一次）。 */
  const clearTerminalHandler = taskManager.setOnTerminal((type, progress, task, state) => {
    if (type === "done") {
      handleTaskDone(progress, task, state)
    } else if (type === "failed") {
      handleTaskFailed(progress, state)
    }
  })
  onScopeDispose(clearTerminalHandler)

  function handleTaskDone(progress, task, state) {
    if (task?.result?.apply_status === "applied") {
      clearActiveWorkflow(state.taskId)
      state.taskId = null
      state.meta = null
      state.progress = null
      state.taskNotice = "这份小说总纲预览已经采用，无需重复采用。"
      preview.value = null
      return
    }
    try {
      const validContent = validateStoryOutlineTaskResult(task?.result || {})
      preview.value = {
        taskId: state.taskId,
        content: clone(validContent),
        baseRevisionId: state.meta?.apply_base_revision_id || null,
        idempotencyKey: state.meta?.apply_idempotency_key || idempotencyKey(),
      }
      applyError.value = null
      toast("小说总纲建议已生成，请编辑后明确采用", "success")
    } catch (err) {
      clearActiveWorkflow(state.taskId)
      state.taskId = null
      state.meta = null
      state.progress = null
      state.taskNotice = `任务已完成，但返回内容不符合总纲格式：${err.message}`
      preview.value = null
    }
  }

  function handleTaskFailed(progress, state) {
    state.cancelPending = false
    state.taskNotice = progress.cancelled
      ? "小说总纲生成已取消，没有创建 revision。"
      : `小说总纲生成失败：${progress.errorMessage || "未知错误"}`
  }

  // ---- 编辑器采集 ----

  /**
   * 从 DOM 读取编辑器字段并验证。
   * 对应 vanilla _collectEditor。
   */
  function collectEditor(prefix) {
    const read = (suffix) => document.getElementById(`${prefix}-${suffix}`)?.value ?? ""
    const arrays = {}
    for (const field of Object.keys(ARRAY_FIELD_LABELS)) {
      const suffix = field.replaceAll("_", "-")
      try {
        arrays[field] = JSON.parse(read(suffix))
      } catch {
        throw new Error(`${ARRAY_FIELD_LABELS[field]} JSON 格式错误`)
      }
    }
    return validateStoryOutlineContent({
      title: read("title-input"),
      creative_core: {
        premise: read("premise"),
        tone_and_reader_promise: read("tone"),
        story_engine: read("engine"),
        ending_direction: read("ending"),
      },
      outline_markdown: read("markdown"),
      ...arrays,
    })
  }

  // ---- 操作（对应 vanilla 方法） ----

  /** 对应 vanilla _showGenerateForm。 */
  function showGenerateForm() {
    if (taskProgress.value && !taskProgress.value.terminal) {
      toast("已有小说总纲生成任务正在运行", "info")
      return
    }

    const includeCurrent = hasCurrentRevision.value
    const characterHtml = characters.value.map((item) => {
      const id = item?.entity_id || item?.id || null
      if (!id) return ""
      return `<label class="checkbox-label"><input type="checkbox" name="story-outline-character" value="${esc(id)}" /><span>${esc(item.name || item.title || "未命名人物")}</span></label>`
    }).join("") || '<span class="form-hint">暂无可选人物。</span>'

    const entityHtml = entities.value.map((item) => {
      const id = item?.entity_id || item?.id || null
      if (!id) return ""
      return `<label class="checkbox-label"><input type="checkbox" name="story-outline-entity" value="${esc(id)}" /><span>${esc(item.name || item.title || "未命名对象")}</span></label>`
    }).join("") || '<span class="form-hint">暂无可选世界对象。</span>'

    const html = `
      <div class="form-group">
        <label for="story-outline-author-intent">作者意图</label>
        <textarea class="form-textarea" id="story-outline-author-intent" rows="5" placeholder="你想写一个怎样的长篇故事？"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-planned-scale">计划尺度</label>
        <textarea class="form-textarea" id="story-outline-planned-scale" rows="3" placeholder="例如：长篇、三部、预计百万字"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-coverage">覆盖描述</label>
        <textarea class="form-textarea" id="story-outline-coverage" rows="3" placeholder="例如：覆盖全书，重点先锁定前两部的方向"></textarea>
      </div>
      <fieldset class="form-group">
        <legend>可选人物（可为空；为空时自动取 Top-K，最多显式选择 12 个）</legend>
        <div class="checkbox-list">${characterHtml}</div>
      </fieldset>
      <fieldset class="form-group">
        <legend>可选世界对象（可为空；为空时自动取 Top-K，最多显式选择 24 个）</legend>
        <div class="checkbox-list">${entityHtml}</div>
      </fieldset>
      ${includeCurrent ? `
        <label class="checkbox-label form-group">
          <input type="checkbox" id="story-outline-include-current" />
          <span>把当前总纲纳入本次生成参考</span>
        </label>
      ` : ""}
      <p class="form-hint">AI 不会预先创建篇章纲或 Scene，也不会自动采用结果。</p>
    `

    showModalHtml("AI 生成小说总纲", html, [{
      text: "生成可编辑预览",
      class: "btn-primary",
      handler: () => submitGeneration(),
    }], { size: "large" })
  }

  /** 对应 vanilla _submitGeneration。 */
  async function submitGeneration() {
    const pid = projectId.value
    const authorIntent = document.getElementById("story-outline-author-intent")?.value?.trim() || ""
    const plannedScale = document.getElementById("story-outline-planned-scale")?.value?.trim() || ""
    const coverage = document.getElementById("story-outline-coverage")?.value?.trim() || ""
    if (!authorIntent || !plannedScale || !coverage) {
      toast("请完整填写作者意图、计划尺度和覆盖描述", "warning")
      return false
    }

    const selectedCharacterIds = [...document.querySelectorAll('input[name="story-outline-character"]:checked')]
      .map((input) => input.value)
    const selectedEntityIds = [...document.querySelectorAll('input[name="story-outline-entity"]:checked')]
      .map((input) => input.value)
    if (selectedCharacterIds.length > 12 || selectedEntityIds.length > 24) {
      toast("人物最多选 12 个，世界对象最多选 24 个", "warning")
      return false
    }

    const includeCurrent = Boolean(document.getElementById("story-outline-include-current")?.checked)
    const baseRevisionId = current.value?.current_revision_id || null
    const applyKey = idempotencyKey()

    try {
      const response = await api.outline.generateStoryOutline({
        novel_id: pid,
        author_intent: authorIntent,
        planned_scale: plannedScale,
        coverage,
        selected_character_ids: selectedCharacterIds,
        selected_entity_ids: selectedEntityIds,
        include_current_outline: includeCurrent,
      })
      if (!response?.task_id) throw new Error("生成任务未返回任务编号")

      const meta = {
        project_id: pid,
        novel_id: pid,
        action: "outline.story_outline.generate",
        apply_base_revision_id: baseRevisionId,
        apply_idempotency_key: applyKey,
      }
      if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
        taskManager.adopt(response, meta, pid, { attach: false })
        return true
      }
      taskManager.adopt(response, meta, pid)
      closeModal()
      toast("小说总纲生成任务已提交", "success")
      return true
    } catch (err) {
      toast(err.message || "提交生成任务失败", "error")
      return false
    }
  }

  /** 对应 vanilla _applyPreview。 */
  async function applyPreview() {
    if (!preview.value) return false
    const pid = projectId.value
    if (getAppState()?.currentProjectId !== pid) {
      applyError.value = "项目已切换，请回到原项目后重新加载总纲。"
      return false
    }

    try {
      const content = collectEditor("story-outline-preview")
      const attemptFingerprint = JSON.stringify({
        task_id: preview.value.taskId,
        base_revision_id: preview.value.baseRevisionId,
        content,
      })
      if (preview.value.lastApplyFingerprint && preview.value.lastApplyFingerprint !== attemptFingerprint) {
        preview.value.idempotencyKey = idempotencyKey()
      }
      preview.value.lastApplyFingerprint = attemptFingerprint

      const response = await api.outline.applyStoryOutlinePreview({
        novel_id: pid,
        source_task_id: preview.value.taskId,
        ...content,
        base_revision_id: preview.value.baseRevisionId,
        idempotency_key: preview.value.idempotencyKey,
        confirmed: true,
      })
      clearActiveWorkflow(preview.value.taskId)
      taskManager.state.taskId = null
      taskManager.state.meta = null
      taskManager.state.progress = null
      taskManager.stop()
      preview.value = null
      applyError.value = null
      toast(`小说总纲已采用为新版本 v${response?.version_number || ""}`, "success")
      await reload()
      return response
    } catch (err) {
      const message = err?.status === 409
        ? "当前总纲已在其他会话中变更，请重新加载后再生成或采用。"
        : err.message || "采用小说总纲失败"
      applyError.value = message
      toast(message, "error")
      return false
    }
  }

  /** 对应 vanilla _discardPreview。 */
  async function discardPreview() {
    if (!preview.value) return
    const confirmed = await confirmAsync(
      "确认放弃这份尚未采用的小说总纲建议？",
      "放弃建议",
    )
    if (!confirmed) return
    clearActiveWorkflow(preview.value.taskId)
    taskManager.state.taskId = null
    taskManager.state.meta = null
    taskManager.state.progress = null
    preview.value = null
    applyError.value = null
  }

  /** 对应 vanilla _cancelTask。 */
  async function cancelTask() {
    const confirmed = await confirmAsync(
      "确认取消当前小说总纲生成任务？未采用的预览不会写入。",
      "确认取消",
    )
    if (!confirmed) return false
    return taskManager.cancel(projectId.value)
  }

  /** 对应 vanilla _dismissTask。 */
  function dismissTask() {
    taskManager.dismiss()
  }

  /** 对应 vanilla _showManualEditor。 */
  function showManualEditor() {
    const pid = projectId.value
    const baseRevisionId = current.value?.current_revision_id || null
    const key = idempotencyKey()
    const content = hasCurrentRevision.value ? clone(currentRevision.value) : emptyContent()

    const html = renderEditor(content, "story-outline-manual", {
      title: hasCurrentRevision.value ? "编辑小说总纲为新版本" : "手工创建小说总纲",
      hint: "保存会创建不可变 revision，不会覆盖当前或历史版本。",
    })

    showModalHtml("编辑小说总纲", html, [{
      text: "保存为新版本",
      class: "btn-primary",
      handler: async () => {
        if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
          toast("项目已切换，请在当前项目重新打开编辑器", "warning")
          return false
        }
        try {
          const response = await api.outline.createStoryOutlineRevision(pid, {
            ...collectEditor("story-outline-manual"),
            base_revision_id: baseRevisionId,
            idempotency_key: key,
            source: "manual",
            provenance: { actor: "author", note: "前端手工保存" },
          })
          closeModal()
          toast(`小说总纲已保存为新版本 v${response?.version_number || ""}`, "success")
          await reload()
          return true
        } catch (err) {
          const message = err?.status === 409
            ? "当前总纲已变更，请关闭编辑器并重新加载后再编辑。"
            : err.message || "保存失败"
          toast(message, "error")
          return false
        }
      },
    }], { size: "full", protectUnsaved: true })
  }

  /** 对应 vanilla _viewRevision。 */
  async function viewRevision(revisionId) {
    if (!revisionId) return
    const pid = projectId.value
    try {
      const revision = await api.outline.getStoryOutlineRevision(revisionId, pid)
      if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) return
      showModalHtml(
        `小说总纲历史版本 v${revision.version_number}`,
        renderContentReadOnly(revision),
        [{ text: "关闭", class: "btn-ghost", handler: closeModal }],
        { size: "full" },
      )
    } catch (err) {
      toast(err.message || "加载历史版本失败", "error")
    }
  }

  /** 对应 vanilla _restoreRevision。 */
  async function restoreRevision(revisionId) {
    const pid = projectId.value
    if (!revisionId) return false
    const confirmed = await confirmAsync(
      "确认采用该历史内容？系统会创建一个新 revision，不会原地回滚或改写历史。",
      "采用为新版本",
    )
    if (!confirmed) return false
    if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
      toast("项目已切换，请在当前项目重新选择历史版本", "warning")
      return false
    }
    const key = restoreKeys.get(revisionId) || idempotencyKey()
    restoreKeys.set(revisionId, key)
    try {
      const response = await api.outline.restoreStoryOutlineRevision(revisionId, pid, {
        base_revision_id: current.value?.current_revision_id || null,
        idempotency_key: key,
        confirmed: true,
        provenance: { actor: "author", note: "前端显式采用历史内容" },
      })
      restoreKeys.delete(revisionId)
      toast(`历史内容已采用为新版本 v${response?.version_number || ""}`, "success")
      await reload()
      return response
    } catch (err) {
      const message = err?.status === 409
        ? "当前总纲已变更，请重新加载历史后再采用。"
        : err.message || "采用历史内容失败"
      toast(message, "error")
      return false
    }
  }

  /** 对应 vanilla _reload：原位重取数据，保留未采用预览并 rebase。 */
  async function reload() {
    applyError.value = null
    storyOutlineTaskManager.state.taskNotice = null
    const pid = projectId.value
    const previewTaskId = preview.value?.taskId || null
    if (previewTaskId) {
      try {
        preview.value.content = collectEditor("story-outline-preview")
      } catch (err) {
        applyError.value = err.message || "预览格式有误，请修正后再重新加载。"
        return false
      }
    }
    const next = await loadStoryOutlineProps(pid, { recoverTask: false })
    if (projectId.value !== pid || getAppState()?.currentProjectId !== pid) return false
    current.value = next.current
    history.value = next.history
    historyTotal.value = next.historyTotal
    characters.value = next.characters
    entities.value = next.entities
    loadError.value = next.loadError
    assetLoadError.value = next.assetLoadError
    if (previewTaskId && preview.value?.taskId === previewTaskId) {
      const nextBaseRevisionId = current.value?.current_revision_id || null
      if (preview.value.baseRevisionId !== nextBaseRevisionId) {
        preview.value.baseRevisionId = nextBaseRevisionId
        preview.value.idempotencyKey = idempotencyKey()
        preview.value.lastApplyFingerprint = null
      }
    }
    return true
  }

  // ---- 纯渲染辅助（模态框 HTML 生成） ----

  function emptyContent() {
    return {
      title: "",
      creative_core: {
        premise: "",
        tone_and_reader_promise: "",
        story_engine: "",
        ending_direction: null,
      },
      outline_markdown: "",
      major_storylines: [],
      macro_movements: [],
      open_decisions: [],
    }
  }

  function _h(val) {
    return typeof esc === "function" ? esc(val) : String(val ?? "")
  }

  function renderContentReadOnly(content) {
    const core = content?.creative_core || {}
    const storylineHtml = (content?.major_storylines || []).map((item) => `
      <article class="card">
        <h5>${_h(item.name)}</h5>
        <p><strong>叙事功能：</strong>${_h(item.narrative_function)}</p>
        <p><strong>轨迹：</strong>${_h(item.trajectory)}</p>
        <p><strong>交汇点：</strong>${_h((item.intersections || []).join("、") || "暂无")}</p>
        <p><strong>收束方向：</strong>${_h(item.resolution_direction)}</p>
      </article>
    `).join("")
    const movementHtml = (content?.macro_movements || []).map((item) => `
      <article class="card">
        <h5>${_h(item.name)}</h5>
        <p>${_h(item.story_state_change)}</p>
        <p><strong>推进剧情线：</strong>${_h((item.advanced_storylines || []).join("、") || "暂无")}</p>
      </article>
    `).join("")
    const decisionHtml = (content?.open_decisions || []).map((item) => `
      <article class="card">
        <h5>${_h(item.question)}</h5>
        <p>${_h(item.why_it_matters)}</p>
        <p><strong>可选方向：</strong>${_h((item.options || []).join("、") || "暂无")}</p>
      </article>
    `).join("")
    return `
      <section><h4>${_h(content?.title)}</h4></section>
      <div class="form-grid form-grid--2">
        <div class="card"><h4>核心前提</h4><p>${_h(core.premise)}</p></div>
        <div class="card"><h4>基调与读者承诺</h4><p>${_h(core.tone_and_reader_promise)}</p></div>
        <div class="card"><h4>故事引擎</h4><p>${_h(core.story_engine)}</p></div>
        <div class="card"><h4>结局方向</h4><p>${_h(core.ending_direction || "待决定")}</p></div>
      </div>
      <section><h4>高层总纲</h4><pre class="generate-markdown-pre">${_h(content?.outline_markdown)}</pre></section>
      <section><h4>主要剧情线</h4>${storylineHtml || '<p class="form-hint">暂无。</p>'}</section>
      <section><h4>宏观推进</h4>${movementHtml || '<p class="form-hint">暂无。</p>'}</section>
      <section><h4>开放决策</h4>${decisionHtml || '<p class="form-hint">暂无。</p>'}</section>
    `
  }

  function renderEditor(content, prefix, { title, hint, actions = "", error = null } = {}) {
    const core = content?.creative_core || {}
    const p = prefix
    return `
      <section class="card" aria-labelledby="${_h(p)}-title">
        <div class="section-header">
          <div><h3 id="${_h(p)}-title">${_h(title)}</h3><p class="form-hint">${_h(hint)}</p></div>
        </div>
        <div class="form-group">
          <label for="${_h(p)}-title-input">标题</label>
          <input class="form-input" id="${_h(p)}-title-input" value="${_h(content?.title)}" />
        </div>
        <div class="form-grid form-grid--2">
          ${_textarea(`${p}-premise`, "核心前提", core.premise)}
          ${_textarea(`${p}-tone`, "基调与读者承诺", core.tone_and_reader_promise)}
          ${_textarea(`${p}-engine`, "故事引擎", core.story_engine)}
          ${_textarea(`${p}-ending`, "结局方向（可留空）", core.ending_direction || "")}
        </div>
        ${_textarea(`${p}-markdown`, "高层总纲（Markdown）", content?.outline_markdown, 14)}
        <div class="form-group">
          <label for="${_h(p)}-major-storylines">主要剧情线（JSON 数组）</label>
          <p class="form-hint">每项字段：name、narrative_function、trajectory、intersections 字符串数组、resolution_direction。可以是 []。</p>
          <textarea class="form-textarea" id="${_h(p)}-major-storylines" rows="12">${_h(JSON.stringify(content?.major_storylines || [], null, 2))}</textarea>
        </div>
        <div class="form-group">
          <label for="${_h(p)}-macro-movements">宏观推进（JSON 数组）</label>
          <p class="form-hint">每项字段：name、story_state_change、advanced_storylines 字符串数组；它们是浏览导航摘要，不作为数据库关联键。可以是 []。</p>
          <textarea class="form-textarea" id="${_h(p)}-macro-movements" rows="10">${_h(JSON.stringify(content?.macro_movements || [], null, 2))}</textarea>
        </div>
        <div class="form-group">
          <label for="${_h(p)}-open-decisions">开放决策（JSON 数组）</label>
          <p class="form-hint">每项字段：question、why_it_matters、options 字符串数组。可以是 []。</p>
          <textarea class="form-textarea" id="${_h(p)}-open-decisions" rows="10">${_h(JSON.stringify(content?.open_decisions || [], null, 2))}</textarea>
        </div>
        <p id="story-outline-apply-error" class="form-error" role="alert">${_h(error || "")}</p>
        ${actions ? `<div class="form-actions">${actions}</div>` : ""}
      </section>
    `
  }

  function _textarea(id, label, value, rows = 5) {
    return `
      <div class="form-group">
        <label for="${_h(id)}">${_h(label)}</label>
        <textarea class="form-textarea" id="${_h(id)}" rows="${_h(rows)}">${_h(value)}</textarea>
      </div>
    `
  }

  return {
    // 派生状态
    projectId,
    current,
    currentRevision,
    hasCurrentRevision,
    history,
    historyTotal,
    characters,
    entities,
    loadError,
    assetLoadError,
    preview,
    applyError,
    taskManager,
    taskProgress,
    taskNotice,
    cancelPending,
    hasRunningTask,
    canCancelTask,
    showDismissTask,

    // 操作
    showGenerateForm,
    submitGeneration,
    applyPreview,
    discardPreview,
    cancelTask,
    dismissTask,
    showManualEditor,
    viewRevision,
    restoreRevision,
    reload,
    collectEditor,

    // 渲染辅助
    renderContentReadOnly,
    renderEditor,
  }
}
