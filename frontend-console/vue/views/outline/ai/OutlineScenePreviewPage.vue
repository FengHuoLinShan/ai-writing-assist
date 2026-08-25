<template>
  <section class="outline-thread-review outline-scene-review" aria-labelledby="outline-scene-review-title">
    <div v-if="!preview" class="outline-thread-review__loading" :role="progress?.failed || !progress ? 'alert' : 'status'">
      <h2>{{ progress?.failed || !progress ? "这份建议暂时无法打开" : "正在恢复场景细纲" }}</h2>
      <p>{{ progress?.failed || !progress ? (progress?.errorMessage || "没有找到可恢复的场景建议，请返回后重新生成。") : "正在读取原任务和本机暂存的修改…" }}</p>
      <button type="button" class="btn" data-action="close-outline-generate-preview" @click="closeReview">返回场景</button>
    </div>

    <template v-else-if="draft">
      <header class="outline-thread-review__header">
        <div>
          <span class="outline-thread-review__eyebrow">AI 未采用建议</span>
          <h2 id="outline-scene-review-title">检查场景细纲</h2>
          <p>先核对场景目标、冲突和必须发生的事。只有点击“采用到场景”后，才会写入作品结构。</p>
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
          <p>{{ conflict ? "你的修改仍保留在本机。这份旧建议已不能直接采用，请返回场景后重新生成。" : `${applyError?.message || "采用失败"}。你的修改仍保留，可以稍后重试。` }}</p>
        </div>
        <button v-if="conflict" type="button" class="btn btn-sm" @click="closeReview">返回并重新生成</button>
      </div>

      <section v-if="storyConflict" class="outline-thread-review__notice outline-thread-review__notice--warning" role="note">
        <h3>这份建议与故事总览有冲突</h3>
        <p><strong>你想改变：</strong>{{ storyConflict.requested_change }}</p>
        <p><strong>冲突位置：</strong>{{ storyConflict.conflict_with_outline }}</p>
        <p><strong>建议先处理：</strong>{{ storyConflict.suggested_story_outline_revision }}</p>
      </section>

      <section v-if="warnings.length" class="outline-thread-review__notice" aria-labelledby="outline-scene-warning-title">
        <h3 id="outline-scene-warning-title">采用前请留意</h3>
        <ul><li v-for="warning in warnings" :key="warning">{{ warning }}</li></ul>
      </section>

      <details v-if="overlaps.length" class="outline-thread-review__support">
        <summary>查看可能重叠的现有场景</summary>
        <div class="outline-thread-review__support-body">
          <ul><li v-for="(item, index) in overlaps" :key="index">{{ item.name || item.title || "一项现有场景" }}</li></ul>
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
        <div v-if="validationErrors.length" ref="errorSummary" class="story-outline-generate__error-summary" role="alert" tabindex="-1" aria-labelledby="outline-scene-error-title">
          <strong id="outline-scene-error-title">请先修正以下内容</strong>
          <ul>
            <li v-for="item in validationErrors" :key="item.id"><a :href="`#${item.id}`" @click.prevent="focusField(item.id)">{{ item.message }}</a></li>
          </ul>
        </div>

        <div class="outline-thread-review__section-heading">
          <div><h3>场景设计</h3><p>先明确这一场要完成什么，再安排推进方式和叙事作用。</p></div>
          <button type="button" class="btn btn-sm" data-action="add-outline-preview-scene" @click="addScene">新增场景</button>
        </div>

        <article v-for="(scene, sceneIndex) in draft.scenes" :key="scene.proposal_ref || sceneIndex" class="outline-thread-editor">
          <header class="outline-thread-editor__header">
            <div><span>场景 {{ sceneIndex + 1 }}</span><strong>{{ scene.title || "未命名场景" }}</strong></div>
            <div class="outline-thread-editor__item-actions">
              <button type="button" class="btn btn-sm btn-ghost" :disabled="sceneIndex === 0" :aria-label="`上移场景 ${sceneIndex + 1}`" @click="moveScene(sceneIndex, -1)">上移</button>
              <button type="button" class="btn btn-sm btn-ghost" :disabled="sceneIndex === draft.scenes.length - 1" :aria-label="`下移场景 ${sceneIndex + 1}`" @click="moveScene(sceneIndex, 1)">下移</button>
              <button type="button" class="btn btn-sm btn-ghost" :aria-label="`移除场景 ${sceneIndex + 1}`" @click="draft.scenes.splice(sceneIndex, 1)">移除</button>
            </div>
          </header>

          <div class="form-group">
            <label :for="fieldId(sceneIndex, 'title')">场景名称</label>
            <input :id="fieldId(sceneIndex, 'title')" v-model="scene.title" class="form-input" maxlength="255" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'title')))" :aria-describedby="errorId(sceneIndex, 'title')" />
            <p v-if="fieldError(fieldId(sceneIndex, 'title'))" :id="errorId(sceneIndex, 'title')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'title')) }}</p>
          </div>

          <div class="outline-thread-editor__grid">
            <div class="form-group"><label :for="fieldId(sceneIndex, 'start')">预计起始章</label><input :id="fieldId(sceneIndex, 'start')" v-model="scene.planned_start_chapter" class="form-input" type="number" min="1" inputmode="numeric" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'start')))" :aria-describedby="errorId(sceneIndex, 'start')" /><p v-if="fieldError(fieldId(sceneIndex, 'start'))" :id="errorId(sceneIndex, 'start')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'start')) }}</p></div>
            <div class="form-group"><label :for="fieldId(sceneIndex, 'end')">预计结束章</label><input :id="fieldId(sceneIndex, 'end')" v-model="scene.planned_end_chapter" class="form-input" type="number" min="1" inputmode="numeric" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'end')))" :aria-describedby="errorId(sceneIndex, 'end')" /><p v-if="fieldError(fieldId(sceneIndex, 'end'))" :id="errorId(sceneIndex, 'end')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'end')) }}</p></div>
          </div>

          <div class="form-group"><label :for="fieldId(sceneIndex, 'goal')">场景目标</label><textarea :id="fieldId(sceneIndex, 'goal')" v-model="scene.goal" class="form-textarea" rows="3" maxlength="4000" placeholder="这一场结束时，人物或局势必须发生什么变化？"></textarea></div>

          <div class="outline-thread-editor__grid">
            <div class="form-group">
              <label :for="fieldId(sceneIndex, 'status')">冲突安排</label>
              <select :id="fieldId(sceneIndex, 'status')" v-model="scene.core_conflict_status" class="form-select" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'status')))" :aria-describedby="errorId(sceneIndex, 'status')">
                <option v-for="[value, label] in CONFLICT_OPTIONS" :key="value" :value="value">{{ label }}</option>
              </select>
              <p v-if="fieldError(fieldId(sceneIndex, 'status'))" :id="errorId(sceneIndex, 'status')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'status')) }}</p>
            </div>
            <div v-if="scene.core_conflict_status !== 'not_applicable'" class="form-group">
              <label :for="fieldId(sceneIndex, 'conflict')">核心冲突</label>
              <textarea :id="fieldId(sceneIndex, 'conflict')" v-model="scene.core_conflict" class="form-textarea" rows="3" maxlength="4000" placeholder="什么阻止目标实现？人物要付出什么代价？" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'conflict')))" :aria-describedby="errorId(sceneIndex, 'conflict')"></textarea>
              <p v-if="fieldError(fieldId(sceneIndex, 'conflict'))" :id="errorId(sceneIndex, 'conflict')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'conflict')) }}</p>
              <p v-else-if="scene.core_conflict_status === 'uncertain'" class="form-hint">这部分会保留为待作者确认。</p>
            </div>
            <div v-else class="form-group"><p class="form-hint">采用时不会为这一场写入核心冲突。</p></div>
          </div>

          <details class="outline-thread-editor__support" open>
            <summary>场景走向</summary>
            <div class="outline-thread-editor__support-body">
              <div class="form-group"><label :for="fieldId(sceneIndex, 'beat')">情绪节拍</label><textarea :id="fieldId(sceneIndex, 'beat')" v-model="scene.emotional_beat" class="form-textarea" rows="3" maxlength="4000" placeholder="人物或读者的情绪如何变化？"></textarea></div>
              <div class="outline-thread-editor__grid">
                <div class="form-group"><label :for="fieldId(sceneIndex, 'must')">必须发生</label><textarea :id="fieldId(sceneIndex, 'must')" v-model="scene.must_happen" class="form-textarea" rows="3" maxlength="4000" placeholder="这场不可缺少的动作、选择或信息"></textarea></div>
                <div class="form-group"><label :for="fieldId(sceneIndex, 'must-not')">不要发生</label><textarea :id="fieldId(sceneIndex, 'must-not')" v-model="scene.must_not_happen" class="form-textarea" rows="3" maxlength="4000" placeholder="避免提前揭晓、越界行动或破坏连续性的内容"></textarea></div>
              </div>
            </div>
          </details>

          <details class="outline-thread-editor__support">
            <summary>叙事作用</summary>
            <div class="outline-thread-editor__support-body">
              <div class="outline-thread-editor__grid">
                <div class="form-group">
                  <label :for="fieldId(sceneIndex, 'tag')">场景位置</label>
                  <select :id="fieldId(sceneIndex, 'tag')" v-model="scene.narrative_tag" class="form-select" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'tag')))" :aria-describedby="errorId(sceneIndex, 'tag')"><option v-for="[value, label] in NARRATIVE_OPTIONS" :key="value" :value="value">{{ label }}</option></select>
                  <p v-if="fieldError(fieldId(sceneIndex, 'tag'))" :id="errorId(sceneIndex, 'tag')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'tag')) }}</p>
                </div>
                <div class="form-group"><label :for="fieldId(sceneIndex, 'function')">叙事任务</label><textarea :id="fieldId(sceneIndex, 'function')" v-model="scene.narrative_function" class="form-textarea" rows="3" maxlength="4000" placeholder="这场在全书中承担什么作用？"></textarea></div>
              </div>
            </div>
          </details>

          <details class="outline-thread-editor__support">
            <summary>创作依据</summary>
            <div class="outline-thread-editor__support-body">
              <div class="form-group">
                <label :for="fieldId(sceneIndex, 'basis')">为什么这样安排</label>
                <textarea :id="fieldId(sceneIndex, 'basis')" v-model="scene.basis" class="form-textarea" rows="3" maxlength="4000" :aria-invalid="Boolean(fieldError(fieldId(sceneIndex, 'basis')))" :aria-describedby="errorId(sceneIndex, 'basis')"></textarea>
                <p v-if="fieldError(fieldId(sceneIndex, 'basis'))" :id="errorId(sceneIndex, 'basis')" class="form-error">{{ fieldError(fieldId(sceneIndex, 'basis')) }}</p>
              </div>
              <p v-if="needsCheck(scene)" class="outline-thread-editor__check-note">AI 对部分信息没有把握，请重点核对留空或仍不确定的内容。</p>
            </div>
          </details>
        </article>

        <div v-if="!draft.scenes.length" class="outline-thread-editor__empty outline-thread-editor__empty--large">
          <p>这份建议目前没有场景。你可以新增一场，或放弃这份建议。</p>
          <button type="button" class="btn" @click="addScene">新增第一场</button>
        </div>

        <footer class="outline-thread-review__actions">
          <div>
            <button type="button" class="btn btn-ghost" data-action="discard-outline-generate-preview" :disabled="applying" @click="discard">放弃这份建议</button>
            <button type="button" class="btn" :disabled="applying" @click="restoreOriginal">恢复 AI 原稿</button>
          </div>
          <button type="submit" class="btn btn-primary" data-action="apply-outline-generate-preview" :disabled="applying || conflict">{{ applying ? "采用中…" : "采用到场景" }}</button>
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

const CONFLICT_OPTIONS = [
  ["present", "有明确冲突"],
  ["not_applicable", "这一场不需要冲突"],
  ["uncertain", "还需要作者判断"],
]
const NARRATIVE_OPTIONS = [
  ["draft", "暂未标注"], ["hook", "钩子"], ["inciting_incident", "诱发事件"],
  ["rising_action", "推进"], ["climax", "高潮"], ["valley", "低谷"],
  ["transition", "过渡"], ["payoff", "兑现"],
]
const CONFLICT_VALUES = new Set(CONFLICT_OPTIONS.map(([value]) => value))
const NARRATIVE_VALUES = new Set(NARRATIVE_OPTIONS.map(([value]) => value))

const props = defineProps({ projectId: { type: String, required: true } })
const manager = outlineGenerateManager
const router = getRouter()
const toast = getToast()
const confirmAction = getConfirmAction()

const preview = computed(() => (
  manager.state.ownerProjectId === props.projectId
  && manager.state.preview?.target === "planned_scene"
) ? manager.state.preview : null)
const progress = computed(() => manager.state.ownerProjectId === props.projectId ? manager.state.progress : null)
const warnings = computed(() => preview.value?.warnings || [])
const overlaps = computed(() => preview.value?.overlap?.scenes || [])
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
const storageKey = (projectId, taskId) => `novel_outline_scene_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
const fieldId = (sceneIndex, field) => `outline-scene-preview-${sceneIndex}-${field}`
const errorId = (sceneIndex, field) => `${fieldId(sceneIndex, field)}-error`
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
  toast("正在采用场景，请稍候", "info")
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
      || saved?.target !== "planned_scene"
      || !saved?.draft_structure
      || !Array.isArray(saved.draft_structure.scenes)
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
      version: 1, project_id: currentProjectId, source_task_id: currentTaskId,
      target: "planned_scene", conflict: conflict.value, saved_at: saved, draft_structure: draft.value,
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
  router?.replace?.("outline", "scenes", query)
}

function localRef() {
  localRefCounter += 1
  const uuid = globalThis.crypto?.randomUUID?.()
  return `author-scene-${uuid || `${Date.now().toString(36)}-${localRefCounter}`}`.slice(0, 64)
}

function addScene() {
  draft.value.result = "proposed"
  draft.value.scenes.push({
    proposal_ref: localRef(), target_scene_ref: null, parent_arc_ref: null, title: "",
    planned_start_chapter: null, planned_end_chapter: null, goal: null, core_conflict: null,
    core_conflict_status: "uncertain", emotional_beat: null, must_happen: null, must_not_happen: null,
    narrative_tag: "draft", narrative_function: null, pov_character_ref: null,
    related_thread_refs: [], related_character_refs: [], related_entity_refs: [],
    basis: "作者在采用前新增这一场。", uncertain_fields: ["core_conflict"], confidence: 1,
  })
  void nextTick(() => document.getElementById(fieldId(draft.value.scenes.length - 1, "title"))?.focus())
}

function moveScene(index, offset) {
  const target = index + offset
  if (target < 0 || target >= draft.value.scenes.length) return
  const [scene] = draft.value.scenes.splice(index, 1)
  draft.value.scenes.splice(target, 0, scene)
}

function needsCheck(scene) {
  return Boolean(scene?.uncertain_fields?.length || (typeof scene?.confidence === "number" && scene.confidence < 0.7))
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
  if (!Array.isArray(draft.value?.scenes)) errors.push({ id: "outline-scene-error-title", message: "场景建议格式不完整" })
  for (const [sceneIndex, scene] of (draft.value?.scenes || []).entries()) {
    required(fieldId(sceneIndex, "title"), scene.title, `请填写场景 ${sceneIndex + 1} 的名称`, 255)
    required(fieldId(sceneIndex, "basis"), scene.basis, `请填写场景 ${sceneIndex + 1} 的创作依据`)
    const start = positive(fieldId(sceneIndex, "start"), scene.planned_start_chapter, `场景 ${sceneIndex + 1} 的起始章节`)
    const end = positive(fieldId(sceneIndex, "end"), scene.planned_end_chapter, `场景 ${sceneIndex + 1} 的结束章节`)
    if (start && end && end < start) errors.push({ id: fieldId(sceneIndex, "end"), message: `场景 ${sceneIndex + 1} 的结束章节不能早于起始章节` })
    if (!CONFLICT_VALUES.has(scene.core_conflict_status)) errors.push({ id: fieldId(sceneIndex, "status"), message: `请选择场景 ${sceneIndex + 1} 的冲突安排` })
    if (scene.core_conflict_status === "present") required(fieldId(sceneIndex, "conflict"), scene.core_conflict, `请填写场景 ${sceneIndex + 1} 的核心冲突`)
    if (!NARRATIVE_VALUES.has(scene.narrative_tag)) errors.push({ id: fieldId(sceneIndex, "tag"), message: `请选择场景 ${sceneIndex + 1} 的叙事位置` })
  }
  validationErrors.value = errors
  if (errors.length) void nextTick(() => errorSummary.value?.focus())
  return errors.length === 0
}

function normalizeDraft() {
  const normalized = clone(draft.value)
  const optionalNumber = (value) => value === "" || value == null ? null : Number(value)
  const optionalText = (value) => String(value || "").trim() || null
  for (const scene of normalized.scenes) {
    scene.title = String(scene.title || "").trim()
    scene.basis = String(scene.basis || "").trim()
    scene.planned_start_chapter = optionalNumber(scene.planned_start_chapter)
    scene.planned_end_chapter = optionalNumber(scene.planned_end_chapter)
    for (const field of ["goal", "core_conflict", "emotional_beat", "must_happen", "must_not_happen", "narrative_function"]) scene[field] = optionalText(scene[field])
    const uncertain = new Set(Array.isArray(scene.uncertain_fields) ? scene.uncertain_fields : [])
    if (scene.core_conflict_status === "uncertain") uncertain.add("core_conflict")
    else uncertain.delete("core_conflict")
    if (scene.core_conflict_status === "not_applicable") scene.core_conflict = null
    scene.uncertain_fields = Array.from(uncertain)
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
      await router?.replace?.("outline", "scenes", query)
    }
  } finally {
    applying.value = false
  }
}

function restoreOriginal() {
  confirmAction("恢复 AI 最初给出的场景建议？当前本机修改会被替换。", () => {
    initializing = true
    draft.value = clone(originalDraft.value)
    clearDraft()
    manager.state.applyError = null
    void nextTick(() => { initializing = false; saveDraft() })
  }, "恢复 AI 原稿")
}

function discard() {
  confirmAction("放弃这份场景建议？本机暂存的修改也会一并清除。", () => {
    clearDraft()
    currentProjectId = null
    currentTaskId = null
    draft.value = null
    clearOutlineGenerateWorkflowsForTarget("planned_scene")
    resetOutlineGenerateState()
    closeReview(false)
  }, "放弃建议")
}

function focusField(id) {
  document.getElementById(id)?.focus()
}
</script>
