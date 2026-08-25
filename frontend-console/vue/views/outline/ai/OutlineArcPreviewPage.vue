<template>
  <section class="outline-thread-review outline-arc-review" aria-labelledby="outline-arc-review-title">
    <div v-if="!preview" class="outline-thread-review__loading" :role="progress?.failed || !progress ? 'alert' : 'status'">
      <h2>{{ progress?.failed || !progress ? "这份建议暂时无法打开" : "正在恢复篇章建议" }}</h2>
      <p>{{ progress?.failed || !progress ? (progress?.errorMessage || "没有找到可恢复的篇章建议，请返回后重新生成。") : "正在读取原任务和本机暂存的修改…" }}</p>
      <button type="button" class="btn" data-action="close-outline-generate-preview" @click="closeReview">返回篇章</button>
    </div>

    <template v-else-if="draft">
      <header class="outline-thread-review__header">
        <div>
          <span class="outline-thread-review__eyebrow">AI 未采用建议</span>
          <h2 id="outline-arc-review-title">检查篇章建议</h2>
          <p>先核对每个篇章的目标、冲突和关键转折。只有点击“采用到篇章”后，才会写入作品结构。</p>
        </div>
        <p class="outline-thread-review__save-state" role="status" aria-live="polite">{{ saveState }}</p>
      </header>

      <div v-if="restored" class="story-outline-editor-notice">
        <div><strong>已恢复本机修改</strong><p>这是你上次离开前尚未采用的内容。</p></div>
      </div>
      <div v-if="storageError" class="story-outline-editor-notice story-outline-editor-notice--warning" role="alert">
        <div><strong>本机暂存不可用</strong><p>{{ storageError }}</p></div>
      </div>
      <div v-if="applyError || conflict" class="story-outline-editor-notice story-outline-editor-notice--warning" role="alert">
        <div>
          <strong>{{ conflict ? "作品结构已变化" : "采用失败" }}</strong>
          <p>{{ conflict ? "你的修改仍保留在本机。这份旧建议已不能直接采用，请返回篇章后重新生成。" : `${applyError?.message || "采用失败"}。你的修改仍保留，可以稍后重试。` }}</p>
        </div>
        <button v-if="conflict" type="button" class="btn btn-sm" @click="closeReview">返回并重新生成</button>
      </div>

      <section v-if="storyConflict" class="outline-thread-review__notice outline-thread-review__notice--warning" role="note">
        <h3>这份建议与故事总览有冲突</h3>
        <p><strong>你想改变：</strong>{{ storyConflict.requested_change }}</p>
        <p><strong>冲突位置：</strong>{{ storyConflict.conflict_with_outline }}</p>
        <p><strong>建议先处理：</strong>{{ storyConflict.suggested_story_outline_revision }}</p>
      </section>

      <section v-if="warnings.length" class="outline-thread-review__notice" aria-labelledby="outline-arc-warning-title">
        <h3 id="outline-arc-warning-title">采用前请留意</h3>
        <ul><li v-for="warning in warnings" :key="warning">{{ warning }}</li></ul>
      </section>

      <details v-if="overlaps.length" class="outline-thread-review__support">
        <summary>查看可能重叠的现有篇章</summary>
        <div class="outline-thread-review__support-body">
          <ul><li v-for="(item, index) in overlaps" :key="index">{{ item.name || item.title || "一项现有篇章" }}</li></ul>
        </div>
      </details>

      <details v-if="authorDecisions.length" class="outline-thread-review__support">
        <summary>还有 {{ authorDecisions.length }} 个问题需要你判断</summary>
        <ol class="outline-thread-review__decision-list">
          <li v-for="(decision, index) in authorDecisions" :key="index">
            <strong>{{ decision.question }}</strong>
            <p>{{ decision.why_it_matters }}</p>
            <p v-if="decision.options?.length" class="form-hint">可考虑：{{ decision.options.join("、") }}</p>
          </li>
        </ol>
      </details>

      <form class="outline-thread-review__form" novalidate @submit.prevent="apply">
        <div v-if="validationErrors.length" ref="errorSummary" class="story-outline-generate__error-summary" role="alert" tabindex="-1" aria-labelledby="outline-arc-error-title">
          <strong id="outline-arc-error-title">请先修正以下内容</strong>
          <ul>
            <li v-for="item in validationErrors" :key="item.id"><a :href="`#${item.id}`" @click.prevent="focusField(item.id)">{{ item.message }}</a></li>
          </ul>
        </div>

        <div class="outline-thread-review__section-heading">
          <div><h3>篇章设计</h3><p>先确定这一段故事要抵达哪里，再检查关键转折是否成立。</p></div>
          <button type="button" class="btn btn-sm" data-action="add-outline-preview-arc" @click="addArc">新增篇章</button>
        </div>

        <article v-for="(arc, arcIndex) in draft.arcs" :key="arc.proposal_ref || arcIndex" class="outline-thread-editor">
          <header class="outline-thread-editor__header">
            <div><span>篇章 {{ arcIndex + 1 }}</span><strong>{{ arc.title || "未命名篇章" }}</strong></div>
            <div class="outline-thread-editor__item-actions">
              <button type="button" class="btn btn-sm btn-ghost" :disabled="arcIndex === 0" :aria-label="`上移篇章 ${arcIndex + 1}`" @click="moveArc(arcIndex, -1)">上移</button>
              <button type="button" class="btn btn-sm btn-ghost" :disabled="arcIndex === draft.arcs.length - 1" :aria-label="`下移篇章 ${arcIndex + 1}`" @click="moveArc(arcIndex, 1)">下移</button>
              <button type="button" class="btn btn-sm btn-ghost" :aria-label="`移除篇章 ${arcIndex + 1}`" @click="draft.arcs.splice(arcIndex, 1)">移除</button>
            </div>
          </header>

          <div class="outline-thread-editor__grid">
            <div class="form-group">
              <label :for="fieldId(arcIndex, 'title')">篇章名称</label>
              <input :id="fieldId(arcIndex, 'title')" v-model="arc.title" class="form-input" maxlength="255" :aria-invalid="Boolean(fieldError(fieldId(arcIndex, 'title')))" :aria-describedby="errorId(arcIndex, 'title')" />
              <p v-if="fieldError(fieldId(arcIndex, 'title'))" :id="errorId(arcIndex, 'title')" class="form-error">{{ fieldError(fieldId(arcIndex, 'title')) }}</p>
            </div>
            <div class="form-group">
              <label :for="fieldId(arcIndex, 'index')">篇章顺序</label>
              <input :id="fieldId(arcIndex, 'index')" v-model="arc.arc_index" class="form-input" type="number" min="1" inputmode="numeric" :aria-invalid="Boolean(fieldError(fieldId(arcIndex, 'index')))" :aria-describedby="errorId(arcIndex, 'index')" />
              <p v-if="fieldError(fieldId(arcIndex, 'index'))" :id="errorId(arcIndex, 'index')" class="form-error">{{ fieldError(fieldId(arcIndex, 'index')) }}</p>
            </div>
          </div>

          <div class="outline-thread-editor__grid">
            <div class="form-group"><label :for="fieldId(arcIndex, 'start')">起始章节</label><input :id="fieldId(arcIndex, 'start')" v-model="arc.start_chapter" class="form-input" type="number" min="1" inputmode="numeric" :aria-invalid="Boolean(fieldError(fieldId(arcIndex, 'start')))" :aria-describedby="errorId(arcIndex, 'start')" /><p v-if="fieldError(fieldId(arcIndex, 'start'))" :id="errorId(arcIndex, 'start')" class="form-error">{{ fieldError(fieldId(arcIndex, 'start')) }}</p></div>
            <div class="form-group"><label :for="fieldId(arcIndex, 'end')">结束章节</label><input :id="fieldId(arcIndex, 'end')" v-model="arc.end_chapter" class="form-input" type="number" min="1" inputmode="numeric" :aria-invalid="Boolean(fieldError(fieldId(arcIndex, 'end')))" :aria-describedby="errorId(arcIndex, 'end')" /><p v-if="fieldError(fieldId(arcIndex, 'end'))" :id="errorId(arcIndex, 'end')" class="form-error">{{ fieldError(fieldId(arcIndex, 'end')) }}</p></div>
          </div>

          <div class="outline-thread-editor__grid">
            <div class="form-group"><label :for="fieldId(arcIndex, 'goal')">篇章目标</label><textarea :id="fieldId(arcIndex, 'goal')" v-model="arc.arc_goal" class="form-textarea" rows="4" maxlength="4000" placeholder="这一篇结束时，故事必须抵达什么状态？"></textarea></div>
            <div class="form-group"><label :for="fieldId(arcIndex, 'conflict')">核心冲突</label><textarea :id="fieldId(arcIndex, 'conflict')" v-model="arc.core_conflict" class="form-textarea" rows="4" maxlength="4000" placeholder="谁或什么阻止目标实现？代价是什么？"></textarea></div>
          </div>

          <div class="form-group"><label :for="fieldId(arcIndex, 'opposition')">主要对抗力量</label><textarea :id="fieldId(arcIndex, 'opposition')" v-model="arc.main_opposition" class="form-textarea" rows="3" maxlength="4000" placeholder="具体的人、势力、环境或内在阻力"></textarea></div>

          <details class="outline-thread-editor__support" open>
            <summary>关键转折</summary>
            <div class="outline-thread-editor__support-body">
              <div class="outline-thread-editor__grid">
                <div class="form-group"><label :for="fieldId(arcIndex, 'entry')">开篇钩子</label><textarea :id="fieldId(arcIndex, 'entry')" v-model="arc.entry_hook" class="form-textarea" rows="3" maxlength="4000" placeholder="用什么变化把读者带入这一篇？"></textarea></div>
                <div class="form-group"><label :for="fieldId(arcIndex, 'midpoint')">中段转折</label><textarea :id="fieldId(arcIndex, 'midpoint')" v-model="arc.midpoint_turn" class="form-textarea" rows="3" maxlength="4000" placeholder="什么发现或选择改变了局势？"></textarea></div>
              </div>
              <div class="outline-thread-editor__grid">
                <div class="form-group"><label :for="fieldId(arcIndex, 'climax')">高潮抉择</label><textarea :id="fieldId(arcIndex, 'climax')" v-model="arc.climax" class="form-textarea" rows="3" maxlength="4000" placeholder="冲突如何被推到无法回避的选择？"></textarea></div>
                <div class="form-group"><label :for="fieldId(arcIndex, 'result')">篇末状态</label><textarea :id="fieldId(arcIndex, 'result')" v-model="arc.result_state" class="form-textarea" rows="3" maxlength="4000" placeholder="人物、关系或世界发生了什么不可逆变化？"></textarea></div>
              </div>
              <div class="form-group"><label :for="fieldId(arcIndex, 'next')">下一篇的牵引</label><textarea :id="fieldId(arcIndex, 'next')" v-model="arc.next_hook" class="form-textarea" rows="3" maxlength="4000" placeholder="留下什么新问题，让故事自然进入下一篇？"></textarea></div>
            </div>
          </details>

          <details class="outline-thread-editor__support">
            <summary>创作依据</summary>
            <div class="outline-thread-editor__support-body">
              <div class="form-group">
                <label :for="fieldId(arcIndex, 'basis')">为什么这样规划</label>
                <textarea :id="fieldId(arcIndex, 'basis')" v-model="arc.basis" class="form-textarea" rows="3" maxlength="4000" :aria-invalid="Boolean(fieldError(fieldId(arcIndex, 'basis')))" :aria-describedby="errorId(arcIndex, 'basis')"></textarea>
                <p v-if="fieldError(fieldId(arcIndex, 'basis'))" :id="errorId(arcIndex, 'basis')" class="form-error">{{ fieldError(fieldId(arcIndex, 'basis')) }}</p>
              </div>
              <p v-if="needsCheck(arc)" class="outline-thread-editor__check-note">AI 对部分信息没有把握，请重点核对留空或仍不确定的内容。</p>
            </div>
          </details>
        </article>

        <div v-if="!draft.arcs.length" class="outline-thread-editor__empty outline-thread-editor__empty--large">
          <p>这份建议目前没有篇章。你可以新增一篇，或放弃这份建议。</p>
          <button type="button" class="btn" @click="addArc">新增第一篇</button>
        </div>

        <footer class="outline-thread-review__actions">
          <div>
            <button type="button" class="btn btn-ghost" data-action="discard-outline-generate-preview" :disabled="applying" @click="discard">放弃这份建议</button>
            <button type="button" class="btn" :disabled="applying" @click="restoreOriginal">恢复 AI 原稿</button>
          </div>
          <button type="submit" class="btn btn-primary" data-action="apply-outline-generate-preview" :disabled="applying || conflict">{{ applying ? "采用中…" : "采用到篇章" }}</button>
        </footer>
      </form>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import { getConfirmAction, getRouter, getToast } from "../../../bridge/index.js"
import { applyOutlineGeneratePreview } from "./outlineAiOps.js"
import {
  clearOutlineGenerateWorkflowsForTarget,
  outlineGenerateManager,
  resetOutlineGenerateState,
} from "./outlineWorkflowManagers.js"

const props = defineProps({ projectId: { type: String, required: true } })
const manager = outlineGenerateManager
const router = getRouter()
const toast = getToast()
const confirmAction = getConfirmAction()

const preview = computed(() => (
  manager.state.ownerProjectId === props.projectId
  && manager.state.preview?.target === "outline_arc"
) ? manager.state.preview : null)
const progress = computed(() => manager.state.ownerProjectId === props.projectId ? manager.state.progress : null)
const warnings = computed(() => preview.value?.warnings || [])
const overlaps = computed(() => preview.value?.overlap?.outline_arcs || [])
const storyConflict = computed(() => draft.value?.story_outline_conflict || null)
const authorDecisions = computed(() => draft.value?.author_decisions || [])
const applyError = computed(() => manager.state.applyError || null)
const previewConflict = ref(false)
const conflict = computed(() => previewConflict.value || applyError.value?.status === 409)

const draft = ref(null)
const originalDraft = ref(null)
const restored = ref(false)
const savedAt = ref(null)
const storageError = ref("")
const applying = ref(false)
const validationErrors = ref([])
const errorSummary = ref(null)
let currentTaskId = null
let currentProjectId = null
let saveTimer = null
let initializing = false
let localRefCounter = 0

const clone = (value) => JSON.parse(JSON.stringify(value))
const storageKey = (projectId, taskId) => `novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
const fieldId = (arcIndex, field) => `outline-arc-preview-${arcIndex}-${field}`
const errorId = (arcIndex, field) => `${fieldId(arcIndex, field)}-error`
const fieldError = (id) => validationErrors.value.find((item) => item.id === id)?.message || ""

const saveState = computed(() => {
  if (applying.value) return "正在采用…"
  if (storageError.value) return "本机暂存不可用"
  if (!savedAt.value) return "修改后会自动暂存在本机"
  const date = new Date(savedAt.value)
  return Number.isNaN(date.getTime()) ? "修改已暂存在本机" : `修改已暂存在本机 · ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
})

watch([() => props.projectId, () => preview.value?.sourceTaskId], initializeDraft, { immediate: true })
watch(draft, () => {
  if (initializing || !draft.value || !currentTaskId) return
  validationErrors.value = []
  if (!conflict.value) manager.state.applyError = null
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveDraft, 250)
}, { deep: true })
watch(applyError, (error) => {
  if (error?.status !== 409) return
  previewConflict.value = true
  saveDraft()
})

useLeaveGuard(() => {
  saveDraft()
  if (!applying.value) return true
  toast("正在采用篇章，请稍候", "info")
  return false
})

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", saveDraft)
  clearTimeout(saveTimer)
  saveDraft()
})
onMounted(() => window.addEventListener("beforeunload", saveDraft))

function initializeDraft() {
  saveDraft()
  clearTimeout(saveTimer)
  currentProjectId = props.projectId
  currentTaskId = preview.value?.sourceTaskId || null
  validationErrors.value = []
  manager.state.applyError = null
  previewConflict.value = false
  if (!preview.value || !currentTaskId) {
    draft.value = null
    originalDraft.value = null
    restored.value = false
    return
  }
  originalDraft.value = clone(preview.value.draftStructure)
  let saved = null
  try {
    saved = JSON.parse(localStorage.getItem(storageKey(props.projectId, currentTaskId)) || "null")
    if (
      saved?.project_id !== props.projectId
      || saved?.source_task_id !== currentTaskId
      || saved?.target !== "outline_arc"
      || !saved?.draft_structure
      || !Array.isArray(saved.draft_structure.arcs)
    ) saved = null
  } catch {
    saved = null
  }
  initializing = true
  draft.value = clone(saved?.draft_structure || originalDraft.value)
  restored.value = Boolean(saved)
  previewConflict.value = saved?.conflict === true
  savedAt.value = saved?.saved_at || null
  storageError.value = ""
  void nextTick(() => { initializing = false })
}

function saveDraft() {
  if (!draft.value || !currentProjectId || !currentTaskId) return
  try {
    const saved = new Date().toISOString()
    localStorage.setItem(storageKey(currentProjectId, currentTaskId), JSON.stringify({
      version: 1,
      project_id: currentProjectId,
      source_task_id: currentTaskId,
      target: "outline_arc",
      conflict: conflict.value,
      saved_at: saved,
      draft_structure: draft.value,
    }))
    savedAt.value = saved
    storageError.value = ""
  } catch {
    storageError.value = "浏览器未能保存这次修改；离开本页前请先采用，或稍后重试。"
  }
}

function clearDraft() {
  if (!currentProjectId || !currentTaskId) return
  try { localStorage.removeItem(storageKey(currentProjectId, currentTaskId)) } catch {}
  savedAt.value = null
  restored.value = false
}

function closeReview(shouldSave = true) {
  if (shouldSave) saveDraft()
  const query = new URLSearchParams(router?.getCurrentQuery?.()?.toString() || "")
  query.delete("review")
  router?.replace?.("outline", "arcs", query)
}

function localRef() {
  localRefCounter += 1
  const uuid = globalThis.crypto?.randomUUID?.()
  return `author-arc-${uuid || `${Date.now().toString(36)}-${localRefCounter}`}`.slice(0, 64)
}

function addArc() {
  draft.value.result = "proposed"
  draft.value.arcs.push({
    proposal_ref: localRef(), target_arc_ref: null, title: "", arc_index: draft.value.arcs.length + 1,
    start_chapter: null, end_chapter: null, arc_goal: null, core_conflict: null,
    main_opposition: null, entry_hook: null, midpoint_turn: null, climax: null,
    result_state: null, next_hook: null, related_thread_refs: [], related_character_refs: [],
    related_entity_refs: [], basis: "作者在采用前新增这篇。", uncertain_fields: [], confidence: 1,
  })
  void nextTick(() => document.getElementById(fieldId(draft.value.arcs.length - 1, "title"))?.focus())
}

function moveArc(index, offset) {
  const target = index + offset
  if (target < 0 || target >= draft.value.arcs.length) return
  const [arc] = draft.value.arcs.splice(index, 1)
  draft.value.arcs.splice(target, 0, arc)
  draft.value.arcs.forEach((item, itemIndex) => { item.arc_index = itemIndex + 1 })
}

function needsCheck(arc) {
  return Boolean(arc?.uncertain_fields?.length || (typeof arc?.confidence === "number" && arc.confidence < 0.7))
}

function validateDraft() {
  const errors = []
  const required = (id, value, message, max = 4000) => {
    const text = String(value || "").trim()
    if (!text) errors.push({ id, message })
    else if (text.length > max) errors.push({ id, message: `${message.replace(/^请填写/, "")}不能超过 ${max} 字` })
  }
  const positive = (id, value, label) => {
    if (value === "" || value == null) return null
    const number = Number(value)
    if (!Number.isInteger(number) || number < 1) errors.push({ id, message: `${label}必须是正整数` })
    return number
  }
  if (!Array.isArray(draft.value?.arcs)) errors.push({ id: "outline-arc-error-title", message: "篇章建议格式不完整" })
  for (const [arcIndex, arc] of (draft.value?.arcs || []).entries()) {
    required(fieldId(arcIndex, "title"), arc.title, `请填写篇章 ${arcIndex + 1} 的名称`, 255)
    required(fieldId(arcIndex, "basis"), arc.basis, `请填写篇章 ${arcIndex + 1} 的创作依据`)
    positive(fieldId(arcIndex, "index"), arc.arc_index, `篇章 ${arcIndex + 1} 的顺序`)
    const start = positive(fieldId(arcIndex, "start"), arc.start_chapter, `篇章 ${arcIndex + 1} 的起始章节`)
    const end = positive(fieldId(arcIndex, "end"), arc.end_chapter, `篇章 ${arcIndex + 1} 的结束章节`)
    if (start && end && end < start) errors.push({ id: fieldId(arcIndex, "end"), message: `篇章 ${arcIndex + 1} 的结束章节不能早于起始章节` })
  }
  validationErrors.value = errors
  if (errors.length) void nextTick(() => errorSummary.value?.focus())
  return errors.length === 0
}

function normalizeDraft() {
  const normalized = clone(draft.value)
  const optionalNumber = (value) => value === "" || value == null ? null : Number(value)
  const optionalText = (value) => String(value || "").trim() || null
  for (const arc of normalized.arcs) {
    arc.title = String(arc.title || "").trim()
    arc.basis = String(arc.basis || "").trim()
    for (const field of ["arc_index", "start_chapter", "end_chapter"]) arc[field] = optionalNumber(arc[field])
    for (const field of ["arc_goal", "core_conflict", "main_opposition", "entry_hook", "midpoint_turn", "climax", "result_state", "next_hook"]) arc[field] = optionalText(arc[field])
  }
  return normalized
}

async function apply() {
  if (applying.value || conflict.value || !validateDraft()) return
  saveDraft()
  applying.value = true
  try {
    const result = await applyOutlineGeneratePreview(normalizeDraft())
    if (result && result !== true) {
      clearDraft()
      currentProjectId = null
      currentTaskId = null
      draft.value = null
      resetOutlineGenerateState()
      applying.value = false
      const query = new URLSearchParams(router?.getCurrentQuery?.()?.toString() || "")
      query.delete("review")
      await router?.replace?.("outline", "arcs", query)
    }
  } finally {
    applying.value = false
  }
}

function restoreOriginal() {
  confirmAction("恢复 AI 最初给出的篇章建议？当前本机修改会被替换。", () => {
    initializing = true
    draft.value = clone(originalDraft.value)
    clearDraft()
    manager.state.applyError = null
    void nextTick(() => {
      initializing = false
      saveDraft()
    })
  }, "恢复 AI 原稿")
}

function discard() {
  confirmAction("放弃这份篇章建议？本机暂存的修改也会一并清除。", () => {
    clearDraft()
    currentProjectId = null
    currentTaskId = null
    draft.value = null
    clearOutlineGenerateWorkflowsForTarget("outline_arc")
    resetOutlineGenerateState()
    closeReview(false)
  }, "放弃建议")
}

function focusField(id) {
  document.getElementById(id)?.focus()
}
</script>
