<template>
  <div class="scene-cockpit" :class="{ 'is-collapsed': railCollapsed }" :data-scene-cockpit-project="projectId || ''">
    <div class="scene-cockpit__title">
      <button
        type="button"
        class="writing-rail-heading-toggle"
        :aria-label="`${railCollapsed ? '展开' : '收起'}写作副驾驶`"
        :aria-expanded="!railCollapsed"
        @click="$emit('toggle-collapse')"
      >
        <span class="writing-rail-heading-label writing-rail-heading-label--copilot">写作副驾驶</span>
        <span aria-hidden="true">{{ railCollapsed ? "‹" : "›" }}</span>
      </button>
      <button v-if="!railCollapsed && chapter" class="btn btn-sm scene-cockpit-organize" @click="$emit('organize')">整理</button>
    </div>

    <div v-if="!railCollapsed && !chapter" class="empty-state writing-scene-panel-empty">
      <p>请先从左侧选择章节，再查看对应场景、人物和设定。</p>
    </div>
    <div v-else-if="!railCollapsed && scene" class="scene-alert-summary" :class="`scene-alert-summary--${alertSummary.highest}`" aria-live="polite">
      <span v-if="loading">警报加载中…</span>
      <span v-else-if="alertSummary.actionable">
        {{ alertSummary.actionable }} 项警报 · 最高{{ severityLabel(alertSummary.highest) }}严重度{{ alertSummary.stale ? ' · 最近校验已过期' : '' }}
      </span>
      <span v-else>✓ 当前未发现确定性警报</span>
    </div>
    <div v-if="!railCollapsed && chapter && !scene" class="scene-cockpit-empty">当前章节还没有关联场景。请从左侧选择场景或到故事结构中整理。</div>

    <template v-if="!railCollapsed && chapter && scene">
      <div class="cockpit-tabs" role="tablist" aria-label="场景参考">
        <button v-for="tab in tabs" :key="tab.key" class="cockpit-tab" :class="{ active: activeTab === tab.key }" role="tab" :aria-selected="activeTab === tab.key" @click="activeTab = tab.key">{{ tab.label }}</button>
      </div>
      <div class="cockpit-body">
        <section v-if="activeTab === 'alerts'" class="cockpit-panel" data-panel="alerts">
          <div v-if="alertError" class="scene-alert-load-error">{{ alertError }}</div>
          <template v-for="severity in severities" :key="severity">
            <section v-if="alertsBySeverity[severity].length" class="scene-alert-group" :class="`scene-alert-group--${severity}`">
              <div class="scene-alert-group__title">{{ severityLabel(severity) }}严重度 · {{ alertsBySeverity[severity].length }}</div>
              <article v-for="(alert, index) in alertsBySeverity[severity]" :key="alert.code || index" class="scene-alert-card" :class="`scene-alert-card--${severity}`">
                <div class="scene-alert-card__head"><span>{{ alert.source || '现场' }}<template v-if="alert.stale"> · 已过期</template></span><button type="button" class="scene-alert-card__action" @click="$emit('open-conflict')">查看 →</button></div>
                <div class="scene-alert-card__message">{{ alert.message || alert.label || alert.code }}</div>
                <div v-if="alert.detail" class="scene-alert-card__detail">{{ alert.detail }}</div>
              </article>
            </section>
          </template>
          <div v-if="!loading && !alerts.length" class="cockpit-empty">当前未发现确定性警报</div>
          <p class="scene-alert-disclaimer">现场警报只做字面和状态检查，不代表正文没有其他问题，也不会自动运行 AI。</p>
          <div class="scene-alert-actions">
            <button v-if="conflict?.latest" class="btn btn-sm" @click="$emit('open-conflict')">查看最近校验</button>
            <button class="btn btn-sm btn-primary" @click="$emit('run-conflict')">运行规则检查</button>
          </div>
        </section>

        <section v-else-if="activeTab === 'people'" class="cockpit-panel" data-panel="people">
          <div v-if="!people.length" class="cockpit-empty">暂无关联人物</div>
          <div v-else class="cockpit-people-list">
            <article v-for="person in people" :key="person.id || person.entity_id || person.name" class="cockpit-person-card">
              <div class="person-avatar">{{ personName(person).slice(0, 1) || '?' }}</div>
              <div class="person-info"><div class="person-name">{{ personName(person) }}</div><div class="person-status">{{ person.role || person.summary || person.status || '暂无摘要' }}</div></div>
              <button class="btn btn-sm btn-insert" @click="$emit('insert-text', personName(person))">插入</button>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'place'" class="cockpit-panel" data-panel="place">
          <div v-if="!location" class="cockpit-empty">暂无地点信息</div>
          <div v-else class="cockpit-place-card">
            <div class="place-name">{{ typeof location === 'string' ? location : (location.name || location.title || '未知地点') }}</div>
            <div v-if="typeof location === 'object'" class="place-desc">{{ location.description || location.summary || '' }}</div>
          </div>
        </section>

        <section v-else-if="activeTab === 'lore'" class="cockpit-panel" data-panel="lore">
          <article
            v-for="(moduleKey, index) in moduleOrder"
            :key="moduleKey"
            class="scene-cockpit-module"
            :class="{ 'is-collapsed': collapsed.has(moduleKey) }"
            :data-cockpit-module="moduleKey"
            draggable="true"
            @dragstart="dragging = moduleKey"
            @dragover.prevent
            @drop="dropModule(moduleKey)"
          >
            <div class="scene-cockpit-module__head">
              <button type="button" @click="toggleModule(moduleKey)"><span>{{ moduleLabel(moduleKey) }}</span><span aria-hidden="true">{{ collapsed.has(moduleKey) ? '▸' : '▾' }}</span></button>
              <span class="scene-cockpit-module__reorder">
                <button class="btn-icon" :disabled="index === 0" :aria-label="`上移${moduleLabel(moduleKey)}`" @click="moveModule(moduleKey, -1)">↑</button>
                <button class="btn-icon" :disabled="index === moduleOrder.length - 1" :aria-label="`下移${moduleLabel(moduleKey)}`" @click="moveModule(moduleKey, 1)">↓</button>
              </span>
            </div>
            <div class="scene-cockpit-module__body">
              <template v-if="moduleKey === 'scene_header'">
                <div class="scene-cockpit-scene-title">{{ scene.title || '未命名场景' }}</div>
                <div class="scene-cockpit-meta"><span>{{ scene.scene_index != null ? `第 ${scene.scene_index} 场` : '未排序' }}</span><span>{{ narrativeTagLabel(scene.narrative_tag) }}</span></div>
              </template>
              <div v-else-if="moduleValue(moduleKey)" class="scene-cockpit-text">{{ moduleValue(moduleKey) }}</div>
              <div v-else class="muted">暂无</div>
            </div>
          </article>
        </section>

      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { loadSceneCockpitOrder, saveSceneCockpitOrder } from "../../../../views/sceneCockpitPanel.js"

const props = defineProps({
  projectId: { type: String, default: null },
  chapter: { type: Number, default: null },
  scene: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  alertError: { type: String, default: null },
  alerts: { type: Array, default: () => [] },
  people: { type: Array, default: () => [] },
  location: { type: [Object, String], default: null },
  conflict: { type: Object, default: () => ({ latest: null }) },
  railCollapsed: { type: Boolean, default: false },
})
defineEmits(["run-conflict", "open-conflict", "insert-text", "organize", "toggle-collapse"])

const tabs = [
  { key: "alerts", label: "警报" }, { key: "people", label: "人物" }, { key: "place", label: "地点" },
  { key: "lore", label: "设定" },
]
const severities = ["high", "medium", "low", "info"]
const labels = {
  scene_header: "场景", goal: "目标", must_happen: "必须发生", must_not_happen: "禁止发生",
  core_conflict: "核心冲突", continuity: "前后连续性摘要", references: "参考资料", foreshadowing: "伏笔 / 揭示",
}
const activeTab = ref("lore")
const moduleOrder = ref([])
const collapsed = ref(new Set())
const dragging = ref(null)

function resetOrder() {
  moduleOrder.value = loadSceneCockpitOrder(props.projectId)
  const compact = typeof window !== "undefined" && window.innerHeight < 760
  collapsed.value = compact ? new Set(["continuity", "references", "foreshadowing"]) : new Set()
}
watch(() => props.projectId, resetOrder, { immediate: true })

const alertsBySeverity = computed(() => Object.fromEntries(severities.map((severity) => [severity, props.alerts.filter((item) => item?.severity === severity)])))
const alertSummary = computed(() => {
  const actionable = props.alerts.filter((item) => ["high", "medium", "low"].includes(item?.severity)).length
  return {
    actionable,
    highest: severities.find((severity) => alertsBySeverity.value[severity].length) || "info",
    stale: props.alerts.some((item) => item?.stale),
  }
})

const severityLabel = (severity) => ({ high: "高", medium: "中", low: "提示", info: "信息" }[severity] || severity)
const personName = (person) => person?.name || person?.title || "未命名"
const moduleLabel = (key) => labels[key] || key
const narrativeTagLabel = (value) => ({
  draft: "创作中",
  planned: "待写",
  canonical: "已采用",
  candidate: "待处理",
  proposal: "建议稿",
}[value] || "创作中")
function moduleValue(key) {
  const value = {
    goal: props.scene?.goal,
    must_happen: props.scene?.must_happen,
    must_not_happen: props.scene?.must_not_happen,
    core_conflict: props.scene?.core_conflict,
    continuity: props.scene?.emotional_beat,
    references: props.scene?.source,
    foreshadowing: props.scene?.foreshadowing || props.scene?.reveals,
  }[key]
  return Array.isArray(value) ? value.join("、") : value
}
function toggleModule(key) {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}
function persistOrder() { saveSceneCockpitOrder(props.projectId, moduleOrder.value) }
function moveModule(key, delta) {
  const from = moduleOrder.value.indexOf(key)
  const to = from + delta
  if (from < 0 || to < 0 || to >= moduleOrder.value.length) return
  const next = [...moduleOrder.value]
  next.splice(to, 0, next.splice(from, 1)[0])
  moduleOrder.value = next
  persistOrder()
}
function dropModule(target) {
  const from = moduleOrder.value.indexOf(dragging.value)
  const to = moduleOrder.value.indexOf(target)
  dragging.value = null
  if (from < 0 || to < 0 || from === to) return
  const next = [...moduleOrder.value]
  next.splice(to, 0, next.splice(from, 1)[0])
  moduleOrder.value = next
  persistOrder()
}
</script>
