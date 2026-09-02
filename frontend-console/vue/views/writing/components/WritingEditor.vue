<template>
  <div class="writing-editor-shell">
    <div class="writing-editor-header">
      <div class="writing-editor-title-group">
        <span id="writing-chapter-title" class="writing-editor-chapter-title">{{ hasChapter ? `第 ${chapterNumber} 章` : '未选择章节' }}</span>
        <input
          v-if="chapterReady"
          id="writing-title-input"
          ref="titleEl"
          class="writing-title-input"
          type="text"
          :value="state.title"
          :readonly="state.readonly"
          placeholder="章节标题"
        >
      </div>
      <div id="writing-editor-buttons" class="writing-editor-buttons">
        <button v-if="state.status !== 'candidate'" id="btn-publish" class="btn btn-primary btn-sm writing-primary-action" :disabled="!chapterReady || state.readonly || Boolean(state.saveError) || !state.content.trim()" @click="$emit('publish')">设为正式正文</button>
        <span v-if="hasChapter && state.status !== 'candidate'" class="writing-primary-action__hint">只在本作品内生效，不会对外发布</span>
        <div ref="toolMenusEl" class="writing-editor-buttons__menus" @click="closeToolMenuAfterAction" @keydown="onToolMenuKeydown">
          <details v-if="state.status !== 'candidate'" class="writing-tools-menu" @toggle="onToolMenuToggle('save', $event)">
            <summary class="btn btn-sm" aria-controls="writing-save-tools" :aria-expanded="String(openToolMenu === 'save')">保存</summary>
            <div id="writing-save-tools" class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <button id="btn-autosave" class="btn btn-sm" :disabled="!chapterReady || state.readonly || state.saving" @click="$emit('autosave')">{{ state.restoreSourceVersion ? '保存为新工作稿' : '保存工作稿' }}</button>
                <button id="btn-checkpoint-version" class="btn btn-sm" :disabled="!chapterReady || state.readonly || state.saving" @click="$emit('checkpoint')">保存版本</button>
                <button v-if="state.status === 'draft' && Number(state.versionNumber || 0) > 1" class="btn btn-sm btn-ghost" @click="$emit('discard')">放弃未设为正式正文的更改</button>
              </div>
            </div>
          </details>
          <details v-if="hasChapters && state.status !== 'candidate'" class="writing-tools-menu" @toggle="onToolMenuToggle('ai', $event)">
            <summary class="btn btn-sm" data-action="writing-ai-menu" aria-controls="writing-ai-tools" :aria-expanded="String(openToolMenu === 'ai')">AI 写作助手</summary>
            <div id="writing-ai-tools" class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <strong>可编辑建议</strong>
                <button class="btn btn-sm" :disabled="!chapterReady || state.readonly || !state.content.trim() || generationLoading" @click="$emit('generate-continuation')">{{ generationLoading ? '生成中…' : '续写建议' }}</button>
                <button class="btn btn-sm" :disabled="!chapterReady || state.readonly || generationLoading" @click="$emit('generate-draft')">AI 正文建议</button>
                <button class="btn btn-sm" :disabled="!chapterReady || state.readonly || generationLoading" @click="$emit('generate-pov')">AI 角色视角建议</button>
              </div>
              <div class="writing-tools-menu__group">
                <strong>从正文整理资料</strong>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'scenes')">先整理场景骨架（推荐）</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'deep')">完整整理世界与结构</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'world_objects')">整理人物、设定与关系</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'plot_structure')">整理剧情线</button>
                <button class="btn btn-sm btn-link" @click="$emit('open-deep-import-settings')">调整深度导入设置</button>
              </div>
            </div>
          </details>
          <details class="writing-tools-menu" @toggle="onToolMenuToggle('checks', $event)">
            <summary class="btn btn-sm" data-action="writing-more-menu" aria-controls="writing-check-tools" :aria-expanded="String(openToolMenu === 'checks')">检查与导出</summary>
            <div id="writing-check-tools" class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <button id="btn-conflict-check" class="btn btn-sm" :disabled="!chapterReady || state.readonly || conflictLoading" @click="$emit('conflict-check')">{{ conflictLoading ? '检查中...' : '检查前后设定' }}</button>
                <button class="btn btn-sm" :disabled="!chapterReady" @click="$emit('export')">导出本章</button>
              </div>
            </div>
          </details>
        </div>
        <div v-if="$slots['context-actions']" class="writing-editor-buttons__context" aria-label="版本与检查状态">
          <slot name="context-actions" />
        </div>
      </div>
    </div>

    <div v-if="!hasChapter" class="writing-editor-empty">
      <p>请从左侧选择章节开始写作</p>
    </div>
    <div v-else-if="state.loading" class="writing-editor-state loading-skeleton" role="status" aria-live="polite" aria-busy="true">
      <p>正在打开第 {{ chapterNumber }} 章…</p>
      <div class="skeleton loading-skeleton__heading" aria-hidden="true" />
      <div class="skeleton loading-skeleton__line" aria-hidden="true" />
      <div class="skeleton loading-skeleton__line loading-skeleton__line--medium" aria-hidden="true" />
    </div>
    <div v-else-if="state.loadError" class="writing-editor-state error-card" role="alert">
      <div>
        <strong>第 {{ chapterNumber }} 章暂时无法打开</strong>
        <p>{{ state.loadError }}。上一章的内容仍安全保留，没有写入本章。</p>
      </div>
      <button id="writing-retry-load" class="btn btn-sm" type="button" @click="$emit('retry-load')">重新加载</button>
    </div>
    <template v-else>
      <div v-if="state.saveError || (state.dirty && state.backupComplete === false)" class="writing-save-recovery error-card" role="alert">
        <div>
          <strong>工作稿还没有保存</strong>
          <p v-if="state.saveError">
            {{ state.saveError }}。{{ state.backupComplete
              ? "本地备份仍保留在这台设备上。"
              : "本地备份不可用，离开或刷新会丢失未保存修改。" }}保存成功前不会切换章节。
          </p>
          <p v-else>本地备份不可用，当前修改只保留在这个页面；离开或刷新会丢失。请尽快保存工作稿。</p>
        </div>
        <button id="writing-retry-save" class="btn btn-sm" type="button" :disabled="state.saving" @click="$emit('autosave')">{{ state.saving ? '重试中…' : '重试保存' }}</button>
      </div>
      <section
        v-if="state.status === 'candidate'"
        ref="reviewPanelEl"
        class="pov-candidate-panel writing-candidate-review-panel"
        tabindex="-1"
        aria-labelledby="writing-candidate-review-title"
        aria-describedby="writing-candidate-review-description"
        :aria-busy="candidateBusy"
      >
        <div class="writing-pov-header">
          <span class="writing-candidate-kicker">AI 建议 · 待你决定</span>
          <h2 id="writing-candidate-review-title" class="writing-pov-title">这份建议还没有改动工作稿</h2>
          <p id="writing-candidate-review-description" class="writing-pov-subtitle">{{ reviewStatusText }}</p>
        </div>
        <div v-if="candidateComparisonAvailable" class="writing-candidate-comparison">
          <span>不必靠记忆判断，先看看正文具体改了什么。</span>
          <button type="button" class="btn btn-sm" :disabled="candidateBusy" @click="$emit('compare-candidate')">与当前工作稿比较</button>
        </div>
        <ul v-if="visibleFindings.length" class="writing-candidate-findings" aria-label="独立审查问题">
          <li v-for="finding in visibleFindings" :key="finding.finding_id">
            <strong>{{ severityLabel(finding.severity) }}</strong>
            <span>{{ finding.message }}</span>
            <small v-if="finding.location?.excerpt">位置：{{ finding.location.excerpt }}</small>
          </li>
        </ul>
        <p v-if="state.candidateActionError" class="writing-candidate-action-error" role="alert">{{ state.candidateActionError }}</p>
        <div class="writing-candidate-review-actions">
          <button v-if="canAdoptCandidate" class="btn btn-primary" :disabled="candidateBusy" @click="$emit('adopt')">{{ state.candidateAction === 'adopt' ? '采用中…' : '采用到工作稿' }}</button>
          <button v-else-if="reviewBlocked" class="btn btn-primary" :disabled="candidateBusy" @click="$emit('targeted-revision')">{{ generationLoading ? '返修中…' : '按问题定向返修' }}</button>
          <button v-else class="btn btn-primary" :disabled="candidateBusy" @click="$emit('semantic-review')">{{ generationLoading ? '审查中…' : '运行独立语义审查' }}</button>
          <button v-if="canAdoptCandidate || independentReview" class="btn" :disabled="candidateBusy" @click="$emit('semantic-review')">{{ independentReview ? '重新独立审查' : '运行独立语义审查' }}</button>
          <button class="btn writing-candidate-reject" :disabled="candidateBusy" @click="$emit('reject')">{{ state.candidateAction === 'reject' ? '拒绝中…' : '拒绝建议' }}</button>
        </div>
      </section>
      <div class="writing-sheet" :class="{ 'writing-sheet--candidate': state.status === 'candidate' }">
        <textarea
          id="writing-editor"
          ref="editorEl"
          class="novel-editor"
          :class="[`novel-editor--font-${editorFont}`, { 'novel-editor--focus': focusMode }]"
          :value="state.content"
          :readonly="state.readonly"
          aria-label="章节正文"
          :aria-describedby="state.status === 'candidate' ? 'writing-candidate-review-description' : undefined"
          placeholder="开始写作..."
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = defineProps({
  state: { type: Object, required: true },
  targetChapter: { type: Number, default: null },
  saveStatus: { type: String, default: "已保存" },
  editorFont: { type: String, default: "system" },
  dailyGoal: { type: Number, default: null },
  focusMode: { type: Boolean, default: false },
  generationLoading: { type: Boolean, default: false },
  conflictLoading: { type: Boolean, default: false },
  reviewResult: { type: Object, default: null },
  candidateComparisonAvailable: { type: Boolean, default: false },
  hasChapters: { type: Boolean, default: false },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits([
  "autosave", "checkpoint", "conflict-check", "publish", "discard",
  "generate-draft", "generate-continuation", "generate-pov",
  "auto-extract", "open-deep-import-settings", "adopt", "reject",
  "semantic-review", "targeted-revision", "compare-candidate", "export",
  "retry-load",
])

const titleEl = ref(null)
const editorEl = ref(null)
const reviewPanelEl = ref(null)
const toolMenusEl = ref(null)
const openToolMenu = ref(null)
const chapterNumber = computed(() => Number(props.targetChapter || props.state.chapter) || null)
const hasChapter = computed(() => Number.isInteger(chapterNumber.value) && chapterNumber.value > 0)
const chapterReady = computed(() => hasChapter.value
  && !props.state.loading
  && !props.state.loadError
  && Number(props.state.chapter) === chapterNumber.value)
const independentReview = computed(() => props.state.provenanceJson?.independent_review || null)
const reviewBlocked = computed(() => independentReview.value?.verdict === "needs_revision" || Number(independentReview.value?.blocking_count || 0) > 0)
const canAdoptCandidate = computed(() => !props.state.provenanceJson?.review_required || independentReview.value?.verdict === "pass")
const candidateBusy = computed(() => Boolean(props.generationLoading || props.state.candidateAction))
const candidateIdentity = computed(() => props.state.status === "candidate" ? props.state.draftId : null)
const candidateReady = computed(() => !props.state.loading && !props.state.loadError ? candidateIdentity.value : null)
const reviewStatusText = computed(() => {
  if (!props.state.provenanceJson?.review_required) return "请先阅读建议正文；采用会创建新工作稿，拒绝只会将建议留在版本历史中。"
  if (!independentReview.value) return "采用前需要一次独立语义审查，正文仍保持只读。"
  if (reviewBlocked.value) return `独立审查发现 ${independentReview.value.blocking_count || 0} 个必须先处理的问题。`
  return "独立语义审查已通过，可以采用。"
})
const visibleFindings = computed(() => (props.reviewResult?.findings || []).filter((item) => item?.location?.draft_id === props.state.draftId).slice(0, 20))
const severityLabel = (severity) => ({ blocker: "阻断", major: "重要", minor: "建议" }[severity] || "问题")
const attachElements = () => nextTick(() => {
  if (editorEl.value) props.attach({ title: titleEl.value, editor: editorEl.value })
  else props.detach()
})
const focusCandidateReview = () => nextTick(() => reviewPanelEl.value?.focus())
function closeToolMenu(details, restoreFocus = false) {
  if (!details) return
  const summary = details.querySelector(":scope > summary")
  details.open = false
  openToolMenu.value = null
  if (restoreFocus) summary?.focus()
}
function closeAllToolMenus() {
  toolMenusEl.value?.querySelectorAll("details[open]").forEach((details) => closeToolMenu(details))
}
function onToolMenuToggle(name, event) {
  const details = event.currentTarget
  if (!details.open) {
    if (openToolMenu.value === name) openToolMenu.value = null
    return
  }
  openToolMenu.value = name
  toolMenusEl.value?.querySelectorAll("details[open]").forEach((other) => {
    if (other !== details) other.open = false
  })
}
function closeToolMenuAfterAction(event) {
  const button = event.target.closest?.("button")
  if (button && !button.disabled) closeToolMenu(button.closest("details"), true)
}
function onToolMenuKeydown(event) {
  if (event.key !== "Escape") return
  const details = event.target.closest?.("details[open]")
  if (!details) return
  event.preventDefault()
  event.stopPropagation()
  closeToolMenu(details, true)
}
function onDocumentPointerdown(event) {
  if (toolMenusEl.value && !toolMenusEl.value.contains(event.target)) closeAllToolMenus()
}
onMounted(() => {
  attachElements()
  if (candidateReady.value) focusCandidateReview()
  document.addEventListener("pointerdown", onDocumentPointerdown)
})
watch(chapterReady, attachElements)
watch(candidateReady, (current, previous) => {
  if (current && current !== previous) focusCandidateReview()
})
watch(() => props.state.status, (current, previous) => {
  closeAllToolMenus()
  if (previous === "candidate" && current !== "candidate") nextTick(() => editorEl.value?.focus())
})
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocumentPointerdown)
  props.detach()
})
</script>
