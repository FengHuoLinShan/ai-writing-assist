/**
 * useStoryOutline — 小说总纲子标签的状态与操作 composable。
 *
 * DOM 事件由 Vue 模板绑定；模态框操作仍走 showModalHtml。
 *
 * 使用方：OutlineStoryTab.vue
 */
import { computed, nextTick, onScopeDispose, ref, watch } from "vue"
import { confirmAsync } from "../../../../shared/confirmAsync.js"
import { clearActiveWorkflow, createOperationId } from "../../../../shared/workflowProgress.js"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import {
  getApi,
  getAppState,
  getToast,
  getEsc,
  getShowModalHtml,
  getCloseModal,
} from "../../../bridge/index.js"
import {
  editableStoryOutlineContent,
  idempotencyKey,
  SOURCE_LABELS,
  loadStoryOutlineProps,
  storyOutlineTaskManager,
  validateStoryOutlineContent,
  validateStoryOutlineTaskResult,
} from "./storyOutlineData.js"

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

  const preview = ref(null)       // { projectId, taskId, content, baseRevisionId, idempotencyKey, lastApplyFingerprint }
  const applyError = ref(null)    // string | null
  const applying = ref(false)
  const previewConflict = ref(false)
  const rebasingPreview = ref(false)
  const previewRestored = ref(false)
  const previewStorageError = ref("")
  const previewDraftSavedAt = ref(null)
  const restoreKeys = new Map()
  let previewDraftTimer = null
  let disposed = false

  const previewDraftKey = (pid) => `story-outline-preview-draft:${encodeURIComponent(pid || "none")}`

  const previewSaveState = computed(() => {
    if (applying.value) return "正在采用新版本…"
    if (previewStorageError.value) return "本地暂存不可用"
    if (!previewDraftSavedAt.value) return "修改后会自动暂存到本机"
    const date = new Date(previewDraftSavedAt.value)
    return Number.isNaN(date.getTime())
      ? "修改已暂存在本机"
      : `修改已暂存在本机 · ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
  })

  watch(() => preview.value?.content, () => {
    if (!preview.value) return
    applyError.value = previewConflict.value ? applyError.value : null
    schedulePreviewDraft()
  }, { deep: true })

  watch(projectId, (nextProjectId, previousProjectId) => {
    if (nextProjectId === previousProjectId || !preview.value) return
    persistPreviewDraft()
    preview.value = null
    previewConflict.value = false
    previewRestored.value = false
    applyError.value = null
  })

  useLeaveGuard(() => {
    if (!preview.value) return true
    persistPreviewDraft()
    if (!applying.value) return true
    toast("正在采用故事总览，请稍候", "info")
    return false
  })

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
  onScopeDispose(() => {
    disposed = true
    persistPreviewDraft()
    clearTimeout(previewDraftTimer)
    clearTerminalHandler()
  })

  function handleTaskDone(progress, task, state) {
    if (
      task?.meta?.novel_id
      && (task.meta.novel_id !== projectId.value || getAppState()?.currentProjectId !== projectId.value)
    ) return
    if (task?.result?.apply_status === "applied") {
      clearPreviewDraft()
      clearActiveWorkflow(state.taskId)
      state.taskId = null
      state.meta = null
      state.progress = null
      state.taskNotice = "这份故事总览已经采用，无需重复采用。"
      preview.value = null
      previewConflict.value = false
      applyError.value = null
      return
    }
    try {
      const validContent = validateStoryOutlineTaskResult(task?.result || {})
      const savedDraft = readPreviewDraft(state.taskId)
      preview.value = {
        projectId: projectId.value,
        taskId: state.taskId,
        content: editableStoryOutlineContent(savedDraft?.content || validContent),
        baseRevisionId: savedDraft?.base_revision_id ?? state.meta?.apply_base_revision_id ?? null,
        idempotencyKey: savedDraft?.idempotency_key || state.meta?.apply_idempotency_key || idempotencyKey(),
        lastApplyFingerprint: savedDraft?.last_apply_fingerprint || null,
      }
      previewRestored.value = Boolean(savedDraft)
      previewConflict.value = false
      previewDraftSavedAt.value = savedDraft?.saved_at || null
      previewStorageError.value = ""
      applyError.value = null
      if (!savedDraft) toast("故事总览建议已生成，请编辑后明确采用", "success")
    } catch (err) {
      clearActiveWorkflow(state.taskId)
      state.taskId = null
      state.meta = null
      state.progress = null
      state.taskNotice = `任务已完成，但返回内容不符合总纲格式：${err.message}`
      preview.value = null
    }
  }

  function readPreviewDraft(taskId) {
    if (!props.projectId || !taskId) return null
    try {
      const value = JSON.parse(localStorage.getItem(previewDraftKey(projectId.value)) || "null")
      if (
        !value
        || value.project_id !== props.projectId
        || value.task_id !== taskId
        || !value.content
        || typeof value.content !== "object"
      ) return null
      return value
    } catch {
      try { localStorage.removeItem(previewDraftKey(projectId.value)) } catch { /* noop */ }
      return null
    }
  }

  function persistPreviewDraft() {
    clearTimeout(previewDraftTimer)
    previewDraftTimer = null
    if (!preview.value?.projectId) return
    try {
      const savedAt = new Date().toISOString()
      localStorage.setItem(previewDraftKey(preview.value.projectId), JSON.stringify({
        project_id: preview.value.projectId,
        task_id: preview.value.taskId,
        base_revision_id: preview.value.baseRevisionId,
        idempotency_key: preview.value.idempotencyKey,
        last_apply_fingerprint: preview.value.lastApplyFingerprint || null,
        saved_at: savedAt,
        content: editableStoryOutlineContent(preview.value.content),
      }))
      previewDraftSavedAt.value = savedAt
      previewStorageError.value = ""
    } catch {
      previewStorageError.value = "浏览器无法暂存这份修改。离开或刷新前，请先采用为新版本。"
    }
  }

  function schedulePreviewDraft() {
    clearTimeout(previewDraftTimer)
    previewDraftTimer = setTimeout(persistPreviewDraft, 250)
  }

  function clearPreviewDraft(pid = preview.value?.projectId || projectId.value) {
    clearTimeout(previewDraftTimer)
    previewDraftTimer = null
    try { localStorage.removeItem(previewDraftKey(pid)) } catch { /* noop */ }
    previewDraftSavedAt.value = null
    previewStorageError.value = ""
    previewRestored.value = false
  }

  function handleTaskFailed(progress, state) {
    state.cancelPending = false
    state.taskNotice = progress.cancelled
      ? "故事总览生成已取消，没有创建新版本。"
      : `故事总览生成失败：${progress.errorMessage || "未知错误"}`
  }

  // ---- 操作（对应 vanilla 方法） ----

  /** 对应 vanilla _showGenerateForm。 */
  async function showGenerateForm() {
    if (taskProgress.value && !taskProgress.value.terminal) {
      toast("已有故事总览正在生成", "info")
      return
    }
    if (preview.value) {
      const confirmed = await confirmAsync(
        "已有一份尚未采用的 AI 建议。继续生成后，新建议会替换它；你当前的修改会保留到新任务成功完成。",
        "继续生成",
      )
      if (!confirmed) return
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
      <div class="story-outline-generate">
        <p class="story-outline-generate__intro">先告诉 AI 这次要规划的方向。生成后可以完整修改，不会直接改变当前版本。</p>
        <div id="story-outline-generate-error-summary" class="form-error story-outline-generate__error-summary" role="alert" tabindex="-1" hidden></div>
        <div class="form-group">
          <label for="story-outline-author-intent">你想写一个怎样的故事？ <span class="story-outline-generate__required">必填</span></label>
          <textarea class="form-textarea" id="story-outline-author-intent" rows="4" required aria-describedby="story-outline-author-intent-hint story-outline-author-intent-error" placeholder="例如：一名失去记忆的档案员追查被整座城市遗忘的真相。"></textarea>
          <p id="story-outline-author-intent-hint" class="form-hint">写清主角、核心矛盾和最想保留的吸引力即可。</p>
          <p id="story-outline-author-intent-error" class="form-error" hidden></p>
        </div>
        <div class="story-outline-generate__quick-fields">
          <div class="form-group">
            <label for="story-outline-planned-scale">预计篇幅 <span class="story-outline-generate__required">必填</span></label>
            <input class="form-input" id="story-outline-planned-scale" required aria-describedby="story-outline-planned-scale-hint story-outline-planned-scale-error" placeholder="例如：30 万字长篇、三部曲" />
            <p id="story-outline-planned-scale-hint" class="form-hint">大致体量即可，后续仍可调整。</p>
            <p id="story-outline-planned-scale-error" class="form-error" hidden></p>
          </div>
          <div class="form-group">
            <label for="story-outline-coverage">这次先规划到哪里？ <span class="story-outline-generate__required">必填</span></label>
            <input class="form-input" id="story-outline-coverage" required aria-describedby="story-outline-coverage-hint story-outline-coverage-error" placeholder="例如：覆盖全书，先细化前两部" />
            <p id="story-outline-coverage-hint" class="form-hint">说明全书或某一阶段，避免生成范围失焦。</p>
            <p id="story-outline-coverage-error" class="form-error" hidden></p>
          </div>
        </div>
        ${includeCurrent ? `
          <label class="checkbox-label story-outline-generate__current">
            <input type="checkbox" id="story-outline-include-current" />
            <span><strong>参考当前故事总览</strong><small>适合沿用现有方向继续发展；关闭后更偏向另起方案。</small></span>
          </label>
        ` : ""}
        <details class="story-outline-generate__references">
          <summary><span>选择参考资料（可选）</span><span class="form-hint">不选时由系统挑选</span></summary>
          <div class="story-outline-generate__reference-body">
            ${assetLoadError.value ? `<p class="form-error" role="status">${esc(assetLoadError.value)}；仍可只用上方故事方向生成。</p>` : ""}
            <p class="form-hint">只选择这次必须参与规划的资料；不选择时，系统会从当前作品中挑选相关内容。</p>
            <fieldset id="story-outline-character-fieldset" class="story-outline-generate__reference-group" tabindex="-1">
              <legend>人物 <span id="story-outline-character-count" class="form-hint">已选 0 / 12</span></legend>
              <div class="checkbox-list">${characterHtml}</div>
              <p id="story-outline-character-error" class="form-error" role="status" hidden></p>
            </fieldset>
            <fieldset id="story-outline-entity-fieldset" class="story-outline-generate__reference-group" tabindex="-1">
              <legend>地点、物品与其他设定 <span id="story-outline-entity-count" class="form-hint">已选 0 / 24</span></legend>
              <div class="checkbox-list">${entityHtml}</div>
              <p id="story-outline-entity-error" class="form-error" role="status" hidden></p>
            </fieldset>
          </div>
        </details>
        <p class="story-outline-generate__safety">生成结果会先进入可编辑建议；不会创建篇章或场景，也不会自动采用。</p>
      </div>
    `

    showModalHtml("用 AI 生成故事总览", html, [{
      text: "开始生成预览",
      class: "btn-primary",
      handler: () => submitGeneration(),
    }])

    const root = document.querySelector(".story-outline-generate")
    root?.addEventListener("change", (event) => {
      const input = event.target
      if (!(input instanceof HTMLInputElement) || input.type !== "checkbox" || !input.name) return
      const limit = input.name === "story-outline-character" ? 12 : input.name === "story-outline-entity" ? 24 : null
      if (!limit) return
      const checked = [...root.querySelectorAll(`input[name="${input.name}"]:checked`)]
      const key = input.name === "story-outline-character" ? "character" : "entity"
      const error = document.getElementById(`story-outline-${key}-error`)
      if (checked.length > limit) {
        input.checked = false
        error.textContent = `最多选择 ${limit} 项。请先取消一项，再选择其他资料。`
        error.hidden = false
      } else {
        error.textContent = ""
        error.hidden = true
      }
      document.getElementById(`story-outline-${key}-count`).textContent = `已选 ${Math.min(checked.length, limit)} / ${limit}`
    })
  }

  function clearGenerationErrors() {
    const summary = document.getElementById("story-outline-generate-error-summary")
    if (summary) {
      summary.hidden = true
      summary.replaceChildren()
    }
    for (const id of ["story-outline-author-intent", "story-outline-planned-scale", "story-outline-coverage", "story-outline-character-fieldset", "story-outline-entity-fieldset"]) {
      document.getElementById(id)?.removeAttribute("aria-invalid")
    }
    for (const id of ["story-outline-author-intent-error", "story-outline-planned-scale-error", "story-outline-coverage-error"]) {
      const error = document.getElementById(id)
      if (!error) continue
      error.hidden = true
      error.textContent = ""
    }
  }

  function showGenerationErrors(errors) {
    const summary = document.getElementById("story-outline-generate-error-summary")
    if (!summary || !errors.length) return
    summary.replaceChildren(document.createTextNode("请先补充或修正："))
    const list = document.createElement("ul")
    for (const error of errors) {
      const item = document.createElement("li")
      if (error.id) {
        const link = document.createElement("a")
        link.href = `#${error.id}`
        link.textContent = error.label
        link.addEventListener("click", (event) => {
          event.preventDefault()
          document.getElementById(error.id)?.focus()
        })
        item.append(link)
        document.getElementById(error.id)?.setAttribute("aria-invalid", "true")
      } else {
        item.textContent = error.label
      }
      list.append(item)
    }
    summary.append(list)
    summary.hidden = false
    summary.focus()
  }

  /** 对应 vanilla _submitGeneration。 */
  async function submitGeneration() {
    const pid = projectId.value
    clearGenerationErrors()
    const authorIntent = document.getElementById("story-outline-author-intent")?.value?.trim() || ""
    const plannedScale = document.getElementById("story-outline-planned-scale")?.value?.trim() || ""
    const coverage = document.getElementById("story-outline-coverage")?.value?.trim() || ""
    const errors = []
    for (const [id, label, value] of [
      ["story-outline-author-intent", "你想写一个怎样的故事", authorIntent],
      ["story-outline-planned-scale", "预计篇幅", plannedScale],
      ["story-outline-coverage", "这次先规划到哪里", coverage],
    ]) {
      if (value) continue
      errors.push({ id, label })
      const error = document.getElementById(`${id}-error`)
      if (error) {
        error.textContent = "这项需要填写。"
        error.hidden = false
      }
    }

    const selectedCharacterIds = [...document.querySelectorAll('input[name="story-outline-character"]:checked')]
      .map((input) => input.value)
    const selectedEntityIds = [...document.querySelectorAll('input[name="story-outline-entity"]:checked')]
      .map((input) => input.value)
    if (selectedCharacterIds.length > 12) errors.push({ id: "story-outline-character-fieldset", label: "人物最多选择 12 项" })
    if (selectedEntityIds.length > 24) errors.push({ id: "story-outline-entity-fieldset", label: "地点、物品与其他设定最多选择 24 项" })
    if (errors.length) {
      if (errors.some((error) => error.id?.includes("fieldset"))) {
        document.querySelector(".story-outline-generate__references")?.setAttribute("open", "")
      }
      showGenerationErrors(errors)
      return false
    }

    const includeCurrent = Boolean(document.getElementById("story-outline-include-current")?.checked)
    const baseRevisionId = current.value?.current_revision_id || null
    const submitButton = document.querySelector("#modal-footer .btn-primary")
    const submitLabel = submitButton?.textContent || "开始生成预览"
    if (submitButton) submitButton.textContent = "正在开始…"
    let operationId = null
    try {
      const applyKey = idempotencyKey()
      operationId = createOperationId()
      const meta = {
        project_id: pid,
        novel_id: pid,
        action: "outline.story_outline.generate",
        apply_base_revision_id: baseRevisionId,
        apply_idempotency_key: applyKey,
      }
      taskManager.prepare(operationId, meta, pid)
      const response = await api.outline.generateStoryOutline({
        novel_id: pid,
        author_intent: authorIntent,
        planned_scale: plannedScale,
        coverage,
        selected_character_ids: selectedCharacterIds,
        selected_entity_ids: selectedEntityIds,
        include_current_outline: includeCurrent,
        operation_id: operationId,
      })
      if (!response?.task_id) throw new Error("故事总览生成未能开始，请稍后重试")
      clearActiveWorkflow(operationId)

      if (preview.value) {
        clearPreviewDraft()
        preview.value = null
        applyError.value = null
        previewConflict.value = false
      }
      if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
        taskManager.adopt(response, meta, pid, { attach: false })
        return true
      }
      taskManager.adopt(response, meta, pid)
      closeModal()
      toast("已开始生成故事总览", "success")
      return true
    } catch (err) {
      if (operationId) clearActiveWorkflow(operationId)
      const message = err.message || "提交生成任务失败，请检查网络后重试。"
      showGenerationErrors([{ id: null, label: message }])
      toast(message, "error")
      return false
    } finally {
      if (submitButton?.isConnected) submitButton.textContent = submitLabel
    }
  }

  /** 对应 vanilla _applyPreview。 */
  async function applyPreview() {
    if (!preview.value || applying.value || previewConflict.value) return false
    const pid = preview.value.projectId
    if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
      applyError.value = "项目已切换，请回到原项目后重新加载总纲。"
      await focusApplyError()
      return false
    }

    let content
    try {
      content = validateStoryOutlineContent(editableStoryOutlineContent(preview.value.content))
    } catch (err) {
      applyError.value = err.message || "请补全必填内容后再采用。"
      await focusApplyError()
      return false
    }

    try {
      const attemptFingerprint = JSON.stringify({
        task_id: preview.value.taskId,
        base_revision_id: preview.value.baseRevisionId,
        content,
      })
      if (preview.value.lastApplyFingerprint && preview.value.lastApplyFingerprint !== attemptFingerprint) {
        preview.value.idempotencyKey = idempotencyKey()
      }
      preview.value.lastApplyFingerprint = attemptFingerprint
      persistPreviewDraft()
      applying.value = true
      applyError.value = null
      const taskId = preview.value.taskId
      const response = await api.outline.applyStoryOutlinePreview({
        novel_id: pid,
        source_task_id: taskId,
        ...content,
        base_revision_id: preview.value.baseRevisionId,
        idempotency_key: preview.value.idempotencyKey,
        confirmed: true,
      })
      clearActiveWorkflow(taskId)
      clearPreviewDraft()
      if (disposed || getAppState()?.currentProjectId !== pid || projectId.value !== pid) return response
      taskManager.state.taskId = null
      taskManager.state.meta = null
      taskManager.state.progress = null
      taskManager.stop()
      preview.value = null
      applyError.value = null
      toast(`故事总览已采用为新版本 v${response?.version_number || ""}`, "success")
      await reload()
      return response
    } catch (err) {
      const message = err?.status === 409
        ? "当前故事总览刚刚被其他会话更新。本机修改没有丢失，请先同步最新版本。"
        : err.message || "采用故事总览失败"
      previewConflict.value = err?.status === 409
      applyError.value = message
      persistPreviewDraft()
      await focusApplyError()
      toast(message, "error")
      return false
    } finally {
      applying.value = false
    }
  }

  async function focusApplyError() {
    await nextTick()
    document.getElementById("story-outline-apply-error")?.focus()
  }

  async function rebasePreview() {
    if (rebasingPreview.value || !preview.value) return false
    rebasingPreview.value = true
    try {
      const succeeded = await reload()
      if (!succeeded) return false
      previewConflict.value = false
      applyError.value = null
      persistPreviewDraft()
      toast("已同步最新版本，本机修改保持不变", "success")
      return true
    } finally {
      rebasingPreview.value = false
    }
  }

  /** 对应 vanilla _discardPreview。 */
  async function discardPreview() {
    if (!preview.value) return
    const confirmed = await confirmAsync(
      "确认放弃这份尚未采用的故事总览建议？",
      "放弃建议",
    )
    if (!confirmed) return
    clearActiveWorkflow(preview.value.taskId)
    taskManager.state.taskId = null
    taskManager.state.meta = null
    taskManager.state.progress = null
    clearPreviewDraft()
    preview.value = null
    applyError.value = null
    previewConflict.value = false
  }

  /** 对应 vanilla _cancelTask。 */
  async function cancelTask() {
    const confirmed = await confirmAsync(
      "确认取消当前故事总览生成？未采用的预览不会写入。",
      "确认取消",
    )
    if (!confirmed) return false
    return taskManager.cancel(projectId.value)
  }

  /** 对应 vanilla _dismissTask。 */
  function dismissTask() {
    taskManager.dismiss()
  }

  /** 对应 vanilla _viewRevision。 */
  async function viewRevision(revisionId) {
    if (!revisionId) return
    const pid = projectId.value
    try {
      const revision = await api.outline.getStoryOutlineRevision(revisionId, pid)
      if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) return
      showModalHtml(
        `故事总览历史版本 v${revision.version_number}`,
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
      "确认采用该历史内容？系统会创建一个新版本，不会改写原有历史。",
      "采用为新版本",
    )
    if (!confirmed) return false
    if (getAppState()?.currentProjectId !== pid || projectId.value !== pid) {
      toast("项目已切换，请在当前项目重新选择历史版本", "warning")
      return false
    }
    try {
      const key = restoreKeys.get(revisionId) || idempotencyKey()
      restoreKeys.set(revisionId, key)
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
    storyOutlineTaskManager.state.taskNotice = null
    const pid = projectId.value
    const previewTaskId = preview.value?.taskId || null
    if (previewTaskId) persistPreviewDraft()
    api.clearCache?.()
    const next = await loadStoryOutlineProps(pid, { recoverTask: false })
    if (projectId.value !== pid || getAppState()?.currentProjectId !== pid) return false
    if (previewTaskId && next.loadError) {
      applyError.value = `同步最新版本失败：${next.loadError}`
      await focusApplyError()
      return false
    }
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
        let nextIdempotencyKey
        try {
          nextIdempotencyKey = idempotencyKey()
        } catch (err) {
          applyError.value = err.message || "无法安全刷新预览，请更换浏览器后重试。"
          return false
        }
        preview.value.baseRevisionId = nextBaseRevisionId
        preview.value.idempotencyKey = nextIdempotencyKey
        preview.value.lastApplyFingerprint = null
      }
      previewConflict.value = false
      applyError.value = null
      persistPreviewDraft()
    }
    return true
  }

  // ---- 纯渲染辅助（模态框 HTML 生成） ----

  function _h(val) {
    return typeof esc === "function" ? esc(val) : String(val ?? "")
  }

  // ponytail: plain-text reading view strips headings only; add a renderer if richer Markdown display becomes necessary.
  function readableOutline(value) {
    return String(value ?? "").replace(/^#{1,6}[ \t]+/gmu, "").trim()
  }

  function renderContentReadOnly(content) {
    const core = content?.creative_core || {}
    const storylineHtml = (content?.major_storylines || []).map((item, index) => `
      <li class="story-outline-entry">
        <div class="story-outline-entry__title"><span aria-hidden="true">${index + 1}</span><h5>${_h(item.name)}</h5></div>
        <dl class="story-outline-entry__details">
          <div><dt>作用</dt><dd>${_h(item.narrative_function)}</dd></div>
          <div><dt>发展轨迹</dt><dd>${_h(item.trajectory)}</dd></div>
          <div><dt>交汇点</dt><dd>${_h((item.intersections || []).join("、") || "暂无")}</dd></div>
          <div><dt>收束方向</dt><dd>${_h(item.resolution_direction)}</dd></div>
        </dl>
      </li>
    `).join("")
    const movementHtml = (content?.macro_movements || []).map((item, index) => `
      <li class="story-outline-entry">
        <div class="story-outline-entry__title"><span aria-hidden="true">${index + 1}</span><h5>${_h(item.name)}</h5></div>
        <p class="story-outline-entry__lead">${_h(item.story_state_change)}</p>
        <p class="story-outline-entry__meta"><strong>推进剧情线</strong>${_h((item.advanced_storylines || []).join("、") || "暂无")}</p>
      </li>
    `).join("")
    const decisionHtml = (content?.open_decisions || []).map((item, index) => `
      <li class="story-outline-entry">
        <div class="story-outline-entry__title"><span aria-hidden="true">${index + 1}</span><h5>${_h(item.question)}</h5></div>
        <p class="story-outline-entry__lead">${_h(item.why_it_matters)}</p>
        <p class="story-outline-entry__meta"><strong>可选方向</strong>${_h((item.options || []).join("、") || "暂无")}</p>
      </li>
    `).join("")
    return `
      <article class="story-outline-document story-outline-document--modal">
        <header class="story-outline-document__header"><h3>${_h(content?.title)}</h3></header>
        <section class="story-outline-document__section">
          <h4>故事核心</h4>
          <dl class="story-outline-core">
            <div><dt>核心前提</dt><dd>${_h(core.premise)}</dd></div>
            <div><dt>基调与读者承诺</dt><dd>${_h(core.tone_and_reader_promise)}</dd></div>
            <div><dt>故事引擎</dt><dd>${_h(core.story_engine)}</dd></div>
            <div><dt>结局方向</dt><dd>${_h(core.ending_direction || "待决定")}</dd></div>
          </dl>
        </section>
        <section class="story-outline-document__section"><h4>总览正文</h4><p class="story-outline-document__prose">${_h(readableOutline(content?.outline_markdown))}</p></section>
        <section class="story-outline-document__section"><h4>主要剧情线</h4>${storylineHtml ? `<ol class="story-outline-entry-list">${storylineHtml}</ol>` : '<p class="form-hint">还没有主要剧情线。</p>'}</section>
        <section class="story-outline-document__section"><h4>故事推进</h4>${movementHtml ? `<ol class="story-outline-entry-list">${movementHtml}</ol>` : '<p class="form-hint">还没有故事推进。</p>'}</section>
        <section class="story-outline-document__section"><h4>待决定问题</h4>${decisionHtml ? `<ol class="story-outline-entry-list">${decisionHtml}</ol>` : '<p class="form-hint">目前没有待决定问题。</p>'}</section>
      </article>
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
    applying,
    previewConflict,
    rebasingPreview,
    previewRestored,
    previewStorageError,
    previewSaveState,
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
    rebasePreview,
    discardPreview,
    cancelTask,
    dismissTask,
    viewRevision,
    restoreRevision,
    reload,
    // 渲染辅助
    readableOutline,
    renderContentReadOnly,
  }
}
