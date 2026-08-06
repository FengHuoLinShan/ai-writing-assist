<!--
  WorldObjectsTab — world/objects 对象库（vanilla _renderEntityList 及子渲染的
  Vue 化，worldView.js:1121-1610）。DOM 契约逐节点保留；筛选变更一律
  navigate 写 query（URL 是事实源），island 重挂载后由 load() 重新解码。
-->
<template>
  <div>
    <!-- 自动提取抽屉（vanilla _renderAutoExtractPanel 847-873） -->
    <div v-if="session.autoExtractOpen" class="world-extract-drawer">
      <div class="world-extract-panel">
        <div class="world-extract-panel__label">从正文整理人物、设定与关系</div>
        <div class="world-extract-panel__controls">
          起始章 <input id="w-extract-start" v-model.number="extractStart" type="number" min="1" class="world-extract-panel__input" />
          结束章 <input id="w-extract-end" v-model.number="extractEnd" type="number" min="1" class="world-extract-panel__input" />
          <button class="btn btn-sm btn-primary" data-action="submit-extract" data-type="world_object_auto_extraction" :disabled="extractRunning" @click="onSubmitExtract">
            {{ extractRunning ? "提取中..." : "确认并开始提取" }}
          </button>
        </div>
        <p class="writing-form-hint" role="note">{{ importNotice }}</p>
        <div id="w-extract-progress" class="world-extract-panel__progress">
          <WorkflowProgressCard
            v-if="extractProgress"
            :progress="extractProgress"
            variant="card"
            title="正在整理人物、设定与关系"
            :show-task-id="false"
          >
            <div class="workflow-progress__destination">{{ extractDestination }}</div>
          </WorkflowProgressCard>
          <div v-else id="w-extract-status" class="world-extract-panel__status">{{ extractStatusText }}</div>
        </div>
      </div>
    </div>

    <!-- 筛选面板（vanilla _renderFilters/_renderFilterPanel 1219-1291） -->
    <section class="world-filter-panel" data-filter-panel="objects">
      <button
        type="button"
        class="btn btn-sm world-filter-panel__toggle"
        data-action="toggle-filter-panel"
        data-filter-key="objects"
        :aria-expanded="filterPanelOpen ? 'true' : 'false'"
        aria-controls="world-filter-panel-objects"
        @click="toggleFilterPanel"
      >
        <span aria-hidden="true">{{ filterPanelOpen ? "▾" : "▸" }}</span>
        <span data-filter-toggle-label>{{ filterPanelOpen ? "收起筛选" : "展开筛选" }}</span>
        <span v-if="hasActiveFilters" class="world-filter-panel__active">已筛选</span>
      </button>
      <div id="world-filter-panel-objects" class="world-filter-panel__body" :hidden="!filterPanelOpen">
        <div class="world-object-filters">
          <select id="filter-entity-type" v-model="filterForm.entity_type" class="form-select" aria-label="对象类型筛选">
            <option value="">全部类型</option>
            <option v-for="type in entityTypes" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
          <select id="filter-display-state" v-model="filterForm.display_state" class="form-select" aria-label="对象状态筛选">
            <option v-for="status in statuses" :key="status.value" :value="status.value">{{ status.label }}</option>
          </select>
          <input
            id="filter-q"
            v-model="filterForm.q"
            class="form-input world-object-filters__search"
            type="search"
            placeholder="模糊搜索名称、别名或描述"
            aria-label="模糊搜索名称、别名或描述"
            @keydown="onFilterQKeydown"
          />
          <button class="btn btn-sm" data-action="toggle-advanced-filters" @click="toggleAdvancedFilters">{{ session.advancedFiltersOpen ? "▾" : "▸" }} 高级</button>
          <button class="btn btn-sm btn-primary" data-action="apply-filters" @click="applyFilters">应用</button>
          <button class="btn btn-sm" data-action="reset-filters" @click="resetFilters">重置</button>
          <template v-if="session.advancedFiltersOpen">
            <select id="filter-source" v-model="filterForm.source" class="form-select" aria-label="来源筛选">
              <option value="">全部来源</option>
              <option value="deep_import">深度导入</option>
              <option value="manual">手动</option>
              <option value="ai_generated">AI 生成</option>
            </select>
            <details class="world-diagnostic-filter" :open="Boolean(objectFilters.workflow_id)">
              <summary>诊断筛选</summary>
              <input id="filter-workflow-id" v-model="filterForm.workflow_id" class="form-input" data-diagnostic-field placeholder="处理批次编号" aria-label="处理批次编号筛选" />
            </details>
            <select id="filter-needs-review" v-model="filterForm.needs_review" class="form-select" aria-label="注意原因筛选">
              <option value="">全部注意原因</option>
              <option value="true">需要人工检查</option>
              <option value="false">无注意项</option>
            </select>
            <select id="filter-auto-ingested" v-model="filterForm.auto_ingested" class="form-select" aria-label="入库方式筛选">
              <option value="">全部入库方式</option>
              <option value="true">自动入库</option>
              <option value="false">非自动入库</option>
            </select>
          </template>
        </div>
      </div>
    </section>

    <!-- 热点概览（vanilla _renderHotOverview 1311-1344） -->
    <section v-if="discoveryMode === 'hot'" class="world-hot-overview" aria-label="对象热点概览">
      <div class="world-hot-overview__facets">
        <button
          v-for="chip in hotChips"
          :key="chip.value"
          class="world-hot-facet"
          :class="{ active: objectFilters.focus === chip.value }"
          data-action="set-hot-focus"
          :data-focus="chip.value"
          @click="setHotFocus(chip.value)"
        >
          <span>{{ chip.label }}</span><strong>{{ chip.count }}</strong>
        </button>
      </div>
      <div v-if="hotTypeChips.length" class="world-hot-overview__types" aria-label="对象类型聚合">
        <button
          v-for="item in hotTypeChips"
          :key="item.entity_type"
          class="world-hot-type"
          :class="{ active: objectFilters.entity_type === item.entity_type }"
          data-action="set-hot-type"
          :data-entity-type="item.entity_type"
          @click="setHotType(item.entity_type)"
        >
          {{ typeLabel(item.entity_type) }} · {{ item.count }}
        </button>
      </div>
      <p class="world-hot-overview__status" :data-status="rankingContext?.status || 'unknown'">{{ hotStatusLabel }}</p>
    </section>

    <!-- 空态 / 错误态（vanilla 1128-1148） -->
    <template v-if="entities.length === 0">
      <div v-if="entitiesLoadError" class="empty-state" role="alert">
        <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
        <p>世界对象加载失败</p>
        <p class="world-text-dim">可稍后重试。错误信息：{{ entitiesLoadError }}</p>
      </div>
      <div v-else class="empty-state">
        <div class="empty-icon">&#127758;</div>
        <p>还没有世界对象。</p>
        <p>世界对象是小说世界中的核心创作资产，包括地点、组织、物品、事件等。</p>
        <div class="actions">
          <button class="btn btn-primary" data-action="new" @click="showEntityCreateForm()">手动新建对象</button>
        </div>
      </div>
    </template>

    <!-- 列表（hot 模式直出；normal 模式按批次分组，vanilla 1150-1216） -->
    <template v-else>
      <template v-if="discoveryMode === 'hot'">
        <WorldEntityCollection :entities="entities" :show-new-badge="false" :object-view-mode="objectViewMode" :display-state="objectFilters.display_state" :entity-types="entityTypes" @bulk-run="onBulkRun" />
      </template>
      <template v-else-if="batchGroups.hasBatches">
        <div v-if="batchGroups.autoEntities.length > 0" class="world-batch-group">
          <details open class="world-batch-group__details">
            <summary class="world-batch-group__summary">
              <span class="world-batch-group__star">&#9733;</span> 自动入库 — <span class="world-batch-time" :title="batchGroups.batchTimeTitle"><span v-if="batchGroups.fresh" class="world-batch-fresh-dot" aria-label="新鲜入库"></span>{{ batchGroups.batchTimeLabel }}</span> — {{ batchGroups.autoEntities.length }} 个对象
            </summary>
            <WorldEntityCollection :entities="batchGroups.autoEntities" :show-new-badge="true" :object-view-mode="objectViewMode" :display-state="objectFilters.display_state" :entity-types="entityTypes" @bulk-run="onBulkRun" />
          </details>
        </div>
        <div v-if="batchGroups.manualEntities.length > 0" class="world-batch-group">
          <details :open="batchGroups.autoEntities.length === 0" class="world-batch-group__details">
            <summary class="world-batch-group__summary">
              其他对象 — {{ batchGroups.manualEntities.length }} 个
            </summary>
            <WorldEntityCollection :entities="batchGroups.manualEntities" :show-new-badge="false" :object-view-mode="objectViewMode" :display-state="objectFilters.display_state" :entity-types="entityTypes" @bulk-run="onBulkRun" />
          </details>
        </div>
      </template>
      <template v-else>
        <WorldEntityCollection :entities="entities" :show-new-badge="false" :object-view-mode="objectViewMode" :display-state="objectFilters.display_state" :entity-types="entityTypes" @bulk-run="onBulkRun" />
      </template>
      <WorldPager
        :total="entitiesTotal"
        :skip="objectFilters.skip"
        :limit="objectFilters.limit"
        prev-action="prev-page"
        next-action="next-page"
        @change="changePage"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { getRouter } from "../../../bridge/index.js"
import { importAuthorizationNotice } from "../../../../shared/importAuthorization.js"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"
import { worldSession as session, saveFilterPanelState } from "../worldSession.js"
import { autoExtractManager, submitAutoExtract } from "../workflowManagers.js"
import {
  WORLD_FILTER_DEFAULTS,
  WORLD_OBJECT_QUERY_KEYS,
  objectQueryFromState,
} from "../logic/worldQuery.js"
import { reconcileBulkSelection } from "../logic/worldBulkSelection.js"
import { entityId, formatBatchTime, formatBatchTimeFull, isFreshBatch } from "../logic/worldEntityHelpers.js"
import { runObjectsBulkAction, showEntityCreateForm, syncWorldListRegistry } from "../logic/worldEntityOps.js"
import WorldEntityCollection from "./WorldEntityCollection.vue"
import WorldPager from "./WorldPager.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  entities: { type: Array, default: () => [] },
  entitiesTotal: { type: Number, default: 0 },
  entitiesLoadError: { type: String, default: null },
  rankingFacets: { type: Object, default: null },
  rankingContext: { type: Object, default: null },
  batches: { type: Array, default: () => [] },
  objectFilters: { type: Object, default: () => ({ ...WORLD_FILTER_DEFAULTS }) },
  objectViewMode: { type: String, default: "table" },
  discoveryMode: { type: String, default: "hot" },
  entityTypes: { type: Array, default: () => [] },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
})

const statuses = [
  { value: "active", label: "已采用" },
  { value: "review", label: "待处理" },
  { value: "archived", label: "历史" },
]

const importNotice = importAuthorizationNotice()

// ---- 筛选表单（本地副本，应用时 navigate 写 query；重挂载后由新 props 重播种） ----
const filterForm = reactive({ ...WORLD_FILTER_DEFAULTS })

function seedFilterForm() {
  Object.assign(filterForm, WORLD_FILTER_DEFAULTS, props.objectFilters)
}
watch(() => props.objectFilters, seedFilterForm, { immediate: true, deep: true })

function navigateObjects(nextFilters) {
  getRouter()?.navigate("world", "objects", true, objectQueryFromState(nextFilters, props.objectViewMode, props.discoveryMode))
}

/** 对应 vanilla _applyFilters（读取表单 → skip 归零 → navigate）。 */
function applyFilters() {
  navigateObjects({ ...filterForm, skip: 0 })
}

/** 对应 vanilla _resetFilters。 */
function resetFilters() {
  navigateObjects({ ...WORLD_FILTER_DEFAULTS, skip: 0 })
}

function onFilterQKeydown(event) {
  if (event.key !== "Enter" || event.isComposing) return
  event.preventDefault()
  applyFilters()
}

/** 对应 vanilla _toggleAdvancedFilters（router.refresh 整刷由响应式取代）。 */
function toggleAdvancedFilters() {
  session.advancedFiltersOpen = !session.advancedFiltersOpen
}

const filterPanelOpen = computed(() => session.filterPanelsOpen?.objects === true)

/** 对应 vanilla _toggleFilterPanel + _saveFilterPanelState。 */
function toggleFilterPanel() {
  session.filterPanelsOpen = { ...session.filterPanelsOpen, objects: !filterPanelOpen.value }
  saveFilterPanelState(props.projectId)
}

const hasActiveFilters = computed(() => (
  props.objectFilters.display_state !== "active"
  || WORLD_OBJECT_QUERY_KEYS.some((key) => key !== "display_state" && Boolean(props.objectFilters[key]))
))

// ---- 热点概览 ----
const hotChips = computed(() => {
  const facets = props.rankingFacets || {}
  return [
    { value: "important", label: "重要", count: facets.important ?? 0 },
    { value: "hot", label: "近期热点", count: facets.hot ?? 0 },
    { value: "other", label: "其他", count: facets.other ?? 0 },
  ]
})

const hotTypeChips = computed(() => (props.rankingFacets?.by_type || []).slice(0, 8))

const hotStatusLabel = computed(() => {
  const context = props.rankingContext || {}
  return {
    ready: `热点索引已覆盖 ${context.covered_chapters ?? 0} 章`,
    partial: `热点索引回填中：已覆盖 ${context.covered_chapters ?? 0} / ${context.total_chapters ?? 0} 章`,
    unavailable: "近期出场索引暂不可用，当前按长期重要性排序",
  }[context.status] || "正在读取热点概览"
})

function typeLabel(entityType) {
  return props.entityTypes.find((type) => type.value === entityType)?.label || entityType
}

/** 对应 vanilla _setHotFocus。 */
function setHotFocus(focus) {
  if (props.discoveryMode !== "hot") return
  const next = props.objectFilters.focus === focus ? "" : focus
  navigateObjects({ ...props.objectFilters, focus: next, skip: 0 })
}

/** 对应 vanilla _setHotType。 */
function setHotType(entityType) {
  if (props.discoveryMode !== "hot") return
  navigateObjects({
    ...props.objectFilters,
    entity_type: props.objectFilters.entity_type === entityType ? "" : entityType,
    skip: 0,
  })
}

// ---- 自动提取 ----
const extractStart = ref(1)
const extractEnd = ref(10)

const extractProgress = computed(() => autoExtractManager.state.progress)
const extractRunning = computed(() => (
  autoExtractManager.state.submitting
  || (
    Boolean(autoExtractManager.state.taskId)
    && !extractProgress.value?.terminal
    && !extractProgress.value?.failed
  )
))

/** 对应 vanilla _renderAutoExtractPanel 的范围文案（_updateExtractStatusDOM 1102-1119）。 */
const extractDestination = computed(() => {
  const meta = autoExtractManager.state.meta
  return meta
    ? `范围: 章节 ${meta.start_chapter || 1}-${meta.end_chapter || 10}。完成后查看世界对象、别名和待处理关系。`
    : "完成后查看世界对象、别名和待处理关系。"
})

/** 对应 vanilla _updateExtractStatusDOM 的状态行（无 progress 时）。 */
const extractStatusText = computed(() => {
  const taskId = autoExtractManager.state.taskId
  const prefix = taskId ? `任务 ${taskId.slice(0, 8)}... — ` : "状态: "
  return prefix + autoExtractManager.state.status
})

function onSubmitExtract() {
  void submitAutoExtract(Number(extractStart.value) || 1, Number(extractEnd.value) || 10)
}

// ---- 批次分组（vanilla 1161-1213） ----
const batchGroups = computed(() => {
  const hasBatches = props.batches && props.batches.length > 0
  if (!hasBatches) return { hasBatches: false, autoEntities: [], manualEntities: [] }
  const autoIngestedIds = new Set()
  for (const batch of props.batches) {
    for (const entity of (batch.entities || [])) autoIngestedIds.add(entity.id)
  }
  const autoEntities = []
  const manualEntities = []
  for (const e of props.entities) {
    if (autoIngestedIds.has(entityId(e))) autoEntities.push(e)
    else manualEntities.push(e)
  }
  const ingestedAt = props.batches[0]?.ingested_at
  return {
    hasBatches: true,
    autoEntities,
    manualEntities,
    batchTimeLabel: formatBatchTime(ingestedAt),
    batchTimeTitle: formatBatchTimeFull(ingestedAt),
    fresh: isFreshBatch(ingestedAt),
  }
})

// ---- 批量选择 / 注册表同步 ----
watch(() => [props.entities, props.entityTypes, props.reviewTypeCatalog], () => {
  syncWorldListRegistry({
    entities: props.entities,
    entityTypes: props.entityTypes,
    reviewTypeCatalog: props.reviewTypeCatalog,
  })
  reconcileBulkSelection("world-objects", props.entities.map((item) => entityId(item)).filter(Boolean))
}, { immediate: true, deep: true })

function onBulkRun(action) {
  runObjectsBulkAction(action, props.entities)
}

/** 对应 vanilla _changePage（3824-3830）。 */
function changePage(delta) {
  const newSkip = props.objectFilters.skip + delta * props.objectFilters.limit
  if (newSkip < 0) return
  if (newSkip >= props.entitiesTotal) return
  navigateObjects({ ...props.objectFilters, skip: newSkip })
}
</script>
