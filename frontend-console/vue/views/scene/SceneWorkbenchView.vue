<template>
  <div class="outline-scene-layout">
    <div class="subnav">
      <button type="button" class="subnav-item" data-action="nav-story-outline" @click="navigateOutline('story-outline')">故事总览</button>
      <button type="button" class="subnav-item" data-action="nav-arcs" @click="navigateOutline('arcs')">篇章</button>
      <button type="button" class="subnav-item" data-action="nav-threads" @click="navigateOutline('threads')">剧情线</button>
      <span class="subnav-item active" aria-current="page" data-action="nav-scenes">场景</span>
      <div class="scene-workbench-actions" aria-label="场景操作">
        <span class="scene-view-mode-toggle" aria-label="场景浏览模式">
          <button class="btn btn-sm" :class="{ 'btn-primary': viewMode === 'normal' }" data-action="set-scene-view-mode" data-mode="normal" @click="setViewMode('normal')">普通</button>
          <button class="btn btn-sm" :class="{ 'btn-primary': viewMode === 'hot' }" data-action="set-scene-view-mode" data-mode="hot" @click="setViewMode('hot')">热点</button>
        </span>
        <button class="btn btn-sm btn-primary" data-action="ai-create-planned-scene" @click="createPlannedScene">AI 创作细纲</button>
        <button class="btn btn-sm" data-action="scene-auto-extract" :disabled="autoExtractionBusy" @click="showAutoExtractForm">{{ autoExtractionBusy ? "整理中..." : "从正文整理场景" }}</button>
        <span data-role="smart-dedup-action"></span>
      </div>
    </div>

    <div data-outline-generate-slot>
      <OutlineGenerateProgressCard />
    </div>

    <div class="scene-workbench-shell">
      <SceneAutoExtractProgressCard @cancel="cancelAutoExtraction" @dismiss="dismissAutoExtraction" />

      <div v-if="fusionTask.progress" class="scene-progress-card-wrap" data-role="scene-fusion-preview-progress">
        <WorkflowProgressCard
          :progress="fusionTask.progress"
          title="场景融合预览"
          :message="fusionTask.progress.message || ''"
          :collapsible="true"
          :show-task-id="false"
        />
        <button v-if="fusionTask.preview" class="btn btn-sm btn-primary" data-action="view-scene-fusion-preview" @click="modalController.showCompletedFusionPreview()">查看预览</button>
        <button v-if="!fusionTask.progress.terminal" class="btn btn-sm" data-action="cancel-scene-fusion-preview" @click="modalController.cancelFusionTask()">取消任务</button>
        <button v-else class="btn btn-sm" data-action="dismiss-scene-fusion-preview" @click="modalController.dismissFusionTask()">关闭</button>
      </div>

      <div v-if="pendingSuggestionCount" class="scene-fusion-queue" role="status">
        <div>
          <strong>{{ pendingSuggestionCount }} 条场景建议待处理</strong>
          <span>包含场景合并决定或受保护内容的替换检查，刷新后仍可继续。</span>
        </div>
        <button class="btn btn-sm btn-primary" data-action="show-fusion-suggestions" @click="modalController.showSuggestions()">逐条处理</button>
        <button v-if="dismissibleSuggestionCount" class="btn btn-sm" data-action="dismiss-fusion-suggestions" @click="modalController.dismissAllSuggestions()">忽略融合建议</button>
      </div>

      <div v-if="loading && !workbench" class="loading-skeleton" role="status" aria-live="polite" aria-busy="true">
        <span class="sr-only">场景工作台加载中...</span>
        <div class="skeleton loading-skeleton__heading" aria-hidden="true"></div>
        <div class="skeleton loading-skeleton__line" aria-hidden="true"></div>
        <div class="skeleton loading-skeleton__line loading-skeleton__line--medium" aria-hidden="true"></div>
      </div>
      <div v-else-if="loadError && !workbench" class="empty-state" role="alert">
        <div class="empty-icon">!</div>
        <p>场景工作台暂不可用。</p>
        <p>{{ loadError }}</p>
        <button class="btn btn-sm" data-action="retry-scene-workbench" @click="refresh()">重新加载</button>
      </div>
      <div v-else-if="workbench" class="scene-workbench" :class="{ 'is-narrow': narrow }">
        <section class="scene-workbench__organize">
          <div class="scene-management-filters" aria-label="场景筛选">
            <label class="scene-filter-field scene-filter-field--wide"><span>搜索</span><input id="scene-filter-q" v-model="filterForm.q" class="form-input" placeholder="标题 / 目标 / 冲突" /></label>
            <label class="scene-filter-field"><span>起始章</span><input id="scene-filter-chapter-from" v-model="filterForm.chapter_from" class="form-input" type="number" min="1" /></label>
            <label class="scene-filter-field"><span>结束章</span><input id="scene-filter-chapter-to" v-model="filterForm.chapter_to" class="form-input" type="number" min="1" /></label>
            <label class="scene-filter-field"><span>状态</span><select id="scene-filter-status" v-model="filterForm.status" class="form-select"><option value="">全部状态</option><option v-for="[value, label] in STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
            <label class="scene-filter-field"><span>来源</span><select id="scene-filter-source" v-model="filterForm.source" class="form-select"><option value="">全部来源</option><option v-for="[value, label] in SOURCE_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
            <label class="scene-filter-field"><span>注意</span><select id="scene-filter-needs-review" v-model="filterForm.needs_review" class="form-select"><option value="">全部注意原因</option><option value="true">需要人工检查</option><option value="false">无注意项</option></select></label>
            <div class="scene-filter-actions">
              <button class="btn btn-sm" data-action="toggle-advanced-scene-filters" @click="toggleAdvanced">{{ advancedFiltersOpen ? '▾' : '▸' }} 高级</button>
              <button class="btn btn-sm btn-primary" data-action="apply-scene-filters" @click="applyFilters">应用</button>
              <button class="btn btn-sm" data-action="reset-scene-filters" @click="resetFilters">重置</button>
            </div>
            <template v-if="advancedFiltersOpen">
              <details class="scene-filter-field scene-filter-field--wide" :open="Boolean(filterForm.workflow_id)">
                <summary>诊断筛选{{ filterForm.workflow_id ? '（1）' : '' }}</summary>
                <label><span>Workflow 诊断 ID</span><input id="scene-filter-workflow-id" v-model="filterForm.workflow_id" class="form-input" data-diagnostic-field placeholder="workflow_id" /></label>
              </details>
              <label class="scene-filter-field"><span>边界</span><select id="scene-filter-boundary-status" v-model="filterForm.boundary_status" class="form-select"><option value="">全部边界</option><option v-for="[value, label] in BOUNDARY_STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
              <label class="scene-filter-field"><span>阶段</span><select id="scene-filter-phase" v-model="filterForm.phase" class="form-select"><option value="">全部阶段</option><option v-for="[value, label] in PHASE_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
              <label class="scene-filter-field"><span>置信度</span><select id="scene-filter-confidence-band" v-model="filterForm.confidence_band" class="form-select"><option value="">全部置信度</option><option v-for="[value, label] in CONFIDENCE_BAND_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
              <label class="scene-filter-checkbox"><input id="scene-filter-phase1a-fallback" v-model="filterForm.phase1a_fallback" type="checkbox" /><span>Phase 1A fallback</span></label>
            </template>
          </div>

          <section v-if="viewMode === 'hot' && workbench.progress" class="scene-progress-panel" aria-label="剧情进度">
            <div class="scene-progress-panel__heading"><strong>当前剧情定位</strong><span>{{ workbench.progress.as_of_chapter == null ? '尚无有效章节' : `截至第 ${workbench.progress.as_of_chapter} 章` }}</span></div>
            <div class="scene-progress-bar">
              <button v-for="[key, label] in PROGRESS_ITEMS" :key="key" class="scene-progress-filter" :class="{ active: filters.segment === key }" data-action="filter-progress-segment" :data-segment="key" @click="toggleSegment(key)"><span>{{ label }}</span><strong>{{ workbench.progress[key] ?? 0 }}</strong></button>
            </div>
          </section>

          <div class="scene-health-bar">
            <button v-for="[key, fallback] in HEALTH_ORDER" :key="key" class="scene-health-filter" :class="{ active: (filters.health || activeHealth) === key }" data-action="filter-health" :data-id="key" @click="toggleHealth(key)">
              <span>{{ healthLabel(key) || fallback }}</span><strong>{{ workbench.health?.[key]?.count ?? 0 }}</strong>
              <small v-if="key === 'needs_organize' && healthBreakdownText">{{ healthBreakdownText }}</small>
            </button>
          </div>
          <p v-if="healthBreakdownText" class="scene-health-count-note" role="note">待整理总数按场景去重；结构、正文定位和合并等原因可能同时出现在同一场景。</p>

          <div class="scene-fusion-toolbar" aria-label="场景批量操作">
            <div class="scene-fusion-toolbar__status"><strong>{{ selectedIds.size }}</strong><span>个场景已选</span><span class="scene-fusion-toolbar__hint">{{ selectionHint }}</span></div>
            <button class="btn btn-sm" data-action="toggle-visible-fusion-selection" :disabled="visibleIds.length === 0" :title="allVisibleSelected ? '取消选择当前列表中的场景' : '选择当前列表中的全部场景'" @click="toggleVisibleSelection">{{ allVisibleSelected ? '取消全选' : '全选当前列表' }}</button>
            <button class="btn btn-sm btn-primary" data-action="handle-selected-context-actions" :disabled="selectedIds.size === 0" @click="runSelectedContextActions">{{ batchLabel }}</button>
            <button class="btn btn-sm" data-action="start-selected-merge" :disabled="selectedIds.size < 2" @click="modalController.startSelectedMerge(Array.from(selectedIds))">机械合并</button>
            <button class="btn btn-sm btn-primary" data-action="start-ai-fusion-draft" :disabled="selectedIds.size < 2" @click="modalController.startFusion(Array.from(selectedIds))">AI 融合建议</button>
          </div>

          <div v-if="items.length || visibleUnassignedChapters.length" class="scene-workbench-list">
            <article v-for="item in items" :key="item.scene?.id" class="scene-workbench-row" :class="{ 'is-selected': selectedItem?.scene?.id === item.scene?.id }" :data-id="item.scene?.id">
              <label class="scene-fusion-select selection-checkbox" title="选择用于批量操作"><input type="checkbox" data-action="toggle-fusion-selection" :data-id="item.scene?.id" aria-label="选择用于批量操作" :checked="selectedIds.has(item.scene?.id)" @change="toggleSelection(item.scene?.id, $event.target.checked)" /></label>
              <div class="scene-workbench-row__content">
                <button class="scene-workbench-row__main" data-action="select-workbench-scene" :data-id="item.scene?.id" @click="selectScene(item.scene?.id)">
                  <div class="scene-workbench-row__meta"><span>#{{ sceneIndex(item.scene) }}</span><span>{{ sceneStatusLabel(item.scene) }}</span><span>{{ sceneSourceLabel(item.scene) }}</span><span>{{ item.chapter_range || '未关联章节' }}</span><span v-if="segmentLabel(item.segment)" class="scene-progress-chip" :class="`scene-progress-chip--${item.segment}`">{{ segmentLabel(item.segment) }}</span></div>
                  <div class="scene-workbench-row__title">{{ item.scene?.title || '未命名场景' }}</div>
                  <div class="scene-workbench-row__summary">{{ item.summary || item.scene?.goal || '暂无目标' }}</div>
                  <div v-if="rowSpanSummary(item)" class="scene-workbench-row__mapping" aria-label="场景正文范围">{{ rowSpanSummary(item) }}</div>
                  <div v-if="rowOverlapSummary(item)" class="scene-workbench-row__overlap" aria-label="场景正文范围重叠">{{ rowOverlapSummary(item) }}</div>
                </button>
                <div class="scene-workbench-row__health"><button v-for="health in item.health || []" :key="health" class="scene-health-chip" data-action="handle-scene-health" :data-id="item.scene?.id" :data-health="health" :title="sceneContextAction(item, health).label" @click="runContextAction(item, sceneContextAction(item, health))">{{ healthLabel(health) }}</button></div>
              </div>
              <div class="scene-workbench-row__actions">
                <button class="btn btn-sm scene-context-action" :class="{ 'btn-primary': sceneContextAction(item).key !== 'edit' }" :data-action="sceneContextAction(item).action" :data-id="item.scene?.id" @click="runContextAction(item)">{{ sceneContextAction(item).label }}</button>
                <button v-if="firstOverlap(item)?.counterpart_scene_id" class="btn btn-sm scene-overlap-shortcut" data-action="open-overlap-scene" :data-id="firstOverlap(item).counterpart_scene_id" @click="openOverlap(firstOverlap(item).counterpart_scene_id)">查看「{{ overlapCounterpartLabel(firstOverlap(item)) }}」</button>
                <button v-if="sceneContextAction(item).key !== 'edit'" class="btn btn-sm scene-secondary-action" data-action="edit-workbench-scene" :data-id="item.scene?.id" @click="selectScene(item.scene?.id)">编辑</button>
                <ActionMenu :menu-id="`scene-actions-${item.scene?.id}`" :label="`${item.scene?.title || '未命名场景'}的更多操作`" :items="menuItems(item)" @select="handleMenu(item, $event)" />
              </div>
            </article>
            <article v-for="chapter in visibleUnassignedChapters" :key="`unassigned-${chapter}`" class="scene-workbench-row scene-workbench-row--unassigned">
              <div class="scene-workbench-row__main"><div class="scene-workbench-row__meta"><span>未归类章节</span></div><div class="scene-workbench-row__title">第 {{ chapter }} 章</div><div class="scene-workbench-row__summary">尚未分配到场景</div></div>
              <div class="scene-workbench-row__actions"><button class="btn btn-sm" data-action="assign-unassigned-chapter" :data-chapter="chapter" @click="modalController.assignChapter(chapter)">分配场景</button></div>
            </article>
          </div>
          <div v-else class="empty-state"><p>暂无需要整理的场景。</p></div>

          <div v-if="total > filters.limit" class="scene-workbench-pagination">
            <button class="btn btn-sm" data-action="prev-scene-page" :disabled="filters.skip <= 0" @click="changePage(-1)">上一页</button>
            <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条</span>
            <button class="btn btn-sm" data-action="next-scene-page" :disabled="filters.skip + filters.limit >= total" @click="changePage(1)">下一页</button>
          </div>
        </section>

        <details v-if="!narrow" class="workspace-rail scene-detail-rail workspace-rail--right" :data-workspace-rail-key="railKey" :open="railOpen" @toggle="onRailToggle">
          <summary class="workspace-rail__summary" :aria-label="`${railOpen ? '收起' : '展开'}场景详情`"><span class="workspace-rail__title">场景详情</span><span class="workspace-rail__chevron" aria-hidden="true"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg></span></summary>
          <div class="workspace-rail__body"><aside class="scene-workbench__detail"><SceneDetailPanel :item="selectedItem" :draft="detailDraft" :narrow="false" @context="runContextAction(selectedItem)" @save="saveScene(selectedItem?.scene?.id, detailDraft)" @merge="modalController.startMerge(selectedItem?.scene?.id)" @split="modalController.startSplit(selectedItem?.scene?.id)" @replacement="openOverlap" /></aside></div>
        </details>

        <div v-if="narrow && mobileDetailOpen && selectedItem" class="scene-workbench-drawer"><SceneDetailPanel :item="selectedItem" :draft="detailDraft" :narrow="true" @close="clearSelectedScene" @context="runContextAction(selectedItem)" @save="saveScene(selectedItem.scene.id, detailDraft)" @merge="modalController.startMerge(selectedItem.scene.id)" @split="modalController.startSplit(selectedItem.scene.id)" @replacement="openOverlap" /></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, reactive, ref, watch } from "vue"
import { structureAssetDisplay } from "../../../shared/assetDisplayState.js"
import { getRouter } from "../../bridge/index.js"
import ActionMenu from "../../components/ActionMenu.vue"
import WorkflowProgressCard from "../../components/WorkflowProgressCard.vue"
import OutlineGenerateProgressCard from "../outline/ai/OutlineGenerateProgressCard.vue"
import { showOutlineLayerAiForm } from "../outline/ai/outlineAiOps.js"
import SceneAutoExtractProgressCard from "./SceneAutoExtractProgressCard.vue"
import { useSceneWorkbench } from "./useSceneWorkbench.js"
import {
  BOUNDARY_STATUS_OPTIONS,
  CONFIDENCE_BAND_OPTIONS,
  HEALTH_ORDER,
  PHASE_OPTIONS,
  SOURCE_OPTIONS,
  STATUS_OPTIONS,
  TAG_OPTIONS,
  healthReasons,
  overlapCounterpartLabel,
  sceneContextAction,
  sceneReviewState,
  sceneSourceLabel,
  sceneStatusLabel,
  spanSummaryLabel,
} from "./sceneModel.js"

const PROGRESS_ITEMS = [["current", "当前"], ["upcoming", "后续"], ["past", "已写过"], ["unassigned", "未定位"]]

const props = defineProps({
  projectId: { type: String, required: true },
  workbench: { type: Object, default: null },
  fusionSuggestions: { type: Array, default: () => [] },
  viewMode: { type: String, default: "hot" },
  selectedSceneId: { type: String, default: null },
  sceneFilters: { type: Object, default: () => ({}) },
  activeHealth: { type: String, default: null },
  advancedFiltersOpen: { type: Boolean, default: false },
  sceneLoadError: { type: String, default: null },
})

const vm = useSceneWorkbench(props)
const {
  activeHealth, advancedFiltersOpen, allVisibleSelected, applyFilters, autoExtractionBusy,
  cancelAutoExtraction, changePage, clearSelectedScene, dismissAutoExtraction,
  dismissibleSuggestionCount, filterForm, filters, healthLabel, items, loadError,
  loading, mobileDetailOpen, modalController, narrow, openOverlap, openWriting,
  fusionTask, pendingSuggestionCount, refresh, resetFilters, runContextAction,
  runSelectedContextActions, saveScene, selectScene, selectedIds, selectedItem,
  setViewMode, showAutoExtractForm, toggleAdvanced, toggleHealth, toggleSegment,
  toggleSelection, toggleVisibleSelection, total, viewMode, visibleIds, workbench,
} = vm

const currentPage = computed(() => Math.floor(filters.skip / filters.limit) + 1)
const totalPages = computed(() => Math.ceil(total.value / filters.limit) || 1)
const visibleUnassignedChapters = computed(() => {
  const chapters = workbench.value?.unassigned_chapters || []
  if (!chapters.length && activeHealth.value !== "unassigned") return []
  if (activeHealth.value && activeHealth.value !== "unassigned") return []
  return chapters
})
const healthBreakdownText = computed(() => {
  const breakdown = workbench.value?.health?.needs_organize?.breakdown || {}
  return [
    breakdown.scene_structure ? `结构 ${breakdown.scene_structure}` : "",
    breakdown.source_mapping ? `定位 ${breakdown.source_mapping}` : "",
    breakdown.scene_fusion_suggestion ? `融合 ${breakdown.scene_fusion_suggestion}` : "",
  ].filter(Boolean).join(" · ")
})
const selectionHint = computed(() => selectedIds.value.size < 2 ? `再选 ${2 - selectedIds.value.size} 个即可融合` : "已可开始融合")
const batchLabel = computed(() => {
  const selected = vm.selectedItems.value
  const kinds = new Set(selected.map((item) => sceneContextAction(item).key))
  if (kinds.size === 1 && kinds.has("review")) return "采用选中项"
  if (kinds.size === 1 && kinds.has("source_mapping")) return "确认选中项定位"
  return "批量处理"
})

const detailDraft = reactive({})
watch(() => selectedItem.value?.scene, (scene) => {
  Object.assign(detailDraft, {
    title: scene?.title || "",
    narrative_tag: scene?.narrative_tag || "draft",
    status: scene?.status || "draft",
    source: scene?.source || "manual",
    goal: scene?.goal || "",
    core_conflict: scene?.core_conflict || "",
    emotional_beat: scene?.emotional_beat || "",
    must_happen: scene?.must_happen || "",
    must_not_happen: scene?.must_not_happen || "",
    pov_character_id: scene?.pov_character_id || "",
  })
}, { immediate: true })

const railKey = computed(() => `workspace-rail:${props.projectId}:scene-workbench:detail`)
function storedRailOpen() {
  try { return sessionStorage.getItem(railKey.value) !== "closed" } catch { return true }
}
const railOpen = ref(storedRailOpen())
watch(railKey, () => { railOpen.value = storedRailOpen() })
function onRailToggle(event) {
  railOpen.value = event.target.open
  try { sessionStorage.setItem(railKey.value, event.target.open ? "open" : "closed") } catch {}
}

function navigateOutline(subView) { getRouter()?.navigate("outline", subView) }
function createPlannedScene() {
  return showOutlineLayerAiForm("planned_scene", { selectedIds: selectedItem.value?.scene?.id ? [selectedItem.value.scene.id] : [] })
}
function sceneIndex(scene) { return Number.isFinite(Number(scene?.scene_index)) ? Number(scene.scene_index) + 1 : "-" }
function segmentLabel(segment) { return { current: "当前剧情", upcoming: "后续", past: "已写过", unassigned: "未定位" }[segment] || "" }
function firstOverlap(item) { return Array.isArray(item?.overlap_details) ? item.overlap_details[0] : null }
function rowSpanSummary(item) {
  const labels = (item?.span_summaries || []).map(spanSummaryLabel).filter(Boolean)
  if (!labels.length) return ""
  return `${labels.slice(0, 2).join("；")}${labels.length > 2 ? `；另 ${labels.length - 2} 段` : ""}`
}
function rowOverlapSummary(item) {
  const details = item?.overlap_details || []
  if (!details.length) return ""
  const label = details[0].range_label || `与「${overlapCounterpartLabel(details[0])}」的正文范围重叠`
  return `${label}${details.length > 1 ? `；另 ${details.length - 1} 处` : ""}`
}
function menuItems(item) {
  const scene = item.scene
  return [
    { action: "open-writing-scene", label: "打开写作", data: { id: scene.id } },
    { action: "start-merge-scene", label: "合并", data: { id: scene.id } },
    { action: "start-split-scene", label: "拆分", data: { id: scene.id } },
    ...(sceneReviewState(item).reviewed ? [{ action: "mark-scene-unreviewed", label: "标记需检查", data: { id: scene.id } }] : []),
    ...(!structureAssetDisplay(scene).isHistory ? [{ action: "move-scene-to-history", label: "移入历史", data: { id: scene.id } }] : []),
  ]
}
function handleMenu(item, menu) {
  if (menu.action === "open-writing-scene") return openWriting(item.scene)
  if (menu.action === "start-merge-scene") return modalController.startMerge(item.scene.id)
  if (menu.action === "start-split-scene") return modalController.startSplit(item.scene.id)
  if (menu.action === "mark-scene-unreviewed") return vm.reviewScenes([item.scene.id], "reopen")
  if (menu.action === "move-scene-to-history") return vm.moveToHistory(item.scene.id)
}

const SceneDetailPanel = defineComponent({
  props: { item: Object, draft: Object, narrow: Boolean },
  emits: ["close", "context", "save", "merge", "split", "replacement"],
  setup(componentProps, { emit }) {
    return () => {
      const item = componentProps.item
      if (!item?.scene) return h("div", { class: "scene-detail-empty" }, "选择一个场景查看详情。")
      const scene = item.scene
      const review = sceneReviewState(item)
      const reviewLabel = review.reviewed ? `已检查 · ${new Date(review.reviewedAt).toLocaleString("zh-CN")}` : review.needsReview ? "需要人工检查" : "无注意项"
      const action = sceneContextAction(item)
      const field = (label, key, type = "input", options = []) => h("label", { class: ["scene-detail-field", type === "textarea" && "scene-detail-field--wide"] }, [
        h("span", label),
        type === "select"
          ? h("select", { id: `scene-detail-${key}`, class: "form-select", value: componentProps.draft[key], onChange: (event) => { componentProps.draft[key] = event.target.value } }, options.map(([value, text]) => h("option", { value }, text)))
          : type === "textarea"
            ? h("textarea", { id: `scene-detail-${key}`, class: "form-textarea", rows: 3, value: componentProps.draft[key], onInput: (event) => { componentProps.draft[key] = event.target.value } })
            : h("input", { id: `scene-detail-${key}`, class: "form-input", value: componentProps.draft[key], onInput: (event) => { componentProps.draft[key] = event.target.value } }),
      ])
      return h("div", { class: "scene-detail-panel" }, [
        h("div", { class: "scene-detail-panel__head" }, [h("div", [h("div", { class: "scene-detail-panel__eyebrow" }, "场景详情"), h("h3", scene.title || "未命名场景")]), componentProps.narrow ? h("button", { class: "btn btn-sm", "data-action": "close-scene-detail", onClick: () => emit("close") }, "关闭") : null]),
        h("div", { class: "scene-detail-grid" }, [
          field("标题", "title"), field("叙事标签", "narrative_tag", "select", TAG_OPTIONS), field("状态", "status", "select", STATUS_OPTIONS), field("来源", "source", "select", SOURCE_OPTIONS),
          field("目标", "goal", "textarea"), field("核心冲突", "core_conflict", "textarea"), field("情感节奏", "emotional_beat", "textarea"), field("必须发生", "must_happen", "textarea"), field("禁止发生", "must_not_happen", "textarea"), field("视角人物", "pov_character_id"),
        ]),
        h("section", { class: "scene-detail-summary" }, [
          h("div", [h("strong", "章节映射"), h("span", item.chapter_range || "未关联章节")]),
          h("div", [h("strong", "来源与注意"), h("span", `${sceneSourceLabel(scene)} · ${sceneStatusLabel(scene)} · ${reviewLabel}`)]),
          healthReasons(item).length ? h("div", [h("strong", "待处理"), h("span", healthReasons(item).map((reason) => reason.label).join(" · "))]) : null,
          ...(item.span_summaries || []).map((summary) => h("div", { class: "scene-span-detail" }, [h("strong", "正文范围"), h("span", spanSummaryLabel(summary))])),
          ...(item.overlap_details || []).map((detail) => h("div", { class: "scene-overlap-detail" }, [h("strong", detail.range_label || `与「${overlapCounterpartLabel(detail)}」重叠`), h("button", { class: "btn btn-sm", onClick: () => emit("replacement", detail.counterpart_scene_id) }, `查看「${overlapCounterpartLabel(detail)}」`)])),
        ]),
        h("div", { class: "scene-detail-actions" }, [
          action.key !== "edit" ? h("button", { class: "btn btn-sm btn-primary", onClick: () => emit("context") }, action.label) : null,
          h("button", { class: "btn btn-primary", "data-action": "save-scene-detail", onClick: () => emit("save") }, "保存"),
          h("button", { class: "btn", "data-action": "start-merge-scene", onClick: () => emit("merge") }, "合并"),
          h("button", { class: "btn", "data-action": "start-split-scene", onClick: () => emit("split") }, "拆分"),
        ]),
      ])
    }
  },
})
</script>
