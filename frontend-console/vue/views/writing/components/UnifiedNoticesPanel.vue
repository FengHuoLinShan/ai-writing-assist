<template>
  <section class="unified-notices" aria-label="统一提醒">
    <header class="unified-notices__header">
      <div>
        <p class="unified-notices__eyebrow">本章与本场</p>
        <h3>提醒</h3>
      </div>
      <button type="button" class="btn btn-sm" :disabled="loading" @click="loadNotices">
        {{ loading ? "读取中…" : "重新读取" }}
      </button>
    </header>

    <p v-if="unsaved" class="unified-notices__saved-basis" role="status">
      正文有未保存修改；这些提醒只按服务器已保存资料核对，本地缓冲区不会作为服务端依据。
    </p>
    <p v-if="error" class="unified-notices__error" role="alert">{{ error }}</p>
    <p v-if="actionMessage" class="unified-notices__message" role="status">{{ actionMessage }}</p>

    <p v-if="loading && !response" class="unified-notices__empty" role="status">正在读取当前范围的提醒…</p>
    <section v-if="response?.unavailable_sources?.length" class="unified-notices__unavailable" aria-label="暂不可读的提醒来源">
      <article v-for="source in response.unavailable_sources" :key="source.source_id" class="unified-notices__unavailable-card" role="status">
        <strong>{{ sourceLabel(source.source_id, source.label) }}</strong>
        <p>{{ source.message || "暂时无法读取" }}；这不代表该来源没有待处理内容。</p>
      </article>
    </section>

    <section v-for="group in groups" :key="group.key" class="unified-notices__group">
      <details :open="group.hasPriority">
        <summary>
          <span>{{ groupLabel(group) }}</span>
          <small>{{ group.items.length }} 项</small>
        </summary>
        <div class="unified-notices__group-actions">
          <button
            v-if="!readOnly"
            type="button"
            class="btn btn-sm btn-ghost"
            :disabled="busyKey !== null"
            @click="setCategoryMute(group.sourceId, group.category, true)"
          >静音此类提醒</button>
        </div>
        <article
          v-for="item in group.items"
          :key="item.notice_key"
          class="unified-notices__item"
          :class="`unified-notices__item--${item.severity}`"
        >
          <div class="unified-notices__item-head">
            <span class="unified-notices__severity" :data-severity="item.severity">{{ severityLabel(item.severity) }}</span>
            <span v-if="item.status !== 'unread'" class="unified-notices__status">{{ statusLabel(item.status) }}</span>
            <span v-if="staleLabel(item)" class="unified-notices__stale">{{ staleLabel(item) }}</span>
          </div>
          <p class="unified-notices__summary">{{ item.summary }}</p>
          <details v-if="item.evidence?.length" class="unified-notices__evidence">
            <summary>查看依据（{{ item.evidence.length }}）</summary>
            <ul>
              <li v-for="(evidence, index) in item.evidence" :key="index">{{ evidenceLabel(evidence) }}</li>
            </ul>
          </details>
          <div class="unified-notices__actions">
            <button v-if="canOpen(item)" type="button" class="btn btn-sm" @click="emit('open-notice', item)">{{ openActionLabel(item) }}</button>
            <template v-if="!readOnly">
              <button
                v-if="item.status === 'unread'"
                type="button"
                class="btn btn-sm btn-ghost"
                :disabled="busyKey !== null"
                @click="setDisposition(item, 'read')"
              >{{ busyKey === item.notice_key ? "保存中…" : "标为已读" }}</button>
              <button
                type="button"
                class="btn btn-sm btn-ghost"
                :disabled="busyKey !== null"
                @click="setDisposition(item, 'snooze')"
              >{{ busyKey === item.notice_key ? "保存中…" : "明天提醒" }}</button>
              <button
                type="button"
                class="btn btn-sm btn-ghost"
                :disabled="busyKey !== null"
                @click="setDisposition(item, 'ignore')"
              >{{ busyKey === item.notice_key ? "保存中…" : ignoreLabel(item) }}</button>
            </template>
          </div>
        </article>
      </details>
    </section>

    <details v-if="mutedCategories.length" class="unified-notices__muted">
      <summary>已静音类别 · {{ mutedCategories.length }}</summary>
      <div v-for="mute in mutedCategories" :key="`${mute.source_id}:${mute.category}`" class="unified-notices__mute-row">
        <span>{{ sourceLabel(mute.source_id) }} · {{ categoryLabel(mute.category) }}</span>
        <button
          v-if="!readOnly"
          type="button"
          class="btn btn-sm btn-ghost"
          :disabled="busyKey !== null"
          @click="setCategoryMute(mute.source_id, mute.category, false, mute.row_version)"
        >恢复提醒</button>
        <span v-else class="unified-notices__read-only">只读</span>
      </div>
    </details>

    <p v-if="response && !groups.length && !response.unavailable_sources?.length" class="unified-notices__empty">
      当前范围暂无待处理提醒，已读取来源均有返回。
    </p>
    <p v-if="response?.partial" class="unified-notices__partial" role="status">
      部分来源暂不可读；列表只展示已成功读取的来源，不能据此判断整个范围已清空。
    </p>
    <p v-if="readOnly" class="unified-notices__read-only" role="status">当前为只读视图；已读、稍后、忽略和类别静音不会写入。</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, default: null },
  sceneId: { type: String, default: null },
  chapterIndex: { type: Number, default: null },
  unsaved: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(["open-notice"])

const response = ref(null)
const loading = ref(false)
const error = ref("")
const actionMessage = ref("")
const busyKey = ref(null)
let generation = 0
let controller = null

const groups = computed(() => {
  const byKey = new Map()
  const items = response.value?.items || []
  const directEditorialIds = new Set(items
    .filter((item) => item.source_id === "assistant.editorial")
    .map((item) => item.actions?.find((action) => action.editorial === true)?.issue_id)
    .filter(Boolean))
  for (const item of items) {
    const legacyIssueId = item.source_id === "assistant.proactive"
      ? item.actions?.find((action) => action.editorial === true)?.issue_id
      : null
    // Keep the existing AssistantNotice projection if the domain issue source
    // failed; suppress it only when the same issue is readable from its owner.
    if (legacyIssueId && directEditorialIds.has(legacyIssueId)) continue
    const key = `${item.source_id}\u001f${item.category}`
    if (!byKey.has(key)) byKey.set(key, { key, sourceId: item.source_id, category: item.category, items: [] })
    byKey.get(key).items.push(item)
  }
  return [...byKey.values()].map((group) => {
    group.items.sort((left, right) => severityOrder(left.severity) - severityOrder(right.severity))
    group.hasPriority = group.items.some((item) => ["high", "medium"].includes(item.severity))
    return group
  }).sort((left, right) => (
    severityOrder(left.items[0]?.severity) - severityOrder(right.items[0]?.severity)
    || left.sourceId.localeCompare(right.sourceId)
    || left.category.localeCompare(right.category)
  ))
})
const mutedCategories = computed(() => response.value?.muted_categories || [])

function groupLabel(group) {
  const source = sourceLabel(group.sourceId, "", group.category)
  const category = categoryLabel(group.category)
  return source === category ? source : `${source} · ${category}`
}

function current(token, projectId, sceneId, chapterIndex) {
  return token === generation
    && projectId === props.projectId
    && sceneId === props.sceneId
    && chapterIndex === props.chapterIndex
}

async function loadNotices({ keepActionMessage = false } = {}) {
  const projectId = props.projectId
  const sceneId = props.sceneId
  const chapterIndex = props.chapterIndex
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  const token = ++generation
  response.value = null
  loading.value = Boolean(projectId && (sceneId || chapterIndex))
  error.value = ""
  if (!keepActionMessage) actionMessage.value = ""
  if (!projectId || (!sceneId && !chapterIndex)) {
    loading.value = false
    return
  }
  try {
    const result = await getApi().assistant.unifiedNotices(projectId, {
      sceneId,
      chapterIndex,
      signal: requestController.signal,
    })
    if (current(token, projectId, sceneId, chapterIndex)) {
      response.value = result
    }
  } catch (failure) {
    if (current(token, projectId, sceneId, chapterIndex) && failure?.name !== "AbortError") {
      error.value = failure?.message || "提醒暂时无法读取，请重试。"
    }
  } finally {
    if (current(token, projectId, sceneId, chapterIndex)) loading.value = false
  }
}

async function setDisposition(item, action) {
  if (props.readOnly || busyKey.value || !item?.basis_fingerprint) return
  const projectId = props.projectId
  const sceneId = props.sceneId
  const chapterIndex = props.chapterIndex
  const token = generation
  busyKey.value = item.notice_key
  error.value = ""
  actionMessage.value = ""
  try {
    await getApi().assistant.setUnifiedNoticeDisposition({
      novel_id: projectId,
      source_id: item.source_id,
      notice_key: item.notice_key,
      basis_fingerprint: item.basis_fingerprint,
      scope: { scene_id: sceneId, chapter_index: chapterIndex },
      expected_row_version: item.row_version,
      action,
      ...(action === "snooze" ? { duration_hours: 24 } : {}),
    })
    if (!current(token, projectId, sceneId, chapterIndex)) return
    actionMessage.value = action === "read"
      ? "已标为已读。"
      : action === "snooze" ? "已暂缓，明天会重新显示。" : "已按对应来源的处置规则处理。"
    busyKey.value = null
    await loadNotices({ keepActionMessage: true })
  } catch (failure) {
    if (!current(token, projectId, sceneId, chapterIndex)) return
    if (failure?.status === 409) {
      actionMessage.value = "提醒依据或版本已变化，正在按最新状态刷新。"
      busyKey.value = null
      await loadNotices({ keepActionMessage: true })
    } else {
      error.value = failure?.message || "保存提醒处置失败；当前内容仍保留。"
    }
  } finally {
    if (current(token, projectId, sceneId, chapterIndex)) busyKey.value = null
  }
}

async function setCategoryMute(sourceId, category, muted, rowVersion = 0) {
  if (props.readOnly || busyKey.value) return
  const projectId = props.projectId
  const sceneId = props.sceneId
  const chapterIndex = props.chapterIndex
  const token = generation
  const key = `category:${sourceId}:${category}`
  busyKey.value = key
  error.value = ""
  actionMessage.value = ""
  try {
    await getApi().assistant.setUnifiedNoticeCategoryMute(
      projectId, sourceId, category, rowVersion, muted,
    )
    if (!current(token, projectId, sceneId, chapterIndex)) return
    actionMessage.value = muted ? "此类别已静音。" : "此类别已恢复提醒。"
    busyKey.value = null
    await loadNotices({ keepActionMessage: true })
  } catch (failure) {
    if (!current(token, projectId, sceneId, chapterIndex)) return
    if (failure?.status === 409) {
      actionMessage.value = "类别设置已在其他位置变化，正在读取最新状态。"
      busyKey.value = null
      await loadNotices({ keepActionMessage: true })
    } else {
      error.value = failure?.message || "类别设置失败；当前内容仍保留。"
    }
  } finally {
    if (current(token, projectId, sceneId, chapterIndex)) busyKey.value = null
  }
}

const SOURCE_LABELS = {
  "assistant.proactive": "助手提醒",
  "assistant.forecast": "下一步建议",
  "assistant.editorial": "编辑员意见",
  "story.structure": "场景结构",
  "writing.conflict": "规则检查",
  "writing.invalidation": "正文变更",
  "world.map_source": "地图来源",
}
const CATEGORY_LABELS = {
  scene_structure: "场景结构",
  conflict_check: "规则检查",
  map_baseline: "地图依据",
  source_invalidation: "待重算内容",
  short_term_forecast: "短期前瞻",
  editorial_issue: "编辑员意见",
  map_source: "地图来源",
  map_source_coverage: "地图来源覆盖",
}
function sourceLabel(sourceId, fallback = "", category = "") {
  if (sourceId === "assistant.proactive" && category === "editorial_issue") return "编辑员意见"
  return SOURCE_LABELS[sourceId] || fallback || "其他来源"
}
function categoryLabel(category) { return CATEGORY_LABELS[category] || "其他提醒" }
function severityOrder(severity) { return ({ high: 0, medium: 1, low: 2, info: 3 })[severity] ?? 4 }
function severityLabel(severity) { return ({ high: "高", medium: "中", low: "低", info: "信息" })[severity] || "提醒" }
function statusLabel(status) { return ({ read: "已读", snoozed: "稍后", ignored: "已忽略" })[status] || "待处理" }
function staleLabel(item) {
  if (item.stale) return "依据已变化"
  if (props.unsaved && item.source_id === "writing.conflict") return "本地正文未保存"
  return ""
}
function ignoreLabel(item) {
  return item.source_id === "assistant.editorial"
    || item.actions?.some((action) => action.editorial === true)
    ? "按原决定关闭"
    : "忽略此项"
}
function openActionLabel(item) {
  return ({
    "assistant.forecast": "打开前瞻",
    "assistant.editorial": "查看编辑意见",
    "assistant.proactive": item.actions?.some((action) => action.editorial === true)
      ? "查看编辑意见"
      : item.actions?.some((action) => action.page === "map") ? "去地图核对" : "查看来源",
    "story.structure": "整理场景",
    "writing.conflict": "查看检查",
    "writing.invalidation": "查看重算选项",
    "world.map_source": "去地图核对",
  })[item.source_id] || "查看来源"
}
function canOpen(item) {
  if (["assistant.forecast", "assistant.editorial", "story.structure", "writing.conflict", "writing.invalidation", "world.map_source"].includes(item.source_id)) return true
  return item.source_id === "assistant.proactive"
    && item.actions?.some((action) => action.kind === "navigate" && (action.editorial === true || ["map", "writing", "outline", "world"].includes(action.page)))
}
function evidenceLabel(value) {
  const title = value?.map_title || value?.title || value?.label || ""
  const chapter = Number(value?.chapter_index)
  const note = value?.note || value?.summary || value?.reason || value?.coverage_note || ""
  const location = Number.isInteger(chapter) ? `第 ${chapter} 章` : ""
  return [title, location, note].filter(Boolean).join(" · ") || "来源记录已读取"
}

watch(() => [props.projectId, props.sceneId, props.chapterIndex], () => {
  busyKey.value = null
  void loadNotices()
}, { immediate: true })
onBeforeUnmount(() => { generation += 1; controller?.abort() })
</script>

<style scoped>
.unified-notices { display: grid; gap: 10px; min-width: 0; }
.unified-notices__header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.unified-notices__header h3 { margin: 2px 0 0; font-size: 15px; }
.unified-notices__eyebrow { margin: 0; color: var(--text-secondary); font-size: 11px; letter-spacing: .06em; }
.unified-notices__header button, .unified-notices__actions button, .unified-notices__group-actions button, .unified-notices__mute-row button { min-height: 34px; }
.unified-notices__saved-basis, .unified-notices__partial, .unified-notices__read-only { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.unified-notices__error { margin: 0; color: var(--danger, #b42318); overflow-wrap: anywhere; }
.unified-notices__message { margin: 0; color: var(--text-secondary); }
.unified-notices__empty { margin: 0; color: var(--text-secondary); }
.unified-notices__unavailable { display: grid; gap: 7px; }
.unified-notices__unavailable-card { border-left: 3px solid var(--warning, #a66a00); padding: 7px 9px; background: var(--warning-soft, rgba(176, 132, 32, .08)); }
.unified-notices__unavailable-card p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.unified-notices__group { border-top: 1px solid var(--border-color, var(--border)); }
.unified-notices__group > details > summary { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-height: 38px; cursor: pointer; font-size: 13px; font-weight: 650; }
.unified-notices__group > details > summary small { flex: none; color: var(--text-secondary); font-weight: 400; }
.unified-notices__group-actions { display: flex; justify-content: flex-end; padding: 0 0 6px; }
.unified-notices__item { display: grid; gap: 6px; margin: 6px 0; padding: 10px; border: 1px solid var(--border-color, var(--border)); border-radius: 8px; background: var(--bg-primary, var(--surface)); min-width: 0; }
.unified-notices__item--high { border-left: 3px solid var(--danger, #b42318); }
.unified-notices__item--medium { border-left: 3px solid var(--warning, #a66a00); }
.unified-notices__item-head, .unified-notices__actions, .unified-notices__mute-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.unified-notices__severity, .unified-notices__status, .unified-notices__stale { color: var(--text-secondary); font-size: 11px; }
.unified-notices__severity[data-severity="high"] { color: var(--danger, #b42318); }
.unified-notices__severity[data-severity="medium"] { color: var(--warning, #8a5b00); }
.unified-notices__stale { color: var(--warning, #8a5b00); }
.unified-notices__summary { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; line-height: 1.5; }
.unified-notices__evidence > summary { cursor: pointer; color: var(--text-secondary); font-size: 12px; min-height: 30px; padding-top: 4px; }
.unified-notices__evidence ul { margin: 4px 0; padding-left: 18px; font-size: 12px; color: var(--text-secondary); }
.unified-notices__evidence li { margin: 3px 0; overflow-wrap: anywhere; }
.unified-notices__actions { padding-top: 2px; }
.unified-notices__muted { border-top: 1px solid var(--border-color, var(--border)); padding-top: 8px; }
.unified-notices__muted > summary { cursor: pointer; min-height: 32px; }
.unified-notices__mute-row { justify-content: space-between; padding: 5px 0; font-size: 12px; }
@media (max-width: 520px) {
  .unified-notices__actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .unified-notices__actions button { white-space: normal; }
}
</style>
