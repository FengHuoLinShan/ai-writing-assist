<template>
  <div v-if="open" ref="overlayRef" class="world-change-history-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="world-change-history" role="dialog" aria-modal="true" aria-label="改动记录" tabindex="-1">
      <header class="world-change-history__header">
        <h2>改动记录</h2>
        <button type="button" class="btn-icon" aria-label="关闭改动记录" data-action="change-history-close" @click="close">×</button>
      </header>
      <div class="world-change-history__filters" role="group" aria-label="按类型筛选改动">
        <button
          v-for="option in FILTERS"
          :key="option.value"
          type="button"
          class="btn btn-sm"
          :aria-pressed="state.filter === option.value"
          :data-filter="option.value"
          @click="setFilter(option.value)"
        >{{ option.label }}</button>
      </div>
      <div ref="scrollRef" class="world-change-history__list" @scroll="onScroll">
        <template v-if="!state.items.length && state.error">
          <p role="alert">{{ state.error }}</p>
          <button type="button" class="btn" data-action="change-history-retry" :disabled="loading" @click="refresh">重试</button>
        </template>
        <p v-else-if="loading && !state.items.length" role="status">正在读取改动记录…</p>
        <p v-else-if="!state.items.length">还没有改动记录</p>
        <template v-else>
          <article
            v-for="item in state.items"
            :key="`${item.kind}:${item.revision_id}`"
            class="world-change-history__item"
            :data-change-kind="item.kind"
          >
            <header class="world-change-history__meta">
              <span class="muted" :title="formatFullTime(item.created_at)">{{ formatRelativeTime(item.created_at) }}</span>
              <span class="pill">{{ kindLabel(item.kind) }}</span>
              <span v-if="item.reason" class="pill">{{ revisionReasonLabel(item.reason) }}</span>
              <span v-if="progressText(item)" class="muted">{{ progressText(item) }}</span>
            </header>
            <p class="world-change-history__title">
              {{ item.target_title || '未命名对象' }}
              <span v-if="item.target_state === 'removed'" class="pill">已移除</span>
              <span v-if="item.version_number" class="muted">第 {{ item.version_number }} 版</span>
            </p>
            <p v-if="changedText(item)">改动：{{ changedText(item) }}</p>
            <p v-if="item.change_note" class="muted">备注：{{ item.change_note }}</p>
            <div class="row-actions">
              <button type="button" class="btn btn-sm" :data-jump="`${item.kind}:${item.revision_id}`" @click="jump(item)">查看</button>
            </div>
          </article>
          <p v-if="state.error" role="alert">{{ state.error }}</p>
          <button
            v-if="state.nextCursor"
            type="button"
            class="btn"
            data-action="change-history-more"
            :disabled="loading"
            @click="loadMore"
          >{{ loading ? '正在读取…' : '加载更多' }}</button>
          <p v-else class="muted">没有更多了</p>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * WorldChangeHistory — 世界页「改动记录」浮层。
 *
 * 合并实体改动、世界书页面发布与地图保存，按时间倒序、游标翻页；
 * 筛选、已加载条目、游标与滚动位置按作品存 worldSession.changeHistory，
 * 跳转到具体对象后返回（open=change-history 深链）恢复原状态；
 * 迟到响应按 session 内 queryEpoch 丢弃，不覆盖新查询。
 */
import { nextTick, ref, watch } from "vue"
import { getApi, getRouter } from "../../../bridge/index.js"
import { useModalDialog } from "../../../composables/useModalDialog.js"
import { worldSession as session } from "../worldSession.js"
import {
  formatChangedFields,
  formatFullTime,
  formatRelativeTime,
  formatWritingProgress,
  revisionReasonLabel,
} from "../../../../shared/revisionHistory.js"

const props = defineProps({
  projectId: { type: String, required: true },
  open: { type: Boolean, default: false },
})
const emit = defineEmits(["close"])

const FILTERS = [
  { value: "all", label: "全部" },
  { value: "entity", label: "设定" },
  { value: "page", label: "世界书" },
  { value: "map", label: "地图" },
]
const KIND_LABELS = { entity: "设定", page: "世界书", map: "地图" }

const state = session.changeHistory
const loading = ref(false)
const scrollRef = ref(null)

function kindLabel(kind) {
  return KIND_LABELS[kind] || "其他"
}
function progressText(item) {
  return formatWritingProgress(item?.writing_chapter_index)
}
function changedText(item) {
  return formatChangedFields(item?.changed_fields)
}

async function query(append = false) {
  const epoch = ++state.queryEpoch
  loading.value = true
  try {
    const result = await getApi().world.listWorldChangeHistory(props.projectId, {
      kinds: state.filter === "all" ? undefined : [state.filter],
      cursor: append ? state.nextCursor : undefined,
      limit: 30,
    })
    if (epoch !== state.queryEpoch) return
    const items = Array.isArray(result?.items) ? result.items : []
    state.items = append ? [...state.items, ...items] : items
    state.nextCursor = result?.next_cursor || null
    state.error = null
  } catch (err) {
    if (epoch !== state.queryEpoch) return
    if (!append) state.items = []
    state.error = err?.message || "改动记录加载失败，请重试"
  } finally {
    if (epoch === state.queryEpoch) loading.value = false
  }
}

function refresh() {
  return query(false)
}
function loadMore() {
  if (!state.nextCursor) return
  return query(true)
}

function setFilter(filter) {
  if (state.filter === filter) return
  state.filter = filter
  state.items = []
  state.nextCursor = null
  state.error = null
  state.scrollTop = 0
  void query(false)
}

function onScroll() {
  state.scrollTop = scrollRef.value?.scrollTop || 0
}

async function jump(item) {
  onScroll()
  const router = getRouter()
  if (item.kind === "entity") {
    const query = new URLSearchParams({ entity_id: item.target_id, open: "history", revision_id: item.revision_id })
    router?.navigate("world", "bible", true, query)
    return
  }
  if (item.kind === "page") {
    const query = new URLSearchParams({ page_id: item.target_id, history: "1", history_version: String(item.version_number || "") })
    router?.navigate("world", "bible", true, query)
    return
  }
  if (item.kind === "map") {
    const query = new URLSearchParams({ node_id: item.target_id, revision_id: item.revision_id })
    router?.navigate("map", null, true, query)
  }
}

function close() {
  state.open = false
  emit("close")
}

const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({
  isOpen: () => props.open,
  requestClose: close,
})

watch(() => [props.open, props.projectId], async ([open]) => {
  if (!open) return
  if (!state.items.length && !state.error && !loading.value) await query(false)
  await nextTick()
  if (scrollRef.value) scrollRef.value.scrollTop = state.scrollTop || 0
}, { immediate: true })
</script>

<style scoped>
.world-change-history-overlay { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center; background: rgba(15, 23, 42, 0.45); padding: 16px; }
.world-change-history { display: flex; flex-direction: column; gap: 12px; width: min(560px, 100%); max-height: min(640px, 90vh); background: var(--bg-panel, var(--bg)); color: var(--text); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; }
.world-change-history__header { display: flex; align-items: center; justify-content: space-between; }
.world-change-history__header h2 { margin: 0; font-size: 1.1rem; }
.world-change-history__filters { display: flex; flex-wrap: wrap; gap: 8px; }
.world-change-history__list { overflow-y: auto; display: grid; gap: 10px; padding-right: 4px; }
.world-change-history__item { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; display: grid; gap: 6px; }
.world-change-history__meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.world-change-history__title { margin: 0; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-weight: 600; }
.world-change-history__item p { margin: 0; }
@media (max-width: 760px) {
  .world-change-history-overlay { padding: 0; align-items: stretch; }
  .world-change-history { width: 100%; max-height: 100vh; height: 100%; border-radius: 0; }
  .world-change-history__filters .btn, .world-change-history__item .btn { min-height: 44px; }
}
</style>
