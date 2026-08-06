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
    <div class="scene-management-filters" aria-label="结构资产筛选">
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
        <summary>诊断筛选{{ filterForm.workflow_id ? "（1）" : "" }}</summary>
        <label class="scene-filter-field scene-filter-field--wide">
          <span>处理批次编号</span>
          <input class="form-input" id="outline-filter-workflow-id" data-diagnostic-field v-model="filterForm.workflow_id" placeholder="按处理批次编号精确筛选" />
        </label>
      </details>
      <div class="scene-filter-actions">
        <button class="btn btn-sm btn-primary" data-action="apply-outline-structure-filters" @click="applyFilters">应用</button>
        <button class="btn btn-sm" data-action="reset-outline-structure-filters" @click="resetFilters">重置</button>
      </div>
    </div>

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
            <td data-label="类型" class="outline-asset-meta">{{ t.thread_type || "-" }}</td>
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
    <section class="outline-information-progress" id="outline-thread-information">
      <h3>信息推进</h3>
      <p class="writing-form-hint">伏笔与揭示在这里按同一条信息运动统一查看；底层计划仍供写作与上下文流程使用。</p>
      <template v-if="threads.length > 0">
        <details v-for="thread in threads" :key="thread.id || thread.thread_id" class="outline-preview-section" :open="threadInformationPlans(thread).length === 0">
          <summary>{{ thread.name || thread.title || "剧情线" }} · 信息推进 {{ informationMovements(thread).size }}</summary>
          <template v-if="informationMovements(thread).size">
            <ol v-for="(items, idx) in informationMovementGroups(thread)" :key="idx" class="outline-information-timeline">
              <li v-for="item in items" :key="item.plan.id" class="outline-information-node">
                <span class="badge">{{ item.kind === "foreshadowing" ? "暗示 / 兑现" : "局部 / 完整揭示" }}</span>
                <span v-if="informationPlanChapter(item.plan, item.kind)" class="outline-asset-mono">第 {{ informationPlanChapter(item.plan, item.kind) }} 章</span>
                <span>{{ informationPlanContent(item.plan, item.kind) }}</span>
              </li>
            </ol>
          </template>
          <p v-else class="writing-form-hint">尚未设计隐藏、暗示、局部揭示或兑现。</p>
        </details>
      </template>
      <p v-else class="writing-form-hint">创建剧情线后可设计信息推进。</p>

      <!-- 未归入剧情线 -->
      <details class="outline-preview-section" :open="unassignedPlans.length > 0">
        <summary>未归入剧情线（{{ unassignedPlans.length }}）</summary>
        <template v-if="unassignedPlans.length">
          <ul>
            <li v-for="item in unassignedPlans" :key="`${item.kind}-${item.plan.id}`" class="outline-information-unassigned">
              <span>{{ item.kind === "foreshadowing" ? (item.plan.name || item.plan.summary) : item.plan.secret_summary }}</span>
              <select class="form-select" data-role="information-thread-assignment" :data-kind="item.kind" :data-id="item.plan.id" v-model="assignmentValues[`${item.kind}-${item.plan.id}`]" @change="assignPlan(item.kind, item.plan.id, $event.target.value)">
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
import { computed, reactive } from "vue"
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
  filters: { type: Object, default: () => ({ ...STRUCTURE_FILTER_DEFAULTS }) },
})

const threadStatusOptions = computed(() => structureStatusOptions("threads"))

// ---- Filters ----
const filterForm = reactive({ ...STRUCTURE_FILTER_DEFAULTS })
Object.assign(filterForm, props.filters)

const threadsTotal = computed(() => props.threadsTotal || 0)
const threadsCurrentPage = computed(() => Math.floor(filterForm.skip / filterForm.limit) + 1)
const threadsTotalPages = computed(() => Math.ceil(threadsTotal.value / filterForm.limit) || 1)
const threadsLoadError = computed(() => props.threadsLoadError)

// ---- Threads Bulk Selection ----
const threadScope = "outline-threads"
const threadIsSelected = (id) => getBulkSelection(threadScope).has(String(id))
const threadSelectAll = computed(() => {
  const ids = props.threads.map((t) => t.id || t.thread_id)
  return computeSelectAll(threadScope, ids)
})

// ---- Unassigned Plans for Information Progression ----
const unassignedPlans = computed(() => [
  ...(props.unassignedForeshadowing || []).map((plan) => ({ kind: "foreshadowing", plan })),
  ...(props.unassignedReveals || []).map((plan) => ({ kind: "reveal", plan })),
])

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

// ---- Status helpers ----
function threadStatusLabel(t) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(t.status) ? t.status : "draft"
  return structureAssetDisplay({ ...t, status: safeStatus }).label
}
function threadStatusBadgeClass(t) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(t.status) ? t.status : "draft"
  return displayStateBadgeClass(structureAssetDisplay({ ...t, status: safeStatus }).displayState)
}

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
  const query = structureQueryFromState("threads", f)
  getRouter()?.navigate("outline", "threads", true, query)
}
function resetFilters() {
  Object.assign(filterForm, STRUCTURE_FILTER_DEFAULTS)
  filterForm.skip = 0
  const query = structureQueryFromState("threads", filterForm)
  getRouter()?.navigate("outline", "threads", true, query)
}
function changePage(delta) {
  const total = props.threadsTotal || 0
  const newSkip = filterForm.skip + delta * filterForm.limit
  if (newSkip < 0 || newSkip >= total) return
  filterForm.skip = newSkip
  const query = structureQueryFromState("threads", filterForm)
  getRouter()?.navigate("outline", "threads", true, query)
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
