<!--
  OutlineArcsTab — outline/arcs 篇章子标签（vanilla _renderArcs L1290-1354）。
  DOM 结构/class/id/data-action 逐节点对齐。
  筛选变更一律 router.navigate("outline", "arcs", true, query)。
-->
<template>
  <div>
    <!-- 筛选面板 -->
    <details ref="filterPanel" class="outline-structure-filters">
      <summary>
        <span class="outline-structure-filters__label">筛选篇章</span>
        <span class="outline-structure-filters__summary">{{ activeFilterCount ? `已启用 ${activeFilterCount} 项` : "未启用" }}</span>
      </summary>
      <div class="scene-management-filters" aria-label="篇章筛选条件">
        <label class="scene-filter-field">
          <span>状态</span>
          <select id="outline-filter-status" class="form-select" v-model="filterForm.status">
            <option value="">全部状态</option>
            <option v-for="[val, label] in statusOptions" :key="val" :value="val">{{ label }}</option>
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

    <!-- 空态 -->
    <template v-if="arcs.length === 0 && !loadError">
      <div class="empty-state">
        <div class="empty-icon">&#128204;</div>
        <p>暂无篇章。</p>
        <p class="outline-empty-detail">{{ emptyDetail }}</p>
        <button class="btn btn-sm btn-primary" data-action="nav-scenes" @click="navigateScenes">从已采用场景开始整理</button>
      </div>
    </template>

    <!-- 错误态 -->
    <div v-else-if="loadError" class="empty-state" role="alert">
      <div class="empty-icon">!</div>
      <p>加载失败</p>
      <p class="outline-empty-detail">{{ loadError }}</p>
      <button class="btn btn-sm" data-action="retry-outline-load" @click="retryLoad">重新加载</button>
    </div>

    <!-- 列表 -->
    <template v-else>
      <OutlineBulkToolbar scope="outline-arcs" :actions="ARC_BULK_ACTIONS" noun="篇章" @run="runBulk" />

      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">
              <label class="selection-checkbox" title="全选当前篇章">
                <input type="checkbox"
                  data-action="bulk-toggle-all"
                  data-scope="outline-arcs"
                  :checked="selectAllState.checked"
                  :indeterminate="selectAllState.indeterminate"
                  :disabled="selectAllState.disabled"
                  @change="toggleAll"
                />
                <span class="sr-only">全选当前篇章</span>
              </label>
            </th>
            <th>状态</th>
            <th>名称</th>
            <th>章节范围</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in arcs" :key="a.id || a.arc_id" class="outline-structure-row" :data-id="a.id || a.arc_id">
            <td class="selection-cell">
              <label class="selection-checkbox" :title="`选择 ${a.name || a.title || '篇章'}`">
                <input type="checkbox"
                  data-action="bulk-toggle-one"
                  data-scope="outline-arcs"
                  :data-id="a.id || a.arc_id"
                  :checked="isSelected(a.id || a.arc_id)"
                  @change="toggleOne(a.id || a.arc_id, $event.target.checked)"
                />
                <span class="sr-only">选择 {{ a.name || a.title || '篇章' }}</span>
              </label>
            </td>
            <td data-label="状态"><span class="badge" :class="statusBadgeClass(a)">{{ statusLabel(a) }}</span></td>
            <td data-label="名称">{{ a.name || a.title }}</td>
            <td data-label="章节范围" class="outline-asset-mono">{{ chapterRange(a) }}</td>
            <td data-label="标记">
              <template v-if="badgesFor(a).length">
                <span v-for="badge in badgesFor(a)" :key="`${badge.text}-${badge.cls}`" class="badge" :class="badge.cls">{{ badge.text }}</span>
              </template>
              <template v-else>-</template>
            </td>
            <td data-label="描述" class="outline-asset-description">{{ arcDescription(a) }}</td>
            <td data-label="操作">
              <button v-if="reviewActionHtml(a)" class="btn btn-sm" :class="reviewActionHtml(a).className" data-action="mark-arc-reviewed" :data-id="a.id || a.arc_id" @click="markReviewed(a.id || a.arc_id)">{{ reviewActionHtml(a).label }}</button>
              <button class="btn btn-sm btn-primary" data-action="edit-arc" :data-id="a.id || a.arc_id" @click="editArc(a.id || a.arc_id)">编辑</button>
              <ActionMenu :menu-id="`arc-actions-${a.id || a.arc_id}`" :label="`${a.name || a.title || '篇章'}的更多操作`" :items="arcMenuItems(a)" @select="onArcMenuSelect" />
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div v-if="total > filterForm.limit" class="outline-structure-pagination">
        <button class="btn btn-sm" :disabled="filterForm.skip <= 0" data-action="prev-outline-structure-page" @click="changePage(-1)">上一页</button>
        <span class="outline-structure-pagination__info">第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条</span>
        <button class="btn btn-sm" :disabled="filterForm.skip + filterForm.limit >= total" data-action="next-outline-structure-page" @click="changePage(1)">下一页</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { getRouter, getToast } from "../../../bridge/index.js"
import { structureAssetDisplay, displayStateBadgeClass, assetAttentionReasons } from "../../../../shared/assetDisplayState.js"
import {
  STRUCTURE_FILTER_DEFAULTS,
  STRUCTURE_SOURCE_OPTIONS,
  structureStatusOptions,
  structureQueryFromState,
} from "../logic/outlineStructure.js"
import {
  arcDescription,
  deleteArc as deleteArcOp,
  editArc as editArcOp,
  markArcReviewed,
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

const ARC_BULK_ACTIONS = [
  { action: "review-arcs", label: "批量采用 / 标记已检查", className: "btn-primary" },
  { action: "delete-arcs", label: "批量删除", className: "btn-danger" },
]

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "arcs" },
  arcs: { type: Array, default: () => [] },
  arcsTotal: { type: Number, default: 0 },
  arcsLoadError: { type: String, default: null },
  filters: { type: Object, default: () => ({ ...STRUCTURE_FILTER_DEFAULTS }) },
})

const statusOptions = computed(() => structureStatusOptions("arcs"))

const scope = "outline-arcs"
const filterPanel = ref(null)
const activeFilterCount = computed(() => (
  ["status", "source", "needs_review", "workflow_id"].filter((key) => Boolean(props.filters?.[key])).length
))
const routeSignature = structureQueryFromState("arcs", props.filters).toString()
const restoredDraft = outlineFilterDrafts[scope]?.routeSignature === routeSignature
  ? outlineFilterDrafts[scope].value
  : null
if (!restoredDraft) delete outlineFilterDrafts[scope]
const filterForm = reactive({
  ...STRUCTURE_FILTER_DEFAULTS,
  ...props.filters,
  ...(restoredDraft || {}),
  skip: props.filters.skip,
  limit: props.filters.limit,
})
watch(filterForm, (value) => {
  outlineFilterDrafts[scope] = {
    routeSignature: outlineFilterDrafts[scope]?.routeSignature || routeSignature,
    value: { ...value },
  }
}, { immediate: true, deep: true, flush: "sync" })

async function navigateFilters(filters, restoreFilterFocus = false) {
  const query = structureQueryFromState("arcs", filters)
  outlineFilterDrafts[scope].routeSignature = query.toString()
  const navigated = await getRouter()?.navigate("outline", "arcs", true, query)
  if (restoreFilterFocus && navigated !== false) {
    document.querySelector(".outline-structure-filters > summary")?.focus()
  }
}

const isSelected = (id) => getBulkSelection(scope).has(String(id))
watch(
  () => props.arcs.map((item) => item.id || item.arc_id),
  (ids) => reconcileBulkSelection(scope, ids),
  { immediate: true },
)

const selectAllState = computed(() => {
  const ids = props.arcs.map((a) => a.id || a.arc_id)
  return computeSelectAll(scope, ids)
})

const total = computed(() => props.arcsTotal || 0)
const currentPage = computed(() => Math.floor(filterForm.skip / filterForm.limit) + 1)
const totalPages = computed(() => Math.ceil(total.value / filterForm.limit) || 1)
const loadError = computed(() => props.arcsLoadError)
const emptyDetail = computed(() => (
  filterForm.source === "deep_import" || Boolean(filterForm.workflow_id)
    ? "结构分析不完整或无匹配结果，可重新分析，或重置筛选查看其他结构资产。"
    : "篇章用于整理深度导入和人工维护后的叙事结构。"
))

function statusLabel(a) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(a.status) ? a.status : "draft"
  return structureAssetDisplay({ ...a, status: safeStatus }).label
}
function statusBadgeClass(a) {
  const safeStatus = new Set(["canonical", "draft", "candidate", "deprecated"]).has(a.status) ? a.status : "draft"
  return displayStateBadgeClass(structureAssetDisplay({ ...a, status: safeStatus }).displayState)
}
function chapterRange(a) {
  return a.start_chapter != null && a.end_chapter != null ? `${a.start_chapter}-${a.end_chapter}` : "-"
}
function badgesFor(a) {
  const meta = a?.provenance_meta && typeof a.provenance_meta === "object" ? a.provenance_meta : {}
  const badges = []
  const source = meta.source || a.source
  if (source === "deep_import") badges.push({ text: "深度导入", cls: "badge-info" })
  else if (source === "manual") badges.push({ text: "手动", cls: "" })
  else if (source) badges.push({ text: source, cls: "" })
  for (const reason of assetAttentionReasons(a)) {
    badges.push({ text: reason, cls: "badge-warning" })
  }
  if (meta.phase) badges.push({ text: meta.phase, cls: "" })
  return badges
}

function reviewActionHtml(a) {
  const id = a?.id || a?.arc_id
  if (!id) return null
  const meta = a?.provenance_meta && typeof a.provenance_meta === "object" ? a.provenance_meta : {}
  const reviewed = Boolean(meta.reviewed_at)
  const needsReview = meta.needs_review === true
  if (reviewed) return null
  const display = structureAssetDisplay(a)
  if (display.displayState === "active" && !needsReview) return null
  return {
    className: needsReview ? "btn-primary" : "",
    label: display.displayState === "active" ? "标记已检查" : "采用",
  }
}

function navigateScenes() {
  getRouter()?.navigate("outline", "scenes")
}

function retryLoad() {
  getRouter()?.refresh()
}

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
  const total = props.arcsTotal || 0
  const newSkip = props.filters.skip + delta * props.filters.limit
  if (newSkip < 0 || newSkip >= total) return
  navigateFilters({ ...props.filters, skip: newSkip })
}

function toggleOne(id, checked) {
  toggleBulkSelection(scope, id, checked)
}
function toggleAll(e) {
  toggleAllBulkSelection(scope, props.arcs.map((a) => a.id || a.arc_id), e.target.checked)
}
function runBulk(action) {
  const items = props.arcs
  runBulkOutlineAction(scope, action, items)
}

function arcMenuItems(a) {
  const id = a.id || a.arc_id
  return [{ action: "delete-arc", label: "删除", class: "danger", data: { id } }]
}
function onArcMenuSelect(item) {
  if (item.action === "delete-arc") deleteArc(item.data.id)
}

function editArc(id) {
  editArcOp(id, props.arcs)
}
function deleteArc(id) {
  deleteArcOp(id)
}
function markReviewed(id) {
  markArcReviewed(id, props.arcs)
}
</script>
