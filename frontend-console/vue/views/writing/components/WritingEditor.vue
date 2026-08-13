<template>
  <div class="writing-editor-shell">
    <div class="writing-editor-header">
      <div class="writing-editor-title-group">
        <span id="writing-chapter-title" class="writing-editor-chapter-title">{{ state.chapter ? `第 ${state.chapter} 章` : '未选择章节' }}</span>
        <input
          v-if="hasChapter"
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
        <button id="btn-publish" class="btn btn-primary btn-sm writing-primary-action" :disabled="!hasChapter || state.readonly || !state.content.trim()" @click="$emit('publish')">设为正式正文</button>
        <span v-if="hasChapter" class="writing-primary-action__hint">只在本作品内生效，不会对外发布</span>
        <div class="writing-editor-buttons__menus">
          <details class="writing-tools-menu">
            <summary class="btn btn-sm">工作稿与版本</summary>
            <div class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <button id="btn-autosave" class="btn btn-sm" :disabled="!hasChapter || state.readonly || state.saving" @click="$emit('autosave')">{{ state.restoreSourceVersion ? '保存为新工作稿' : '保存工作稿' }}</button>
                <button id="btn-checkpoint-version" class="btn btn-sm" :disabled="!hasChapter || state.readonly || state.saving" @click="$emit('checkpoint')">保存版本</button>
                <button v-if="state.status === 'draft' && Number(state.versionNumber || 0) > 1" class="btn btn-sm btn-ghost" @click="$emit('discard')">放弃未设为正式正文的更改</button>
              </div>
            </div>
          </details>
          <details v-if="hasChapters" class="writing-tools-menu">
            <summary class="btn btn-sm" data-action="writing-ai-menu">AI 写作助手</summary>
            <div class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <strong>可编辑建议</strong>
                <button class="btn btn-sm btn-primary" :disabled="!hasChapter || state.readonly || !state.content.trim() || generationLoading" @click="$emit('generate-continuation')">{{ generationLoading ? '生成中…' : '续写建议' }}</button>
                <button class="btn btn-sm" :disabled="!hasChapter || state.readonly || generationLoading" @click="$emit('generate-draft')">AI 正文建议</button>
                <button class="btn btn-sm" :disabled="!hasChapter || state.readonly || generationLoading" @click="$emit('generate-pov')">AI 角色视角建议</button>
              </div>
              <div class="writing-tools-menu__group">
                <strong>从正文整理资料</strong>
                <button class="btn btn-sm btn-primary" @click="$emit('auto-extract', 'scenes')">先整理场景骨架（推荐）</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'deep')">完整整理世界与结构</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'world_objects')">整理人物、设定与关系</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'plot_structure')">整理剧情线</button>
                <button class="btn btn-sm btn-link" @click="$emit('open-deep-import-settings')">调整深度导入设置</button>
              </div>
            </div>
          </details>
          <details class="writing-tools-menu">
            <summary class="btn btn-sm" data-action="writing-more-menu">更多</summary>
            <div class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <button id="btn-conflict-check" class="btn btn-sm" :disabled="!hasChapter || state.readonly || conflictLoading" @click="$emit('conflict-check')">{{ conflictLoading ? '检查中...' : '检查前后设定' }}</button>
                <button class="btn btn-sm" :disabled="!hasChapter" @click="$emit('export')">导出本章</button>
                <button class="btn btn-sm" @click="$emit('toggle-focus')">专注模式</button>
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
    <template v-else>
      <div class="writing-sheet">
        <textarea
          id="writing-editor"
          ref="editorEl"
          class="novel-editor"
          :class="[`novel-editor--font-${editorFont}`, { 'novel-editor--focus': focusMode }]"
          :value="state.content"
          :readonly="state.readonly"
          aria-label="章节正文"
          placeholder="开始写作..."
        />

        <section v-if="state.status === 'candidate'" class="pov-candidate-panel writing-candidate-review-panel">
          <div class="writing-pov-header">
            <div>
              <div class="writing-pov-title">AI 正文建议待审核</div>
              <div class="writing-pov-subtitle">{{ reviewStatusText }}</div>
            </div>
          </div>
          <ul v-if="visibleFindings.length" class="writing-candidate-findings" aria-label="独立审查问题">
            <li v-for="finding in visibleFindings" :key="finding.finding_id">
              <strong>{{ severityLabel(finding.severity) }}</strong>
              <span>{{ finding.message }}</span>
              <small v-if="finding.location?.excerpt">位置：{{ finding.location.excerpt }}</small>
            </li>
          </ul>
          <div class="writing-candidate-review-actions">
            <button class="btn" :disabled="generationLoading" @click="$emit('semantic-review')">{{ independentReview ? '重新独立审查' : '运行独立语义审查' }}</button>
            <button v-if="reviewBlocked" class="btn" :disabled="generationLoading" @click="$emit('targeted-revision')">按问题定向返修</button>
            <button class="btn btn-primary" :disabled="!canAdoptCandidate || generationLoading" @click="$emit('adopt')">采用到工作稿</button>
            <button class="btn btn-danger" @click="$emit('reject')">拒绝建议</button>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = defineProps({
  state: { type: Object, required: true },
  saveStatus: { type: String, default: "已保存" },
  editorFont: { type: String, default: "system" },
  dailyGoal: { type: Number, default: null },
  focusMode: { type: Boolean, default: false },
  generationLoading: { type: Boolean, default: false },
  conflictLoading: { type: Boolean, default: false },
  reviewResult: { type: Object, default: null },
  hasChapters: { type: Boolean, default: false },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits([
  "autosave", "checkpoint", "conflict-check", "publish", "discard",
  "generate-draft", "generate-continuation", "generate-pov",
  "auto-extract", "open-deep-import-settings", "adopt", "reject",
  "semantic-review", "targeted-revision", "export", "toggle-focus",
])

const titleEl = ref(null)
const editorEl = ref(null)
const hasChapter = computed(() => Number.isInteger(Number(props.state.chapter)) && Number(props.state.chapter) > 0)
const independentReview = computed(() => props.state.provenanceJson?.independent_review || null)
const reviewBlocked = computed(() => independentReview.value?.verdict === "needs_revision" || Number(independentReview.value?.blocking_count || 0) > 0)
const canAdoptCandidate = computed(() => !props.state.provenanceJson?.review_required || independentReview.value?.verdict === "pass")
const reviewStatusText = computed(() => {
  if (!props.state.provenanceJson?.review_required) return "建议尚未进入工作稿，请明确采用或拒绝。"
  if (!independentReview.value) return "采用前需要一次与生成器分离的语义审查。"
  if (reviewBlocked.value) return `独立审查还有 ${independentReview.value.blocking_count || 0} 个阻断项，请先返修。`
  return "独立语义审查已通过，可以采用到工作稿。"
})
const visibleFindings = computed(() => (props.reviewResult?.findings || []).filter((item) => item?.location?.draft_id === props.state.draftId).slice(0, 20))
const severityLabel = (severity) => ({ blocker: "阻断", major: "重要", minor: "建议" }[severity] || "问题")
const attachElements = () => props.attach({ title: titleEl.value, editor: editorEl.value })
onMounted(() => nextTick(attachElements))
watch(() => props.state.chapter, () => nextTick(attachElements))
onBeforeUnmount(() => props.detach())
</script>
