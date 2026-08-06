<template>
  <div class="writing-editor-shell">
    <div class="writing-editor-header">
      <div class="writing-editor-title-group">
        <span id="writing-chapter-title" class="writing-editor-chapter-title">{{ state.chapter ? `第 ${state.chapter} 章` : '未选择章节' }}</span>
        <span v-if="hasChapter" id="writing-version-info" class="writing-version-badge">{{ versionLabel }}</span>
        <span v-if="hasChapter" id="writing-save-status" class="writing-save-badge" :class="saveBadgeClass">{{ saveStatus }}</span>
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
                <button class="btn btn-sm" @click="$emit('auto-extract', 'deep')">完整整理</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'scenes')">整理场景</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'world_objects')">整理人物、设定与关系</button>
                <button class="btn btn-sm" @click="$emit('auto-extract', 'plot_structure')">整理剧情线</button>
              </div>
            </div>
          </details>
          <details class="writing-tools-menu">
            <summary class="btn btn-sm" data-action="writing-more-menu">更多</summary>
            <div class="writing-tools-menu__body">
              <div class="writing-tools-menu__group">
                <button id="btn-conflict-check" class="btn btn-sm" :disabled="!hasChapter || state.readonly || conflictLoading" @click="$emit('conflict-check')">{{ conflictLoading ? '检查中...' : '检查前后设定' }}</button>
                <button class="btn btn-sm" :disabled="!hasChapter" @click="$emit('export')">导出本章</button>
                <button class="btn btn-sm" @click="$emit('open-map')">打开地图</button>
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
        <input
          id="writing-title-input"
          ref="titleEl"
          class="writing-title-input"
          type="text"
          :value="state.title"
          :readonly="state.readonly"
          placeholder="章节标题"
        >
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
              <div class="writing-pov-subtitle">建议尚未进入工作稿，请明确采用或拒绝。</div>
            </div>
          </div>
          <div class="writing-candidate-review-actions">
            <button class="btn btn-primary" @click="$emit('adopt')">采用到工作稿</button>
            <button class="btn btn-danger" @click="$emit('reject')">拒绝建议</button>
          </div>
        </section>

        <div id="writing-wordcount-bar" class="writing-wordcount-bar">
          <span><strong>{{ state.content.length.toLocaleString() }}</strong> 字</span>
          <span>{{ paragraphCount }} 段</span>
          <span>约 {{ readMinutes }} 分钟阅读</span>
          <span v-if="dailyGoal" class="wc-daily-goal">
            日目标 {{ state.content.length.toLocaleString() }} / {{ Number(dailyGoal).toLocaleString() }}
            <span class="wc-goal-progress" aria-hidden="true"><span class="wc-goal-fill" :style="{ width: `${goalPercent}%` }" /></span>
          </span>
        </div>
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
  hasChapters: { type: Boolean, default: false },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits([
  "autosave", "checkpoint", "conflict-check", "publish", "discard",
  "generate-draft", "generate-continuation", "generate-pov",
  "auto-extract", "adopt", "reject", "export", "open-map", "toggle-focus",
])

const titleEl = ref(null)
const editorEl = ref(null)
const hasChapter = computed(() => Number.isInteger(Number(props.state.chapter)) && Number(props.state.chapter) > 0)
const attachElements = () => props.attach({ title: titleEl.value, editor: editorEl.value })
onMounted(() => nextTick(attachElements))
watch(() => props.state.chapter, () => nextTick(attachElements))
onBeforeUnmount(() => props.detach())

const versionLabel = computed(() => props.state.versionNumber ? `v${props.state.versionNumber}${props.state.readonly ? '（只读）' : ''}` : "未选择版本")
const saveBadgeClass = computed(() => ({
  "writing-save-badge--saving": Boolean(props.state.saving),
  "writing-save-badge--unsaved": !props.state.saving && props.state.dirty,
  "writing-save-badge--saved": !props.state.saving && !props.state.dirty,
}) )
const paragraphCount = computed(() => String(props.state.content || "").replace(/\r\n?/g, "\n").split(/\n+/).filter((item) => item.trim()).length)
const readMinutes = computed(() => Math.max(1, Math.ceil(String(props.state.content || "").length / 300)))
const goalPercent = computed(() => {
  const goal = Number(props.dailyGoal)
  if (!Number.isFinite(goal) || goal <= 0) return 0
  return Math.min(100, Math.round((String(props.state.content || "").length / goal) * 100))
})
</script>
