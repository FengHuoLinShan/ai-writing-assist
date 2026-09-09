<script setup>
import { computed } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"

const props = defineProps({
  open: Boolean,
  title: { type: String, default: "加入主题" },
  topics: { type: Array, default: () => [] },
  targetTitle: { type: String, default: "" },
  memberTopicIds: { type: Array, default: () => [] },
})
const emit = defineEmits(["close", "toggle"])
const close = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open, requestClose: close })

const memberSet = computed(() => new Set(props.memberTopicIds))

function flatten(nodes, depth = 0) {
  const rows = []
  for (const node of nodes || []) {
    rows.push({ ...node, depth })
    rows.push(...flatten(node.children || [], depth + 1))
  }
  return rows
}
const topicRows = computed(() => flatten(props.topics))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="overlayRef" class="modal-overlay" @click.self="close" @keydown="onKeydown" @focusin="onFocusin">
      <section ref="dialogRef" class="modal-content world-topic-picker" role="dialog" aria-modal="true" aria-labelledby="world-topic-picker-title" tabindex="-1">
        <header class="modal-header">
          <h2 id="world-topic-picker-title">{{ title }}</h2>
          <button type="button" class="btn-icon" aria-label="关闭" @click="close">×</button>
        </header>
        <div class="modal-body">
          <p class="world-topic-picker__target">正在整理：<strong>{{ targetTitle || "未命名资料" }}</strong></p>
          <p v-if="!topicRows.length" class="world-topic-picker__empty">还没有主题，请先在资料目录里新建一个主题。</p>
          <ul v-else class="world-topic-picker__list">
            <li v-for="topic in topicRows" :key="topic.id" :style="{ paddingLeft: `${8 + topic.depth * 18}px` }">
              <button
                type="button"
                :aria-pressed="memberSet.has(topic.id) ? 'true' : 'false'"
                :data-topic-id="topic.id"
                @click="emit('toggle', topic)"
              >
                <span aria-hidden="true">{{ memberSet.has(topic.id) ? "✓" : "＋" }}</span>
                <span>{{ topic.name }}</span>
                <small v-if="topic.status === 'archived'">已归档</small>
              </button>
            </li>
          </ul>
        </div>
        <footer class="modal-footer"><button type="button" class="btn" data-action="world-topic-picker-done" @click="close">完成</button></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.world-topic-picker { max-width: 440px; max-height: min(600px, calc(100vh - 32px)); }
.world-topic-picker__target { margin: 0 0 10px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-topic-picker__empty { margin: 0; color: var(--text-muted); }
.world-topic-picker__list { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.world-topic-picker__list button { display: flex; width: 100%; min-height: 44px; align-items: center; gap: 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-panel); color: var(--text-primary); padding: 8px 12px; text-align: left; cursor: pointer; }
.world-topic-picker__list button:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-topic-picker__list button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
.world-topic-picker__list small { margin-left: auto; color: var(--text-muted); }
</style>
