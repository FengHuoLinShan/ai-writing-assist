<template>
  <details ref="panel" class="story-fact-timeline" @toggle="onToggle">
    <summary class="story-fact-timeline__summary">
      <span>
        <strong>已发生事实时间线</strong>
        <small>作者视角 · 来自已记录事件</small>
      </span>
      <span class="story-fact-timeline__summary-count">{{ result?.total ?? 0 }} 条</span>
    </summary>

    <div class="story-fact-timeline__body" :aria-busy="loading ? 'true' : 'false'">
      <p class="story-fact-timeline__intro">这里只读取 Story 已记录的事实事件，不会把伏笔、揭示安排或篇章计划当作已发生事实。选择 Scene 截止时间后，只显示该 Scene 及之前可确认的事件。</p>
      <p v-if="error" class="story-fact-timeline__error" role="alert">{{ error }}</p>
      <p v-if="result?.pending_revalidations?.length" class="story-fact-timeline__pending" role="status">
        <strong>{{ result.pending_revalidations.length }} 项计划仍待重验</strong>
        <span>章节顺序变化后，以下计划锚点已迁移；请在对应计划页面核对。</span>
      </p>
      <ul v-if="result?.pending_revalidations?.length" class="story-fact-timeline__pending-list">
        <li v-for="(item, index) in result.pending_revalidations" :key="`${item.receipt_id}-${item.target_type}-${item.target_id}-${index}`">
          <strong>{{ item.label || typeLabel(item.target_type) }}</strong>
          <span>{{ formatAnchors(item.before) }} → {{ formatAnchors(item.after) }}</span>
        </li>
      </ul>

      <form class="story-fact-timeline__filters" @submit.prevent="loadFacts(true)">
        <label>
          <span>截止 Scene</span>
          <select v-model="filters.cutoffSceneId">
            <option value="">全部可确认时间</option>
            <option v-for="scene in result?.scene_options || []" :key="scene.scene_id" :value="scene.scene_id">
              {{ scene.title || `Scene ${scene.scene_index}` }} · 顺序 {{ scene.scene_index }}
            </option>
          </select>
        </label>
        <label>
          <span>对象</span>
          <select v-model="filters.entityId">
            <option value="">全部对象</option>
            <option v-for="(entity, index) in entityOptions" :key="entity.entity_id" :value="entity.entity_id">
              {{ entity.label }}{{ entityCounts[entity.label] > 1 ? ` ${index + 1}` : '' }} · {{ entity.entity_type || '类型未知' }}
            </option>
          </select>
        </label>
        <label>
          <span>来源</span>
          <select v-model="filters.source">
            <option value="">全部来源</option>
            <option v-for="source in result?.source_options || []" :key="source" :value="source">{{ sourceLabel(source) }}</option>
          </select>
        </label>
        <label>
          <span>时间状态</span>
          <select v-model="filters.status">
            <option value="">全部状态</option>
            <option value="current">时间可确认</option>
            <option value="stale">待重验</option>
            <option value="unknown">时间未知</option>
          </select>
        </label>
        <button type="submit" class="btn btn-sm" :disabled="loading">{{ loading ? '读取中…' : '应用筛选' }}</button>
      </form>

      <p v-if="result?.unknown_time_count" class="story-fact-timeline__unknown" role="status">
        {{ result.unknown_time_count }} 条事件没有可确认的 Scene 时间；列表会将它们标为未知，无法按截止时间推断先后。
      </p>
      <p v-if="!loading && !(result?.items || []).length" class="story-fact-timeline__empty">当前筛选下没有事实事件。</p>

      <ol v-if="result?.items?.length" class="story-fact-timeline__events" aria-label="事实事件">
        <li v-for="event in result.items" :key="event.id" class="story-fact-timeline__event">
          <div class="story-fact-timeline__event-head">
            <span class="story-fact-timeline__event-type">{{ eventLabel(event.event_type) }}</span>
            <span class="story-fact-timeline__status" :class="`is-${event.time_status}`">{{ statusLabel(event.time_status) }}</span>
          </div>
          <p class="story-fact-timeline__position">
            <template v-if="event.current_scene_index != null">Scene {{ event.current_scene_index }}</template>
            <template v-if="event.current_chapter_index != null"> · 第 {{ event.current_chapter_index }} 章</template>
            <template v-if="event.entity_label"> · {{ event.entity_label }}</template>
            <template v-else-if="event.entity_type"> · {{ entityTypeLabel(event.entity_type) }}</template>
            · {{ sourceLabel(event.source) }}
            <template v-if="event.created_at"> · {{ formatDate(event.created_at) }}</template>
          </p>
          <p v-if="event.dimension" class="story-fact-timeline__dimension">{{ dimensionLabel(event.dimension) }}</p>
          <dl v-if="eventFields(event.snapshot_after).length" class="story-fact-timeline__values">
            <div v-for="field in eventFields(event.snapshot_after)" :key="field.key">
              <dt>{{ field.key }}</dt><dd>{{ field.value }}</dd>
            </div>
          </dl>
          <details v-if="event.snapshot_before" class="story-fact-timeline__before">
            <summary>查看事件前状态</summary>
            <dl v-if="eventFields(event.snapshot_before).length" class="story-fact-timeline__values">
              <div v-for="field in eventFields(event.snapshot_before)" :key="field.key">
                <dt>{{ field.key }}</dt><dd>{{ field.value }}</dd>
              </div>
            </dl>
          </details>
        </li>
      </ol>

      <footer v-if="result?.total > pageSize" class="story-fact-timeline__pagination">
        <span>第 {{ pageStart + 1 }}–{{ Math.min(pageStart + pageSize, result.total) }} 条，共 {{ result.total }} 条</span>
        <div>
          <button type="button" class="btn btn-sm" :disabled="loading || pageStart === 0" @click="previousPage">上一页</button>
          <button type="button" class="btn btn-sm" :disabled="loading || pageStart + pageSize >= result.total" @click="nextPage">下一页</button>
        </div>
      </footer>
    </div>
  </details>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({ projectId: { type: String, default: null } })
const panel = ref(null)
const pageSize = 50
const pageStart = ref(0)
const result = ref(null)
const loading = ref(false)
const loaded = ref(false)
const error = ref("")
const requestGeneration = ref(0)
const filters = reactive({ cutoffSceneId: "", entityId: "", source: "", status: "" })

const entityOptions = computed(() => result.value?.entity_options || [])
const entityCounts = computed(() => entityOptions.value.reduce((counts, entity) => {
  counts[entity.label] = (counts[entity.label] || 0) + 1
  return counts
}, {}))

watch(() => props.projectId, async () => {
  const wasOpen = Boolean(panel.value?.open)
  requestGeneration.value += 1
  loading.value = false
  result.value = null
  loaded.value = false
  pageStart.value = 0
  filters.cutoffSceneId = ""
  filters.entityId = ""
  filters.source = ""
  filters.status = ""
  error.value = ""
  if (wasOpen) {
    await Promise.resolve()
    void loadFacts(true)
  }
})

function onToggle(event) {
  if (event.currentTarget.open && !loaded.value) void loadFacts(true)
}

async function loadFacts(reset = false) {
  const projectId = props.projectId
  if (!projectId || loading.value) return
  if (reset) pageStart.value = 0
  const generation = ++requestGeneration.value
  loading.value = true
  error.value = ""
  try {
    const next = await getApi().storyTimeline.listFacts(projectId, {
      entityId: filters.entityId || null,
      cutoffSceneId: filters.cutoffSceneId || null,
      source: filters.source || null,
      status: filters.status || null,
      skip: pageStart.value,
      limit: pageSize,
    })
    if (generation !== requestGeneration.value || props.projectId !== projectId) return
    result.value = next
    loaded.value = true
  } catch (cause) {
    if (generation !== requestGeneration.value || props.projectId !== projectId) return
    error.value = cause?.message || "事实时间线读取失败。筛选条件和当前页面仍保留，可以重试。"
  } finally {
    if (generation === requestGeneration.value) loading.value = false
  }
}

function previousPage() {
  pageStart.value = Math.max(0, pageStart.value - pageSize)
  void loadFacts()
}

function nextPage() {
  pageStart.value += pageSize
  void loadFacts()
}

function eventFields(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return []
  const fields = []
  const visit = (record, prefix = "", depth = 0) => {
    if (!record || typeof record !== "object" || depth > 3) return
    for (const [key, item] of Object.entries(record).slice(0, 20)) {
      const label = fieldLabel(key)
      if (item && typeof item === "object" && !Array.isArray(item)) {
        visit(item, prefix ? `${prefix} · ${label}` : label, depth + 1)
      } else {
        fields.push({
          key: prefix ? `${prefix} · ${label}` : label,
          value: formatValue(item),
        })
      }
      if (fields.length >= 12) return
    }
  }
  visit(value)
  return fields
}

function formatValue(value) {
  if (Array.isArray(value)) return value.slice(0, 8).map(formatValue).join("、") || "暂无"
  if (value && typeof value === "object") return "包含多项信息"
  return String(value ?? "未知").slice(0, 240)
}

function formatAnchors(anchors = {}) {
  return Object.entries(anchors).map(([field, value]) => `${fieldLabel(field)}：${formatValue(value)}`).join("；") || "章节锚点不变"
}

function fieldLabel(field) {
  return ({
    start_chapter: "起始章",
    end_chapter: "结束章",
    planned_seed_chapter: "埋设章",
    planned_payoff_chapter: "兑现章",
    planned_reinforce_chapters: "强化章",
    reveal_stages: "揭示阶段",
})[field] || "章节安排"
}

function typeLabel(type) {
  return ({ plot_thread: "剧情线", outline_arc: "篇章", foreshadowing_plan: "伏笔计划", reveal_plan: "揭示计划" })[type] || "计划"
}

function sourceLabel(source) {
  return ({ author: "作者确认", manual: "作者编辑", manual_edit: "作者编辑", ai_extraction: "正文整理", deep_import: "导入整理", system: "系统记录", system_generated: "系统生成", evolution: "进度整理", derived: "派生记录" })[source] || "其他来源"
}

function entityTypeLabel(value) {
  return ({ character: "人物", place: "地点", item: "物品", organization: "组织", event: "事件", concept: "概念", rule: "规则" })[value] || "对象"
}

function dimensionLabel(value) {
  return ({ entities: "对象变化", relations: "关系变化", locations: "位置变化", knowledge: "知识变化", timeline: "时间线变化", causality: "因果变化" })[value] || "事实记录"
}

function statusLabel(status) {
  return ({ current: "时间可确认", stale: "待重验", unknown: "时间未知" })[status] || "状态未知"
}

function eventLabel(eventType) {
  return ({ entity_created: "对象创建", entity_updated: "对象变化", entity_removed: "对象移除", entity_moved: "位置变化", relation_established: "关系建立", relation_ended: "关系结束", knowledge_changed: "知识变化", timeline_changed: "时间变化", causality_changed: "因果变化", manual_correction: "作者修正" })[eventType] || "已记录事件"
}

function formatDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN")
}
</script>

<style scoped>
.story-fact-timeline { margin: 1rem 0; border: 1px solid var(--border-subtle, #d8e0e4); border-radius: .9rem; background: var(--surface-primary, #fff); }
.story-fact-timeline__summary { display: flex; align-items: center; justify-content: space-between; gap: 1rem; min-height: 3.5rem; padding: .8rem 1rem; cursor: pointer; list-style: none; }
.story-fact-timeline__summary::-webkit-details-marker { display: none; }
.story-fact-timeline__summary > span:first-child { display: grid; gap: .2rem; }
.story-fact-timeline__summary small,
.story-fact-timeline__summary-count { color: var(--text-secondary, #59676e); }
.story-fact-timeline__body { display: grid; gap: .85rem; padding: 0 1rem 1rem; }
.story-fact-timeline__intro { max-width: 75ch; margin: 0; color: var(--text-secondary, #59676e); line-height: 1.5; }
.story-fact-timeline__filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr)); align-items: end; gap: .65rem; }
.story-fact-timeline__filters label { display: grid; min-width: 0; gap: .28rem; font-size: .84rem; font-weight: 600; }
.story-fact-timeline__filters select { width: 100%; min-height: 2.75rem; }
.story-fact-timeline__filters button { min-height: 2.75rem; }
.story-fact-timeline__pending,
.story-fact-timeline__unknown,
.story-fact-timeline__error { margin: 0; padding: .65rem .75rem; border-radius: .6rem; background: var(--surface-secondary, #f7f9f8); }
.story-fact-timeline__pending { display: grid; gap: .2rem; border-left: 3px solid var(--status-warning, #a86613); }
.story-fact-timeline__pending span,
.story-fact-timeline__unknown { color: var(--text-secondary, #59676e); }
.story-fact-timeline__pending-list { display: grid; gap: .4rem; margin: 0; padding: 0; list-style: none; }
.story-fact-timeline__pending-list li { display: grid; gap: .2rem; padding: .55rem .65rem; border-left: 2px solid var(--status-warning, #a86613); background: var(--surface-secondary, #f7f9f8); }
.story-fact-timeline__pending-list span { color: var(--text-secondary, #59676e); overflow-wrap: anywhere; }
.story-fact-timeline__error { color: var(--status-danger-text, #872d2d); background: var(--status-danger-bg, #fff0ed); }
.story-fact-timeline__events { display: grid; gap: .65rem; margin: 0; padding: 0; list-style: none; }
.story-fact-timeline__event { display: grid; gap: .35rem; padding: .75rem; border: 1px solid var(--border-subtle, #d8e0e4); border-radius: .75rem; }
.story-fact-timeline__event-head { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.story-fact-timeline__event-type { font-weight: 700; }
.story-fact-timeline__status { padding: .15rem .45rem; border-radius: 99px; color: var(--text-secondary, #59676e); background: var(--surface-secondary, #f7f9f8); font-size: .75rem; }
.story-fact-timeline__status.is-stale { color: var(--status-warning-text, #6a450d); background: var(--status-warning-bg, #fff5df); }
.story-fact-timeline__status.is-unknown { color: var(--text-secondary, #59676e); background: var(--surface-secondary, #f7f9f8); }
.story-fact-timeline__position { margin: 0; color: var(--text-secondary, #59676e); font-size: .82rem; }
.story-fact-timeline__dimension { margin: 0; color: var(--text-secondary, #59676e); font-size: .78rem; }
.story-fact-timeline__values { display: grid; gap: .25rem; margin: .2rem 0 0; }
.story-fact-timeline__values div { display: grid; grid-template-columns: minmax(6rem, .35fr) 1fr; gap: .5rem; }
.story-fact-timeline__values dt { color: var(--text-secondary, #59676e); }
.story-fact-timeline__values dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.story-fact-timeline__before summary { color: var(--text-secondary, #59676e); cursor: pointer; font-size: .82rem; }
.story-fact-timeline__pagination { display: flex; align-items: center; justify-content: space-between; gap: .75rem; color: var(--text-secondary, #59676e); font-size: .82rem; }
.story-fact-timeline__pagination div { display: flex; gap: .4rem; }
.story-fact-timeline__pagination button { min-height: 2.6rem; }
.story-fact-timeline__empty { margin: 0; color: var(--text-secondary, #59676e); }
@media (max-width: 480px) {
  .story-fact-timeline__summary { padding-inline: .75rem; }
  .story-fact-timeline__body { padding-inline: .75rem; }
  .story-fact-timeline__pagination { align-items: stretch; flex-direction: column; }
  .story-fact-timeline__pagination div button { flex: 1; }
}
</style>
