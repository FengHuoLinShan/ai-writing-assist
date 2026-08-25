<template>
  <div v-if="model.open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="modal-content modal-content--wide writing-version-history-modal" role="dialog" aria-modal="true" aria-label="版本历史" aria-labelledby="version-history-dialog-title" :aria-busy="model.loading" tabindex="-1">
      <div class="modal-header">
        <h3 id="version-history-dialog-title">版本历史</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="close">×</button>
      </div>
      <div class="modal-body">
        <div class="writing-version-history-list">
          <article v-for="version in versions" :key="version.id" class="writing-version-history-item">
            <div class="writing-version-history-summary">
              <div>
                <strong>v{{ version.version_number }}</strong>
                <span class="pill">{{ statusLabel(version) }}</span>
                <span v-if="version.id === currentId" class="pill writing-version-current">当前打开</span>
                <span v-if="version.updated_at" class="muted writing-version-history-date">{{ formatTimestamp(version.updated_at) }}</span>
              </div>
              <p v-if="version.title || Number.isFinite(version.word_count)" class="muted">
                <span v-if="version.title">{{ version.title }}</span><span v-if="version.title && Number.isFinite(version.word_count)"> · </span><span v-if="Number.isFinite(version.word_count)">{{ version.word_count }} 字</span>
              </p>
            </div>
            <div class="row-actions">
              <button v-if="version.id !== currentId" type="button" class="btn btn-sm btn-primary" aria-label="与当前打开版本比较" :disabled="model.loading" @click="compareWithCurrent(version)">与当前版本比较</button>
              <button v-if="canManage(version)" type="button" class="btn btn-sm" :disabled="model.loading" @click="$emit('restore', version)">从此版本继续写</button>
              <ActionMenu
                v-if="menuItems(version).length"
                class="writing-version-history-menu"
                :menu-id="`writing-version-${version.id}`"
                :label="`版本 v${version.version_number} 的更多操作`"
                :items="menuItems(version)"
                trigger-text="更多"
                :disabled="model.loading"
                @select="handleMenu(version, $event)"
              />
            </div>
          </article>
        </div>
        <details v-if="versions.length >= 2" class="writing-version-compare">
          <summary>自选两个版本比较</summary>
          <div class="writing-version-diff-controls">
            <label>版本 A
              <select v-model="model.leftId" :disabled="model.loading">
                <option v-for="version in versions" :key="`l-${version.id}`" :value="version.id">v{{ version.version_number }} · {{ statusLabel(version) }}</option>
              </select>
            </label>
            <label>版本 B
              <select v-model="model.rightId" :disabled="model.loading">
                <option v-for="version in versions" :key="`r-${version.id}`" :value="version.id">v{{ version.version_number }} · {{ statusLabel(version) }}</option>
              </select>
            </label>
            <button type="button" class="btn btn-primary" :disabled="model.loading" @click="$emit('compare')">{{ model.loading ? '比较中...' : '查看差异' }}</button>
          </div>
        </details>
        <p v-if="model.error" role="alert" class="writing-empty-hint">{{ model.error }}</p>
        <div v-if="model.diffOpen && model.diff" ref="diffRef" class="writing-version-diff" tabindex="-1" aria-label="版本差异结果">
          <div class="writing-version-diff__stats">
            <span>版本 A {{ model.diff.stats.leftChars }} 字</span>
            <span>版本 B {{ model.diff.stats.rightChars }} 字</span>
            <span>修改 {{ model.diff.stats.changedParagraphs }} 段</span>
            <span>移动 {{ model.diff.stats.movedParagraphs }} 段</span>
          </div>
          <div v-if="model.diff.identical" class="writing-version-diff__identical">两个版本正文完全一致</div>
          <div v-if="model.diff.fallbackUsed" class="writing-version-diff__notice">章节较长，已使用安全降级对齐。</div>
          <div class="writing-version-diff__grid" role="table" aria-label="正文版本并排差异">
            <div class="writing-version-diff__header" role="columnheader">版本 A</div>
            <div class="writing-version-diff__header" role="columnheader">版本 B</div>
            <template v-for="(row, index) in model.diff.rows" :key="index">
              <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell" data-side="版本 A">
                <template v-if="row.leftSegments?.length">
                  <component :is="segment.type === 'delete' ? 'mark' : 'span'" v-for="(segment, i) in row.leftSegments" :key="i" :class="{ 'writing-version-diff__removed': segment.type === 'delete' }">{{ segment.text }}</component>
                </template>
                <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
              </div>
              <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell" data-side="版本 B">
                <template v-if="row.rightSegments?.length">
                  <component :is="segment.type === 'insert' ? 'mark' : 'span'" v-for="(segment, i) in row.rightSegments" :key="i" :class="{ 'writing-version-diff__added': segment.type === 'insert' }">{{ segment.text }}</component>
                </template>
                <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import ActionMenu from "../../../components/ActionMenu.vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"
const props = defineProps({
  model: { type: Object, required: true },
  versions: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
})
const emit = defineEmits(["preview", "restore", "delete", "compare"])
const diffRef = ref(null)
const close = () => { props.model.open = false; props.model.diffOpen = false }
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.model.open, requestClose: close })
const isActive = (version) => version.display_state ? version.display_state === "active" : !["candidate", "deprecated"].includes(version.status)
const activeVersions = computed(() => props.versions.filter(isActive))
const latestActiveId = computed(() => activeVersions.value.reduce((latest, version) => Number(version.version_number) > Number(latest?.version_number || 0) ? version : latest, null)?.id || null)
const canManage = (version) => isActive(version) && activeVersions.value.length > 1 && version.id !== latestActiveId.value
const statusLabel = (version) => version.status === "published" ? "正式正文" : version.status === "candidate" ? "待处理" : version.status === "deprecated" ? "历史" : "工作稿"
const menuItems = (version) => [
  ...(version.id !== props.currentId ? [{ action: "preview", label: "单独预览" }] : []),
  ...(canManage(version) ? [{ action: "delete", label: "移入历史", class: "danger" }] : []),
]
function compareWithCurrent(version) {
  props.model.leftId = version.id
  props.model.rightId = props.currentId
  emit("compare")
}
function handleMenu(version, item) {
  if (item.action === "preview") emit("preview", version.id)
  else if (item.action === "delete") emit("delete", version)
}
watch(() => props.model.diffOpen, async (open) => {
  if (!open) return
  await nextTick()
  diffRef.value?.focus()
})
function formatTimestamp(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (number) => String(number).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>
