<!--
  OutlineArcsTab — outline/arcs 篇章子标签（vanilla _renderArcs L1290-1354）。
  按用户任务验证功能；DOM 与定位器可调整。
  筛选变更一律 router.navigate("outline", "arcs", true, query)。
-->
<template>
  <div>
    <p v-if="!inlineBackupOk" role="alert">本机草稿无法备份，请先保存到作品再离开。</p><p v-else-if="Object.keys(changedInlineDrafts).length" role="status">未保存行已在此浏览器备份，可稍后继续。</p>
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
          <tr @keydown.esc.stop="cancelInlineArc(a)" v-for="a in arcs" :key="a.id || a.arc_id" class="outline-structure-row" :data-id="a.id || a.arc_id">
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
            <td data-label="名称"><input v-if="inlineDrafts[a.id]" v-model="inlineDrafts[a.id].name" class="form-input" :disabled="inlineSaving" :aria-label="`篇章名称：${a.name || a.title}`" /><template v-else>{{ a.name || a.title }}</template></td>
            <td data-label="章节范围" class="outline-asset-mono"><template v-if="inlineDrafts[a.id]"><input v-model.number="inlineDrafts[a.id].start_chapter" type="number" min="1" class="form-input" aria-label="起始章节" :disabled="inlineSaving" /><input v-model.number="inlineDrafts[a.id].end_chapter" type="number" min="1" class="form-input" aria-label="结束章节" :disabled="inlineSaving" /></template><template v-else>{{ chapterRange(a) }}</template></td>
            <td data-label="标记">
              <template v-if="badgesFor(a).length">
                <span v-for="badge in badgesFor(a)" :key="`${badge.text}-${badge.cls}`" class="badge" :class="badge.cls">{{ badge.text }}</span>
              </template>
              <template v-else>-</template>
            </td>
            <td data-label="描述" class="outline-asset-description"><textarea v-if="inlineDrafts[a.id]" v-model="inlineDrafts[a.id].description" aria-label="篇章描述" :disabled="inlineSaving" /><template v-else>{{ arcDescription(a) }}</template></td>
            <td data-label="操作">
              <button class="btn btn-sm" :disabled="inlineSaving" @click="inlineDrafts[a.id] ? saveInlineArc(a) : startInlineArc(a)">{{ inlineSaving ? '保存中…' : inlineDrafts[a.id] ? '保存这一行' : '就地修改' }}</button>
              <button v-if="inlineDrafts[a.id]" class="btn btn-sm" :disabled="inlineSaving" @click="cancelInlineArc(a)">取消</button>
              <p v-if="inlineErrors[a.id]" role="status">{{ inlineErrors[a.id] }}</p>
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getAppState, getRouter, getConfirm } from "../../../bridge/index.js"
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
import { ACCOUNT_MARKER_KEY } from "../../../../shared/accountStorage.js"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import ActionMenu from "../../../components/ActionMenu.vue"
import OutlineBulkToolbar from "./OutlineBulkToolbar.vue"

const ARC_BULK_ACTIONS = [
  { action: "review-arcs", label: "批量采用 / 标记已检查", className: "btn-primary" },
  { action: "delete-arcs", label: "批量删除", className: "btn-danger" },
]

const props = defineProps({
  focusedAsset: { type: Object, default: null },
  projectId: { type: String, default: null },
  subView: { type: String, default: "arcs" },
  arcs: { type: Array, default: () => [] },
  arcsTotal: { type: Number, default: 0 },
  arcsLoadError: { type: String, default: null },
  filters: { type: Object, default: () => ({ ...STRUCTURE_FILTER_DEFAULTS }) },
})

const inlineSaved = reactive({})
const arcs = computed(() => props.arcs.map(arc => inlineSaved[arc.id] || arc))
watch(() => props.arcs, () => { for (const key of Object.keys(inlineSaved)) delete inlineSaved[key] })
const inlineDrafts = ref({}), inlineErrors = reactive({}), inlineSaving = ref(false)
let inlineAccount = "local"
try { inlineAccount = localStorage.getItem(ACCOUNT_MARKER_KEY) || "local" } catch { /* The backup below remains independently checked. */ }
const inlineDraftKey = `novel_outline_arc_edits:${inlineAccount}:${props.projectId}`
const inlineBackupOk = ref(true)
try { inlineDrafts.value = JSON.parse(localStorage.getItem(inlineDraftKey) || sessionStorage.getItem(inlineDraftKey) || '{}') } catch { inlineBackupOk.value = false }
function arcDraft(arc) { return { name: arc.name || arc.title || '', start_chapter: arc.start_chapter, end_chapter: arc.end_chapter, description: arcDescription(arc) === '-' ? '' : arcDescription(arc) } }
const changedInlineDrafts = computed(() => Object.fromEntries(Object.entries(inlineDrafts.value).filter(([id, draft]) => {
  const arc = arcs.value.find(item => item.id === id)
  return !arc || JSON.stringify(draft) !== JSON.stringify(arcDraft(arc))
})))
function cancelInlineArc(arc) {
  if (inlineSaving.value) return
  if (changedInlineDrafts.value[arc.id] && !getConfirm()('放弃这一行的未保存修改？')) return
  delete inlineDrafts.value[arc.id]
  delete inlineErrors[arc.id]
}
watch(changedInlineDrafts, value => {
  try { const raw = JSON.stringify(value); localStorage.setItem(inlineDraftKey, raw); inlineBackupOk.value = localStorage.getItem(inlineDraftKey) === raw } catch { inlineBackupOk.value = false }
}, { deep: true, flush: 'sync' })
useLeaveGuard(() => !inlineSaving.value && (!Object.keys(changedInlineDrafts.value).length || inlineBackupOk.value))
function startInlineArc(arc) { inlineDrafts.value[arc.id] = arcDraft(arc) }
async function saveInlineArc(arc) {
  const draft = inlineDrafts.value[arc.id]
  if (inlineSaving.value || !draft) return
  const validChapter = value => value == null || value === '' || (Number.isInteger(value) && value > 0)
  if (!draft.name.trim() || !validChapter(draft.start_chapter) || !validChapter(draft.end_chapter) || (draft.start_chapter && draft.end_chapter && draft.end_chapter < draft.start_chapter)) { inlineErrors[arc.id] = '请填写名称及有效的起止章节'; return }
  inlineSaving.value = true
  try {
    const saved = await getApi().outline.updateArc(arc.id, props.projectId, { title: draft.name.trim(), arc_goal: draft.description, start_chapter: draft.start_chapter || null, end_chapter: draft.end_chapter || null })
    if (getAppState()?.currentProjectId !== props.projectId) return
    inlineSaved[arc.id] = saved; delete inlineDrafts.value[arc.id]; inlineErrors[arc.id] = '已保存'
  } catch (err) { inlineErrors[arc.id] = err.message || '保存失败，输入已保留' }
  finally { inlineSaving.value = false }
}
function warnUnbackedRows(event) { if (inlineSaving.value || (Object.keys(changedInlineDrafts.value).length && !inlineBackupOk.value)) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => globalThis.addEventListener('beforeunload', warnUnbackedRows))
onBeforeUnmount(() => globalThis.removeEventListener('beforeunload', warnUnbackedRows))
const statusOptions = computed(() => structureStatusOptions("arcs"))

const scope = "outline-arcs"
const filterPanel = ref(null)
const activeFilterCount = computed(() => (
  ["status", "source", "needs_review", "workflow_id"].filter((key) => Boolean(props.filters?.[key])).length
))
const routeSignature = structureQueryFromState("arcs", props.filters).toString()
const restoreFilterFocusOnMount = Boolean(outlineFilterDrafts[scope]?.restoreFocus)
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
  if (restoreFilterFocus) outlineFilterDrafts[scope].restoreFocus = true
  const navigated = await getRouter()?.navigate("outline", "arcs", true, query)
  if (restoreFilterFocus && navigated !== true) delete outlineFilterDrafts[scope].restoreFocus
}

onMounted(async () => {
  if (props.focusedAsset) {
    editArcOp(props.focusedAsset.id, [props.focusedAsset])
    return
  }
  if (!restoreFilterFocusOnMount) return
  await nextTick()
  filterPanel.value?.querySelector(":scope > summary")?.focus()
})

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
  editArcOp(id, arcs.value)
}
function deleteArc(id) {
  deleteArcOp(id)
}
function markReviewed(id) {
  markArcReviewed(id, props.arcs)
}
</script>
