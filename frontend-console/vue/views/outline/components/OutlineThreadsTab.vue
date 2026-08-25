<!--
  OutlineThreadsTab — outline/threads 剧情线子标签（vanilla _renderThreads L1145-1207
  + _renderThreadInformationProgression L1258-1288）。DOM 结构/class/id/data-action
  逐节点对齐。vanilla 的 _renderForeshadowing/_renderReveals 为未挂载死代码，
  threads 视图契约不含伏笔/揭示列表，本组件不渲染。
  筛选变更一律 router.navigate("outline", "threads", true, query)。
-->
<template>
  <div>
    <!-- === 筛选面板（vanilla _renderStructureFilters "threads" L890-911） === -->
    <details ref="filterPanel" class="outline-structure-filters">
      <summary>
        <span class="outline-structure-filters__label">筛选剧情线</span>
        <span class="outline-structure-filters__summary">{{ activeFilterCount ? `已启用 ${activeFilterCount} 项` : "未启用" }}</span>
      </summary>
      <div class="scene-management-filters" aria-label="剧情线筛选条件">
        <label class="scene-filter-field">
          <span>状态</span>
          <select id="outline-filter-status" class="form-select" v-model="filterForm.status">
            <option value="">全部状态</option>
            <option v-for="[val, label] in threadStatusOptions" :key="val" :value="val">{{ label }}</option>
          </select>
        </label>
        <label class="scene-filter-field">
          <span>来源</span>
          <select id="outline-filter-source" class="form-select" v-model="filterForm.source">
            <option value="">全部来源</option>
            <option v-for="[val, label] in STRUCTURE_SOURCE_OPTIONS" :key="val" :value="val">{{ label }}</option>
          </select>
        </label>
        <label class="scene-filter-field">
          <span>注意</span>
          <select id="outline-filter-needs-review" class="form-select" v-model="filterForm.needs_review">
            <option value="">全部注意原因</option>
            <option value="true">需要人工检查</option>
            <option value="false">无注意项</option>
          </select>
        </label>
        <details class="outline-structure-diagnostic-filters" :open="Boolean(filterForm.workflow_id)">
          <summary>更多筛选{{ filterForm.workflow_id ? "（已填写）" : "" }}</summary>
          <label class="scene-filter-field scene-filter-field--wide">
            <span>整理批次编号</span>
            <input class="form-input" id="outline-filter-workflow-id" data-diagnostic-field v-model="filterForm.workflow_id" placeholder="需要排查某次整理时输入批次编号" />
          </label>
        </details>
        <div class="scene-filter-actions">
          <button type="button" class="btn btn-sm btn-primary" data-action="apply-outline-structure-filters" @click="applyFilters">应用</button>
          <button type="button" class="btn btn-sm" data-action="reset-outline-structure-filters" @click="resetFilters">重置</button>
        </div>
      </div>
    </details>

    <!-- === 剧情线列表（vanilla _renderThreads L1152-1207） === -->
    <template v-if="threads.length > 0">
      <OutlineBulkToolbar scope="outline-threads" :actions="THREAD_BULK_ACTIONS" noun="剧情线" @run="runBulkThread" />

      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">
              <label class="selection-checkbox" title="全选当前剧情线">
                <input type="checkbox"
                  data-action="bulk-toggle-all"
                  data-scope="outline-threads"
                  :checked="threadSelectAll.checked"
                  :indeterminate="threadSelectAll.indeterminate"
                  :disabled="threadSelectAll.disabled"
                  @change="toggleAllThread"
                />
                <span class="sr-only">全选当前剧情线</span>
              </label>
            </th>
            <th>状态</th>
            <th>名称</th>
            <th>类型</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in threads" :key="t.id || t.thread_id" class="outline-structure-row" :data-id="t.id || t.thread_id">
            <td class="selection-cell">
              <label class="selection-checkbox" :title="`选择 ${t.name || t.title || '剧情线'}`">
                <input type="checkbox"
                  data-action="bulk-toggle-one"
                  data-scope="outline-threads"
                  :data-id="t.id || t.thread_id"
                  :checked="threadIsSelected(t.id || t.thread_id)"
                  @change="toggleOneThread(t.id || t.thread_id, $event.target.checked)"
                />
                <span class="sr-only">选择 {{ t.name || t.title || '剧情线' }}</span>
              </label>
            </td>
            <td data-label="状态"><span class="badge" :class="threadStatusBadgeClass(t)">{{ threadStatusLabel(t) }}</span></td>
            <td data-label="名称">{{ t.name || t.title }}</td>
            <td data-label="类型" class="outline-asset-meta">{{ threadTypeLabel(t) }}</td>
            <td data-label="标记">
              <template v-if="threadBadges(t).length">
                <span v-for="badge in threadBadges(t)" :key="`${badge.text}-${badge.cls}`" class="badge" :class="badge.cls">{{ badge.text }}</span>
              </template>
              <template v-else>-</template>
            </td>
            <td data-label="描述" class="outline-asset-description">{{ threadDesc(t) }}</td>
            <td data-label="操作">
              <button v-if="threadReviewAction(t)" class="btn btn-sm" :class="threadReviewAction(t).className" data-action="mark-thread-reviewed" :data-id="t.id || t.thread_id" @click="markThreadReviewed(t.id || t.thread_id)">{{ threadReviewAction(t).label }}</button>
              <button class="btn btn-sm btn-primary" data-action="edit-thread" :data-id="t.id || t.thread_id" @click="editThread(t.id || t.thread_id)">编辑</button>
              <ActionMenu :menu-id="`thread-actions-${t.id || t.thread_id}`" :label="`${t.name || t.title || '剧情线'}的更多操作`" :items="threadMenuItems(t)" @select="onThreadMenuSelect" />
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="threadsTotal > filterForm.limit" class="outline-structure-pagination">
        <button class="btn btn-sm" :disabled="filterForm.skip <= 0" data-action="prev-outline-structure-page" @click="changePage(-1)">上一页</button>
        <span class="outline-structure-pagination__info">第 {{ threadsCurrentPage }} / {{ threadsTotalPages }} 页，共 {{ threadsTotal }} 条</span>
        <button class="btn btn-sm" :disabled="filterForm.skip + filterForm.limit >= threadsTotal" data-action="next-outline-structure-page" @click="changePage(1)">下一页</button>
      </div>
    </template>

    <!-- === 空态（vanilla _renderStructureEmptyState L1026-1040） === -->
    <div v-else-if="!threadsLoadError" class="empty-state">
      <div class="empty-icon">&#128204;</div>
      <p>暂无剧情线。</p>
      <p class="outline-empty-detail">{{ emptyDetail }}</p>
      <button class="btn btn-sm btn-primary" data-action="nav-scenes" @click="navigateScenes">从已采用场景开始整理</button>
    </div>

    <!-- 错误态 -->
    <div v-if="threadsLoadError" class="empty-state" role="alert">
      <div class="empty-icon">!</div>
      <p>加载失败</p>
      <p class="outline-empty-detail">{{ threadsLoadError }}</p>
      <button class="btn btn-sm" data-action="retry-outline-load" @click="retryLoad">重新加载</button>
    </div>

    <!-- === 信息推进（vanilla _renderThreadInformationProgression L1258-1288） === -->
    <section
      ref="informationSection"
      class="outline-information-progress"
      :class="{ 'is-deep-linked': informationFocusKind && !hasInformationFocusMatch }"
      id="outline-thread-information"
      tabindex="-1"
      aria-labelledby="outline-thread-information-title"
    >
      <h3 id="outline-thread-information-title">信息推进</h3>
      <p class="writing-form-hint">伏笔、暗示、揭示与兑现按同一条线索和章节排列；未归类的计划可在下方归入剧情线。</p>
      <template v-if="threads.length > 0">
        <details
          v-for="thread in threads"
          :key="thread.id || thread.thread_id"
          class="outline-preview-section"
          :class="{ 'is-deep-linked': threadHasInformationFocus(thread) }"
          :data-thread-id="thread.id || thread.thread_id"
          :data-information-focus-match="threadHasInformationFocus(thread) ? 'true' : undefined"
          :open="informationMovements(thread).size > 0"
        >
          <summary>
            <span>{{ thread.name || thread.title || "剧情线" }}</span>
            <span class="outline-information-count">{{ informationMovements(thread).size }} 条推进</span>
          </summary>
          <template v-if="informationMovements(thread).size">
            <ol class="outline-information-timeline">
              <li v-for="(items, idx) in informationMovementGroups(thread)" :key="idx" class="outline-information-movement">
                <h4>推进 {{ idx + 1 }}</h4>
                <ul class="outline-information-events">
                  <li v-for="item in items" :key="item.plan.id" class="outline-information-node" :data-kind="item.kind">
                    <span class="outline-information-node__kind">{{ item.kind === "foreshadowing" ? "暗示 / 兑现" : "局部 / 完整揭示" }}</span>
                    <span v-if="informationPlanChapter(item.plan, item.kind)" class="outline-asset-mono">第 {{ informationPlanChapter(item.plan, item.kind) }} 章</span>
                    <span class="outline-information-node__content">{{ informationPlanContent(item.plan, item.kind) }}</span>
                  </li>
                </ul>
              </li>
            </ol>
          </template>
          <p v-else class="writing-form-hint">尚未设计隐藏、暗示、局部揭示或兑现。</p>
        </details>
      </template>
      <p v-else class="writing-form-hint">创建剧情线后可设计信息推进。</p>

      <!-- 未归入剧情线 -->
      <details class="outline-preview-section" :open="unassignedPlans.length > 0">
        <summary><span>未归入剧情线</span><span class="outline-information-count">（{{ unassignedPlans.length }}）</span></summary>
        <template v-if="unassignedPlans.length">
          <ul class="outline-information-unassigned-list">
            <li v-for="item in unassignedPlans" :key="`${item.kind}-${item.plan.id}`" class="outline-information-unassigned">
              <span>{{ informationPlanName(item) }}</span>
              <select class="form-select" data-role="information-thread-assignment" :data-kind="item.kind" :data-id="item.plan.id" :aria-label="`将 ${informationPlanName(item)} 归入剧情线`" v-model="assignmentValues[`${item.kind}-${item.plan.id}`]" @change="assignPlan(item.kind, item.plan.id, $event.target.value)">
                <option value="">选择剧情线…</option>
                <option v-for="thread in threads" :key="thread.id || thread.thread_id" :value="thread.id || thread.thread_id">{{ thread.name || thread.title || thread.id || thread.thread_id }}</option>
              </select>
            </li>
          </ul>
        </template>
        <p v-else class="writing-form-hint">没有未归类计划。</p>
      </details>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { getRouter } from "../../../bridge/index.js"
import { structureAssetDisplay, displayStateBadgeClass, assetAttentionReasons } from "../../../../shared/assetDisplayState.js"
import {
  STRUCTURE_FILTER_DEFAULTS,
  STRUCTURE_SOURCE_OPTIONS,
  structureStatusOptions,
  structureQueryFromState,
} from "../logic/outlineStructure.js"
import {
  editThread as editThreadOp,
  deleteThread as deleteThreadOp,
  markThreadReviewed as markThreadReviewedOp,
  threadDescription,
  assignInformationPlan,
  runBulkOutlineAction,
} from "../logic/outlineStructureOps.js"
import {
  getBulkSelection,
  reconcileBulkSelection,
  outlineFilterDrafts,
  selectAllState as computeSelectAll,
  toggleBulkSelection,
  toggleAllBulkSelection,
} from "../logic/outlineBulkSelection.js"
import ActionMenu from "../../../components/ActionMenu.vue"
import OutlineBulkToolbar from "./OutlineBulkToolbar.vue"

const THREAD_BULK_ACTIONS = [
  { action: "review-threads", label: "批量采用 / 标记已检查", className: "btn-primary" },
  { action: "delete-threads", label: "批量删除", className: "btn-danger" },
]
const THREAD_TYPE_LABELS = { main: "主线", sub: "支线", background: "暗线" }

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "threads" },
  threads: { type: Array, default: () => [] },
  threadsTotal: { type: Number, default: 0 },
  threadsLoadError: { type: String, default: null },
  foreshadowing: { type: Array, default: () => [] },
  reveals: { type: Array, default: () => [] },
  unassignedForeshadowing: { type: Array, default: () => [] },
  unassignedReveals: { type: Array, default: () => [] },
  informationFocus: { type: String, default: null },
  filters: { type: Object, default: () => ({ ...STRUCTURE_FILTER_DEFAULTS }) },
})

const threadStatusOptions = computed(() => structureStatusOptions("threads"))

// ---- Filters ----
const threadScope = "outline-threads"
const filterPanel = ref(null)
const activeFilterCount = computed(() => (
  ["status", "source", "needs_review", "workflow_id"].filter((key) => Boolean(props.filters?.[key])).length
))
const routeSignature = structureQueryFromState("threads", props.filters).toString()
const restoredDraft = outlineFilterDrafts[threadScope]?.routeSignature === routeSignature
  ? outlineFilterDrafts[threadScope].value
  : null
if (!restoredDraft) delete outlineFilterDrafts[threadScope]
const filterForm = reactive({
  ...STRUCTURE_FILTER_DEFAULTS,
  ...props.filters,
  ...(restoredDraft || {}),
  skip: props.filters.skip,
  limit: props.filters.limit,
})
watch(filterForm, (value) => {
  outlineFilterDrafts[threadScope] = {
    routeSignature: outlineFilterDrafts[threadScope]?.routeSignature || routeSignature,
    value: { ...value },
  }
}, { immediate: true, deep: true, flush: "sync" })

async function navigateFilters(filters, restoreFilterFocus = false) {
  const query = structureQueryFromState("threads", filters)
  outlineFilterDrafts[threadScope].routeSignature = query.toString()
  const navigated = await getRouter()?.navigate("outline", "threads", true, query)
  if (restoreFilterFocus && navigated !== false) {
    document.querySelector(".outline-structure-filters > summary")?.focus()
  }
}

const threadsTotal = computed(() => props.threadsTotal || 0)
const threadsCurrentPage = computed(() => Math.floor(filterForm.skip / filterForm.limit) + 1)
const threadsTotalPages = computed(() => Math.ceil(threadsTotal.value / filterForm.limit) || 1)
const threadsLoadError = computed(() => props.threadsLoadError)

// ---- Threads Bulk Selection ----
const threadIsSelected = (id) => getBulkSelection(threadScope).has(String(id))
watch(
  () => props.threads.map((item) => item.id || item.thread_id),
  (ids) => reconcileBulkSelection(threadScope, ids),
  { immediate: true },
)
const threadSelectAll = computed(() => {
  const ids = props.threads.map((t) => t.id || t.thread_id)
  return computeSelectAll(threadScope, ids)
})

// ---- Unassigned Plans for Information Progression ----
const unassignedPlans = computed(() => [
  ...(props.unassignedForeshadowing || []).map((plan) => ({ kind: "foreshadowing", plan })),
  ...(props.unassignedReveals || []).map((plan) => ({ kind: "reveal", plan })),
])
const informationFocusKind = computed(() => ({
  foreshadowing: "foreshadowing",
  reveals: "reveal",
})[props.informationFocus] || null)
const hasInformationFocusMatch = computed(() => props.threads.some(threadHasInformationFocus))
const informationSection = ref(null)

// ---- Assignment values (track selection per plan) ----
const assignmentValues = reactive({})
function initAssignmentValues() {
  for (const item of unassignedPlans.value) {
    const key = `${item.kind}-${item.plan.id}`
    if (!(key in assignmentValues)) {
      assignmentValues[key] = ""
    }
  }
}
initAssignmentValues()

// ---- Information Progression helpers (vanilla _threadInformationPlans / _informationMovementId / _informationPlanChapter) ----
function threadInformationPlans(thread) {
  const threadId = thread.id || thread.thread_id
  const belongs = (plan) => (plan.related_thread_ids || []).includes(threadId)
  return [
    ...(props.foreshadowing || []).filter(belongs).map((plan) => ({ kind: "foreshadowing", plan })),
    ...(props.reveals || []).filter(belongs).map((plan) => ({ kind: "reveal", plan })),
  ].sort((left, right) => (
    (informationPlanChapter(left.plan, left.kind) || Number.MAX_SAFE_INTEGER)
    - (informationPlanChapter(right.plan, right.kind) || Number.MAX_SAFE_INTEGER)
  ))
}

function informationMovements(thread) {
  const plans = threadInformationPlans(thread)
  const movements = new Map()
  plans.forEach(({ kind, plan }) => {
    const movementId = plan?.provenance_meta?.information_movement_id || `legacy:${plan?.id || "unknown"}`
    if (!movements.has(movementId)) movements.set(movementId, [])
    movements.get(movementId).push({ kind, plan })
  })
  return movements
}

function informationMovementGroups(thread) {
  return Array.from(informationMovements(thread).values())
}

function threadHasInformationFocus(thread) {
  return Boolean(informationFocusKind.value && threadInformationPlans(thread).some((item) => item.kind === informationFocusKind.value))
}

function informationPlanChapter(plan, kind) {
  if (kind === "foreshadowing") {
    return plan.planned_seed_chapter || plan.planned_payoff_chapter || null
  }
  const chapters = (plan.reveal_stages || []).map((stage) => stage.chapter_index).filter(Boolean)
  return chapters.length ? Math.min(...chapters) : null
}

function informationPlanContent(plan, kind) {
  if (kind === "foreshadowing") return plan.summary || plan.hidden_meaning || plan.name
  return plan.secret_summary
}

function informationPlanName(item) {
  return item.kind === "foreshadowing"
    ? (item.plan.name || item.plan.summary || "未命名伏笔")
    : (item.plan.secret_summary || "未命名揭示")
}

onMounted(async () => {
  if (!informationFocusKind.value) return
  await nextTick()
  const target = informationSection.value?.querySelector('[data-information-focus-match="true"] > summary')
    || informationSection.value
  target?.scrollIntoView?.({ block: "center" })
  target?.focus?.({ preventScroll: true })
})

// ---- Status helpers ----
function threadStatusLabel(t) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(t.status) ? t.status : "draft"
  return structureAssetDisplay({ ...t, status: safeStatus }).label
}
function threadStatusBadgeClass(t) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(t.status) ? t.status : "draft"
  return displayStateBadgeClass(structureAssetDisplay({ ...t, status: safeStatus }).displayState)
}
function threadTypeLabel(t) { return THREAD_TYPE_LABELS[t.thread_type] || "未分类" }

// ---- Badges ----
function threadBadges(t) {
  const meta = t?.provenance_meta && typeof t.provenance_meta === "object" ? t.provenance_meta : {}
  const badges = []
  const source = meta.source || t.source
  if (source === "deep_import") badges.push({ text: "深度导入", cls: "badge-info" })
  else if (source === "manual") badges.push({ text: "手动", cls: "" })
  else if (source) badges.push({ text: source, cls: "" })
  for (const reason of assetAttentionReasons(t)) {
    badges.push({ text: reason, cls: "badge-warning" })
  }
  if (meta.phase) badges.push({ text: meta.phase, cls: "" })
  return badges
}

const emptyDetail = computed(() => (
  filterForm.source === "deep_import" || Boolean(filterForm.workflow_id)
    ? "结构分析不完整或无匹配结果，可重新分析，或重置筛选查看其他结构资产。"
    : "剧情线用于整理深度导入和人工维护后的叙事结构。"
))

// ---- Review actions ----
function threadReviewAction(t) {
  const id = t?.id || t?.thread_id
  if (!id) return null
  const meta = t?.provenance_meta && typeof t.provenance_meta === "object" ? t.provenance_meta : {}
  const reviewed = Boolean(meta.reviewed_at)
  const needsReview = meta.needs_review === true
  if (reviewed) return null
  const display = structureAssetDisplay(t)
  if (display.displayState === "active" && !needsReview) return null
  return {
    className: needsReview ? "btn-primary" : "",
    label: display.displayState === "active" ? "标记已检查" : "采用",
  }
}

// ---- Row action menu ----
function threadMenuItems(t) {
  const id = t.id || t.thread_id
  return [{ action: "delete-thread", label: "删除", class: "danger", data: { id } }]
}
function onThreadMenuSelect(item) {
  if (item.action === "delete-thread") deleteThread(item.data.id)
}

// ---- Navigation ----
function navigateScenes() { getRouter()?.navigate("outline", "scenes") }
function retryLoad() { getRouter()?.refresh() }

// ---- Filters ----
function applyFilters() {
  const f = { ...STRUCTURE_FILTER_DEFAULTS, ...filterForm, skip: 0 }
  Object.assign(filterForm, f)
  collapseFilters()
  navigateFilters(f, true)
}
function resetFilters() {
  Object.assign(filterForm, STRUCTURE_FILTER_DEFAULTS)
  filterForm.skip = 0
  collapseFilters()
  navigateFilters(filterForm, true)
}
function collapseFilters() {
  if (!filterPanel.value) return
  filterPanel.value.open = false
  filterPanel.value.querySelector(":scope > summary")?.focus()
}
function changePage(delta) {
  const total = props.threadsTotal || 0
  const newSkip = props.filters.skip + delta * props.filters.limit
  if (newSkip < 0 || newSkip >= total) return
  navigateFilters({ ...props.filters, skip: newSkip })
}

// ---- Bulk ----
function toggleOneThread(id, checked) { toggleBulkSelection(threadScope, id, checked) }
function toggleAllThread(e) { toggleAllBulkSelection(threadScope, props.threads.map((t) => t.id || t.thread_id), e.target.checked) }
function runBulkThread(action) { runBulkOutlineAction(threadScope, action, props.threads) }

// ---- CRUD ----
function editThread(id) { editThreadOp(id, props.threads) }
function deleteThread(id) { deleteThreadOp(id) }
function markThreadReviewed(id) { markThreadReviewedOp(id, props.threads) }
const threadDesc = (t) => threadDescription(t)

// ---- Assign information plan to thread ----
function assignPlan(kind, planId, threadId) {
  if (!threadId || !planId) return
  assignInformationPlan(planId, kind, threadId, props.unassignedForeshadowing, props.unassignedReveals)
}
</script>
