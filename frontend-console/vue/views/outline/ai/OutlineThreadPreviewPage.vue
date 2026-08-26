<template>
  <section class="outline-thread-review" aria-labelledby="outline-thread-review-title">
    <div v-if="!preview" class="outline-thread-review__loading" :role="progress?.failed || !progress ? 'alert' : 'status'">
      <h2>{{ progress?.failed || !progress ? "这份建议暂时无法打开" : "正在恢复剧情线建议" }}</h2>
      <p>{{ progress?.failed || !progress ? (progress?.errorMessage || "没有找到可恢复的剧情线建议，请返回后重新生成。") : "正在读取原任务和本机暂存的修改…" }}</p>
      <button type="button" class="btn" data-action="close-outline-generate-preview" @click="closeReview">返回剧情线</button>
    </div>

    <template v-else-if="draft">
      <header class="outline-thread-review__header">
        <div>
          <span class="outline-thread-review__eyebrow">AI 未采用建议</span>
          <h2 id="outline-thread-review-title">检查剧情线建议</h2>
          <p>先把名称、目标、秘密和信息推进改成你的版本。只有点击“采用到剧情线”后，才会写入作品结构。</p>
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
          <p>{{ conflict ? "你的修改仍保留在本机。这份旧建议已不能直接采用，请返回剧情线后重新生成。" : `${applyError?.message || "采用失败"}。你的修改仍保留，可以稍后重试。` }}</p>
        </div>
        <button v-if="conflict" type="button" class="btn btn-sm" @click="closeReview">返回并重新生成</button>
      </div>

      <section v-if="storyConflict" class="outline-thread-review__notice outline-thread-review__notice--warning" role="note">
        <h3>这份建议与故事总览有冲突</h3>
        <p><strong>你想改变：</strong>{{ storyConflict.requested_change }}</p>
        <p><strong>冲突位置：</strong>{{ storyConflict.conflict_with_outline }}</p>
        <p><strong>建议先处理：</strong>{{ storyConflict.suggested_story_outline_revision }}</p>
      </section>

      <section v-if="warnings.length" class="outline-thread-review__notice" aria-labelledby="outline-thread-warning-title">
        <h3 id="outline-thread-warning-title">采用前请留意</h3>
        <ul><li v-for="warning in warnings" :key="warning">{{ warning }}</li></ul>
      </section>

      <details v-if="overlaps.length || reuseJudgments.length" class="outline-thread-review__support">
        <summary>查看与现有剧情线的关系</summary>
        <div class="outline-thread-review__support-body">
          <div v-if="overlaps.length">
            <h3>可能重叠</h3>
            <ul><li v-for="(item, index) in overlaps" :key="index">{{ item.name || item.title || "一项现有剧情线" }}</li></ul>
          </div>
          <div v-if="reuseJudgments.length">
            <h3>AI 的复用判断</h3>
            <ul><li v-for="(item, index) in reuseJudgments" :key="index">{{ reuseLabel(item.judgment) }}：{{ item.basis }}</li></ul>
          </div>
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
        <div v-if="validationErrors.length" ref="errorSummary" class="story-outline-generate__error-summary" role="alert" tabindex="-1" aria-labelledby="outline-thread-error-title">
          <strong id="outline-thread-error-title">请先修正以下内容</strong>
          <ul>
            <li v-for="item in validationErrors" :key="item.id"><a :href="`#${item.id}`" @click.prevent="focusField(item.id)">{{ item.message }}</a></li>
          </ul>
        </div>

        <div class="outline-thread-review__section-heading">
          <div><h3>剧情线设计</h3><p>先核对故事会如何推进，再按需展开信息铺垫。</p></div>
          <button type="button" class="btn btn-sm" data-action="add-outline-preview-thread" @click="addThread">新增剧情线</button>
        </div>

        <article v-for="(thread, threadIndex) in draft.threads" :key="thread.proposal_ref || threadIndex" class="outline-thread-editor">
          <header class="outline-thread-editor__header">
            <div><span>剧情线 {{ threadIndex + 1 }}</span><strong>{{ thread.name || "未命名剧情线" }}</strong></div>
            <div class="outline-thread-editor__item-actions">
              <button type="button" class="btn btn-sm btn-ghost" :disabled="threadIndex === 0" :aria-label="`上移剧情线 ${threadIndex + 1}`" @click="moveItem(draft.threads, threadIndex, -1)">上移</button>
              <button type="button" class="btn btn-sm btn-ghost" :disabled="threadIndex === draft.threads.length - 1" :aria-label="`下移剧情线 ${threadIndex + 1}`" @click="moveItem(draft.threads, threadIndex, 1)">下移</button>
              <button type="button" class="btn btn-sm btn-ghost" :aria-label="`移除剧情线 ${threadIndex + 1}`" @click="draft.threads.splice(threadIndex, 1)">移除</button>
            </div>
          </header>

          <div class="outline-thread-editor__grid">
            <div class="form-group">
              <label :for="fieldId(threadIndex, 'name')">剧情线名称</label>
              <input :id="fieldId(threadIndex, 'name')" v-model="thread.name" class="form-input" maxlength="255" :aria-invalid="Boolean(fieldError(fieldId(threadIndex, 'name')))" :aria-describedby="errorId(threadIndex, 'name')" />
              <p v-if="fieldError(fieldId(threadIndex, 'name'))" :id="errorId(threadIndex, 'name')" class="form-error">{{ fieldError(fieldId(threadIndex, 'name')) }}</p>
            </div>
            <div class="form-group">
              <label :for="fieldId(threadIndex, 'type')">剧情线类型</label>
              <select :id="fieldId(threadIndex, 'type')" v-model="thread.thread_type" class="form-select" :aria-invalid="Boolean(fieldError(fieldId(threadIndex, 'type')))" :aria-describedby="errorId(threadIndex, 'type')">
                <option value="main">主线</option><option value="sub">支线</option><option value="background">暗线</option>
                <option v-if="!knownThreadTypes.includes(thread.thread_type)" :value="thread.thread_type">其他：{{ thread.thread_type }}</option>
              </select>
              <p v-if="fieldError(fieldId(threadIndex, 'type'))" :id="errorId(threadIndex, 'type')" class="form-error">{{ fieldError(fieldId(threadIndex, 'type')) }}</p>
            </div>
          </div>

          <div class="form-group">
            <label :for="fieldId(threadIndex, 'summary')">一句话说明</label>
            <textarea :id="fieldId(threadIndex, 'summary')" v-model="thread.summary" class="form-textarea" rows="3" maxlength="4000" placeholder="这条剧情线讲什么，它为什么值得跟下去？"></textarea>
          </div>

          <div class="outline-thread-editor__grid">
            <div class="form-group"><label :for="fieldId(threadIndex, 'goal')">表面目标</label><textarea :id="fieldId(threadIndex, 'goal')" v-model="thread.visible_goal" class="form-textarea" rows="4" maxlength="4000" placeholder="角色或读者眼前正在追求什么？"></textarea></div>
            <div class="form-group"><label :for="fieldId(threadIndex, 'truth')">隐藏真相</label><textarea :id="fieldId(threadIndex, 'truth')" v-model="thread.hidden_truth" class="form-textarea" rows="4" maxlength="4000" placeholder="真正驱动这条线的秘密是什么？"></textarea></div>
          </div>

          <div class="outline-thread-editor__chapter-grid">
            <div class="form-group"><label :for="fieldId(threadIndex, 'start')">预计开始章</label><input :id="fieldId(threadIndex, 'start')" v-model="thread.start_chapter" class="form-input" type="number" min="1" inputmode="numeric" /></div>
            <div class="form-group"><label :for="fieldId(threadIndex, 'payoff')">预计兑现章</label><input :id="fieldId(threadIndex, 'payoff')" v-model="thread.planned_payoff_chapter" class="form-input" type="number" min="1" inputmode="numeric" /></div>
            <div class="form-group"><label :for="fieldId(threadIndex, 'stage')">当前发展阶段</label><input :id="fieldId(threadIndex, 'stage')" v-model="thread.current_stage" class="form-input" maxlength="32" placeholder="例如：埋下、加深、即将兑现" /></div>
          </div>

          <details class="outline-thread-editor__support">
            <summary>人物认知与创作依据</summary>
            <div class="outline-thread-editor__support-body">
              <div class="outline-thread-editor__grid">
                <div class="form-group"><label :for="fieldId(threadIndex, 'reader-known')">读者目前知道什么</label><textarea :id="fieldId(threadIndex, 'reader-known')" v-model="thread.reader_known_state" class="form-textarea" rows="3" maxlength="4000"></textarea></div>
                <div class="form-group"><label :for="fieldId(threadIndex, 'author-known')">作者掌握的完整情况</label><textarea :id="fieldId(threadIndex, 'author-known')" v-model="thread.author_known_state" class="form-textarea" rows="3" maxlength="4000"></textarea></div>
              </div>
              <div class="form-group">
                <label :for="fieldId(threadIndex, 'basis')">设计依据</label>
                <textarea :id="fieldId(threadIndex, 'basis')" v-model="thread.basis" class="form-textarea" rows="3" maxlength="4000" :aria-invalid="Boolean(fieldError(fieldId(threadIndex, 'basis')))" :aria-describedby="errorId(threadIndex, 'basis')"></textarea>
                <p v-if="fieldError(fieldId(threadIndex, 'basis'))" :id="errorId(threadIndex, 'basis')" class="form-error">{{ fieldError(fieldId(threadIndex, 'basis')) }}</p>
              </div>
              <p v-if="needsCheck(thread)" class="outline-thread-editor__check-note">AI 对部分信息没有把握，请重点核对已留空或标记不确定的内容。</p>
            </div>
          </details>

          <section class="outline-thread-movements" :aria-labelledby="`outline-thread-${threadIndex}-movement-title`">
            <div class="outline-thread-review__section-heading outline-thread-review__section-heading--compact">
              <div><h4 :id="`outline-thread-${threadIndex}-movement-title`">信息推进</h4><p>按“埋下—加深—兑现”安排读者逐步知道什么。</p></div>
              <button type="button" class="btn btn-sm" :data-thread-index="threadIndex" @click="addMovement(thread)">新增信息推进</button>
            </div>

            <p v-if="!thread.information_movements?.length" class="outline-thread-editor__empty">这条剧情线还没有安排信息推进。</p>
            <details v-for="(movement, movementIndex) in thread.information_movements" :key="movement.movement_ref || movementIndex" class="outline-thread-movement" :open="movementIndex === 0">
              <summary>推进 {{ movementIndex + 1 }} · {{ movement.information_subject || "未命名信息" }}</summary>
              <div class="outline-thread-movement__body">
                <div class="outline-thread-editor__item-actions outline-thread-movement__actions">
                  <button type="button" class="btn btn-sm btn-ghost" :disabled="movementIndex === 0" @click="moveItem(thread.information_movements, movementIndex, -1)">上移</button>
                  <button type="button" class="btn btn-sm btn-ghost" :disabled="movementIndex === thread.information_movements.length - 1" @click="moveItem(thread.information_movements, movementIndex, 1)">下移</button>
                  <button type="button" class="btn btn-sm btn-ghost" @click="thread.information_movements.splice(movementIndex, 1)">移除</button>
                </div>
                <div class="form-group">
                  <label :for="movementId(threadIndex, movementIndex, 'subject')">这组信息围绕什么</label>
                  <input :id="movementId(threadIndex, movementIndex, 'subject')" v-model="movement.information_subject" class="form-input" maxlength="4000" :aria-invalid="Boolean(fieldError(movementId(threadIndex, movementIndex, 'subject')))" :aria-describedby="`${movementId(threadIndex, movementIndex, 'subject')}-error`" />
                  <p v-if="fieldError(movementId(threadIndex, movementIndex, 'subject'))" :id="`${movementId(threadIndex, movementIndex, 'subject')}-error`" class="form-error">{{ fieldError(movementId(threadIndex, movementIndex, 'subject')) }}</p>
                </div>
                <div class="outline-thread-editor__grid">
                  <div class="form-group"><label :for="movementId(threadIndex, movementIndex, 'surface')">表面理解</label><textarea :id="movementId(threadIndex, movementIndex, 'surface')" v-model="movement.surface_understanding" class="form-textarea" rows="3" maxlength="4000"></textarea></div>
                  <div class="form-group"><label :for="movementId(threadIndex, movementIndex, 'hidden')">真实情况</label><textarea :id="movementId(threadIndex, movementIndex, 'hidden')" v-model="movement.hidden_content" class="form-textarea" rows="3" maxlength="4000"></textarea></div>
                </div>

                <div class="outline-thread-node-list">
                  <div class="outline-thread-review__section-heading outline-thread-review__section-heading--compact"><div><h5>推进节点</h5></div><button type="button" class="btn btn-sm" @click="addNode(movement)">新增节点</button></div>
                  <div v-for="(node, nodeIndex) in movement.nodes" :key="nodeIndex" class="outline-thread-node">
                    <div class="outline-thread-node__heading"><strong>节点 {{ nodeIndex + 1 }}</strong><button type="button" class="btn btn-sm btn-ghost" @click="movement.nodes.splice(nodeIndex, 1)">移除</button></div>
                    <div class="outline-thread-node__grid">
                      <div class="form-group"><label :for="nodeId(threadIndex, movementIndex, nodeIndex, 'kind')">作用</label><select :id="nodeId(threadIndex, movementIndex, nodeIndex, 'kind')" v-model="node.kind" class="form-select"><option v-for="kind in nodeKinds" :key="kind.value" :value="kind.value">{{ kind.label }}</option></select></div>
                      <div class="form-group"><label :for="nodeId(threadIndex, movementIndex, nodeIndex, 'chapter')">预计章节</label><input :id="nodeId(threadIndex, movementIndex, nodeIndex, 'chapter')" v-model="node.chapter_hint" class="form-input" type="number" min="1" inputmode="numeric" /></div>
                    </div>
                    <div class="form-group">
                      <label :for="nodeId(threadIndex, movementIndex, nodeIndex, 'content')">节点内容</label>
                      <textarea :id="nodeId(threadIndex, movementIndex, nodeIndex, 'content')" v-model="node.content" class="form-textarea" rows="3" maxlength="4000" :aria-invalid="Boolean(fieldError(nodeId(threadIndex, movementIndex, nodeIndex, 'content')))" :aria-describedby="`${nodeId(threadIndex, movementIndex, nodeIndex, 'content')}-error`"></textarea>
                      <p v-if="fieldError(nodeId(threadIndex, movementIndex, nodeIndex, 'content'))" :id="`${nodeId(threadIndex, movementIndex, nodeIndex, 'content')}-error`" class="form-error">{{ fieldError(nodeId(threadIndex, movementIndex, nodeIndex, 'content')) }}</p>
                    </div>
                    <div class="outline-thread-editor__grid">
                      <div class="form-group"><label :for="nodeId(threadIndex, movementIndex, nodeIndex, 'trigger')">触发条件（可选）</label><input :id="nodeId(threadIndex, movementIndex, nodeIndex, 'trigger')" v-model="node.trigger" class="form-input" maxlength="4000" /></div>
                      <div class="form-group"><label :for="nodeId(threadIndex, movementIndex, nodeIndex, 'effect')">造成的变化（可选）</label><input :id="nodeId(threadIndex, movementIndex, nodeIndex, 'effect')" v-model="node.effect" class="form-input" maxlength="4000" /></div>
                    </div>
                  </div>
                </div>

                <div class="form-group">
                  <label :for="movementId(threadIndex, movementIndex, 'basis')">推进依据</label>
                  <textarea :id="movementId(threadIndex, movementIndex, 'basis')" v-model="movement.basis" class="form-textarea" rows="3" maxlength="4000" :aria-invalid="Boolean(fieldError(movementId(threadIndex, movementIndex, 'basis')))" :aria-describedby="`${movementId(threadIndex, movementIndex, 'basis')}-error`"></textarea>
                  <p v-if="fieldError(movementId(threadIndex, movementIndex, 'basis'))" :id="`${movementId(threadIndex, movementIndex, 'basis')}-error`" class="form-error">{{ fieldError(movementId(threadIndex, movementIndex, 'basis')) }}</p>
                </div>
              </div>
            </details>
          </section>
        </article>

        <div v-if="!draft.threads.length" class="outline-thread-editor__empty outline-thread-editor__empty--large">
          <p>这份建议目前没有剧情线。你可以新增一条，或放弃这份建议。</p>
          <button type="button" class="btn" @click="addThread">新增第一条剧情线</button>
        </div>

        <footer class="outline-thread-review__actions">
          <div>
            <button type="button" class="btn btn-ghost" data-action="discard-outline-generate-preview" :disabled="applying" @click="discard">放弃这份建议</button>
            <button type="button" class="btn" :disabled="applying" @click="restoreOriginal">恢复 AI 原稿</button>
          </div>
          <button type="submit" class="btn btn-primary" data-action="apply-outline-generate-preview" :disabled="applying || conflict">{{ applying ? "采用中…" : "采用到剧情线" }}</button>
        </footer>
      </form>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import { getConfirmAction, getRouteQuery, getRouter, getToast } from "../../../bridge/index.js"
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
const knownThreadTypes = ["main", "sub", "background"]
const nodeKinds = [
  { value: "seed", label: "埋下" },
  { value: "reinforce", label: "加深" },
  { value: "payoff", label: "兑现" },
  { value: "partial_reveal", label: "部分揭示" },
  { value: "full_reveal", label: "完整揭示" },
]

const preview = computed(() => (
  manager.state.ownerProjectId === props.projectId
  && manager.state.preview?.target === "plot_thread"
) ? manager.state.preview : null)
const progress = computed(() => manager.state.ownerProjectId === props.projectId ? manager.state.progress : null)
const warnings = computed(() => preview.value?.warnings || [])
const overlaps = computed(() => preview.value?.overlap?.plot_threads || [])
const storyConflict = computed(() => draft.value?.story_outline_conflict || null)
const authorDecisions = computed(() => draft.value?.author_decisions || [])
const reuseJudgments = computed(() => draft.value?.reuse_judgments || [])
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
const storageKey = (projectId, taskId) => `novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
const fieldId = (threadIndex, field) => `outline-thread-preview-${threadIndex}-${field}`
const errorId = (threadIndex, field) => `${fieldId(threadIndex, field)}-error`
const movementId = (threadIndex, movementIndex, field) => `outline-thread-preview-${threadIndex}-movement-${movementIndex}-${field}`
const nodeId = (threadIndex, movementIndex, nodeIndex, field) => `outline-thread-preview-${threadIndex}-movement-${movementIndex}-node-${nodeIndex}-${field}`
const fieldError = (id) => validationErrors.value.find((item) => item.id === id)?.message || ""

const saveState = computed(() => {
  if (applying.value) return "正在采用…"
  if (storageError.value) return "本机暂存不可用"
  if (!savedAt.value) return "修改后会自动暂存在本机"
  const date = new Date(savedAt.value)
  return Number.isNaN(date.getTime()) ? "修改已暂存在本机" : `修改已暂存在本机 · ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
})

watch([() => props.projectId, () => preview.value?.sourceTaskId], () => initializeDraft(), { immediate: true })
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
  toast("正在采用剧情线，请稍候", "info")
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
      || saved?.target !== "plot_thread"
      || !saved?.draft_structure
      || !Array.isArray(saved.draft_structure.threads)
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
      target: "plot_thread",
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
  const query = getRouteQuery()
  query.delete("review")
  router?.replace?.("outline", "threads", query)
}

function localRef(prefix) {
  localRefCounter += 1
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}-${uuid || `${Date.now().toString(36)}-${localRefCounter}`}`.slice(0, 64)
}

function addThread() {
  draft.value.threads.push({
    proposal_ref: localRef("author-thread"), target_thread_ref: null, name: "", thread_type: "main",
    summary: null, visible_goal: null, hidden_truth: null, start_chapter: null,
    planned_payoff_chapter: null, current_stage: null, related_character_refs: [],
    related_entity_refs: [], reader_known_state: null, author_known_state: null,
    information_movements: [], basis: "作者在采用前新增这条剧情线。", uncertain_fields: [], confidence: 1,
  })
  void nextTick(() => document.getElementById(fieldId(draft.value.threads.length - 1, "name"))?.focus())
}

function addMovement(thread) {
  thread.information_movements ||= []
  thread.information_movements.push({
    movement_ref: localRef("author-movement"), information_subject: "", surface_understanding: null,
    hidden_content: null, target_ref: null, nodes: [], basis: "作者在采用前新增这组信息推进。",
    uncertain_fields: ["hidden_content"], confidence: 1,
  })
}

function addNode(movement) {
  movement.nodes ||= []
  movement.nodes.push({ kind: "seed", content: "", chapter_hint: null, scene_ref: null, trigger: null, effect: null })
}

function moveItem(items, index, offset) {
  const target = index + offset
  if (target < 0 || target >= items.length) return
  const [item] = items.splice(index, 1)
  items.splice(target, 0, item)
}

function reuseLabel(value) {
  return ({ reuse: "建议复用", revise: "建议修订", not_relevant: "无需关联" })[value] || "需要核对"
}

function needsCheck(item) {
  return Boolean(item?.uncertain_fields?.length || (typeof item?.confidence === "number" && item.confidence < 0.7))
}

function validateDraft() {
  const errors = []
  const required = (id, value, message, max = 4000) => {
    const text = String(value || "").trim()
    if (!text) errors.push({ id, message })
    else if (text.length > max) errors.push({ id, message: `${message.replace(/^请填写/, "")}不能超过 ${max} 字` })
  }
  const positiveChapter = (id, value, label) => {
    if (value === "" || value == null) return
    const number = Number(value)
    if (!Number.isInteger(number) || number < 1) errors.push({ id, message: `${label}必须是正整数` })
  }
  if (!Array.isArray(draft.value?.threads)) errors.push({ id: "outline-thread-error-title", message: "剧情线建议格式不完整" })
  for (const [threadIndex, thread] of (draft.value?.threads || []).entries()) {
    required(fieldId(threadIndex, "name"), thread.name, `请填写剧情线 ${threadIndex + 1} 的名称`, 255)
    required(fieldId(threadIndex, "type"), thread.thread_type, `请填写剧情线 ${threadIndex + 1} 的类型`, 32)
    required(fieldId(threadIndex, "basis"), thread.basis, `请填写剧情线 ${threadIndex + 1} 的设计依据`)
    positiveChapter(fieldId(threadIndex, "start"), thread.start_chapter, `剧情线 ${threadIndex + 1} 的开始章`)
    positiveChapter(fieldId(threadIndex, "payoff"), thread.planned_payoff_chapter, `剧情线 ${threadIndex + 1} 的兑现章`)
    for (const [movementIndex, movement] of (thread.information_movements || []).entries()) {
      required(movementId(threadIndex, movementIndex, "subject"), movement.information_subject, `请填写推进 ${movementIndex + 1} 围绕的信息`)
      required(movementId(threadIndex, movementIndex, "basis"), movement.basis, `请填写推进 ${movementIndex + 1} 的设计依据`)
      for (const [nodeIndex, node] of (movement.nodes || []).entries()) {
        required(nodeId(threadIndex, movementIndex, nodeIndex, "content"), node.content, `请填写推进 ${movementIndex + 1} 节点 ${nodeIndex + 1} 的内容`)
        positiveChapter(nodeId(threadIndex, movementIndex, nodeIndex, "chapter"), node.chapter_hint, `节点 ${nodeIndex + 1} 的章节`)
      }
    }
  }
  validationErrors.value = errors
  if (errors.length) void nextTick(() => errorSummary.value?.focus())
  return errors.length === 0
}

function normalizeDraft() {
  const normalized = clone(draft.value)
  const optionalNumber = (value) => value === "" || value == null ? null : Number(value)
  const optionalText = (value) => String(value || "").trim() || null
  for (const thread of normalized.threads) {
    thread.name = String(thread.name || "").trim()
    thread.thread_type = String(thread.thread_type || "").trim()
    thread.basis = String(thread.basis || "").trim()
    thread.start_chapter = optionalNumber(thread.start_chapter)
    thread.planned_payoff_chapter = optionalNumber(thread.planned_payoff_chapter)
    for (const field of ["summary", "visible_goal", "hidden_truth", "current_stage", "reader_known_state", "author_known_state"]) thread[field] = optionalText(thread[field])
    for (const movement of thread.information_movements || []) {
      movement.information_subject = String(movement.information_subject || "").trim()
      movement.basis = String(movement.basis || "").trim()
      for (const field of ["surface_understanding", "hidden_content"]) movement[field] = optionalText(movement[field])
      for (const node of movement.nodes || []) {
        node.content = String(node.content || "").trim()
        node.chapter_hint = optionalNumber(node.chapter_hint)
        for (const field of ["trigger", "effect"]) node[field] = optionalText(node[field])
      }
    }
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
      const query = getRouteQuery()
      query.delete("review")
      await router?.replace?.("outline", "threads", query)
    }
  } finally {
    applying.value = false
  }
}

function restoreOriginal() {
  confirmAction("恢复 AI 最初给出的剧情线建议？当前本机修改会被替换。", () => {
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
  confirmAction("放弃这份剧情线建议？本机暂存的修改也会一并清除。", () => {
    clearDraft()
    currentProjectId = null
    currentTaskId = null
    draft.value = null
    clearOutlineGenerateWorkflowsForTarget("plot_thread")
    resetOutlineGenerateState()
    closeReview(false)
  }, "放弃建议")
}

function focusField(id) {
  document.getElementById(id)?.focus()
}
</script>
