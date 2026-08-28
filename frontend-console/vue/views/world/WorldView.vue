<!--
  WorldView — world 视图 Vue 外壳（island 根组件）。
  对应 vanilla worldView 的 _renderHeader（worldView.js:799-820）+ 子标签分派
  （render L713-742）。DOM class/id/data-action 逐节点保留（e2e 契约）；
  事件由 Vue 绑定，不再走 bindWorkspaceClick 委托。
-->
<template>
  <div ref="rootEl" class="world-view">
    <div class="view-header view-header--with-tabs world-toolbar">
      <div class="subnav">
        <button type="button" class="subnav-item" :class="{ active: subView === 'bible' || subView === 'objects' || subView === 'aliases' }" :aria-current="subView === 'bible' || subView === 'objects' || subView === 'aliases' ? 'page' : undefined" data-subview="bible" data-action="nav-bible" @click="navigateSub('bible')">资料库</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'relations' }" :aria-current="subView === 'relations' ? 'page' : undefined" data-subview="relations" data-action="nav-relations" @click="navigateSub('relations')">关系</button>
        <button type="button" class="subnav-item" :class="{ active: !!reviewSubView }" :aria-current="reviewSubView ? 'page' : undefined" :aria-label="reviewTotal ? `需要决定，${reviewTotal} 项` : undefined" data-action="nav-review" @click="navigateReview()">需要决定 <span v-if="reviewTotal" class="today-count" aria-hidden="true">{{ reviewCountLabel }}</span></button>
      </div>
      <div class="view-header__tail">
        <h1 v-if="headerTitle" class="view-header__title">
          {{ headerTitle.text }} <span class="view-header__count">共 {{ headerTitle.count }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span>
        </h1>
        <div class="view-header__actions">
          <button v-if="objectToolsOpen" type="button" class="btn btn-sm btn-ghost" @click="returnToLibrary">← 返回资料库</button>
          <template v-if="subView === 'objects' || objectToolsOpen">
            <button id="btn-new-entity" class="btn btn-sm btn-primary" data-action="new" @click="showEntityCreateForm()">新建人物或设定</button>
            <button class="btn btn-sm" data-action="toggle-extract" @click="toggleExtract">{{ session.autoExtractOpen ? "收起正文整理" : "从正文整理资料" }}</button>
            <details ref="viewOptionsEl" class="world-view-options" @keydown.esc="closeViewOptions">
              <summary class="btn btn-sm">浏览方式</summary>
              <div class="world-view-options__panel">
                <div class="world-view-options__heading">
                  <strong>浏览方式</strong>
                  <button type="button" class="btn btn-sm" data-action="close-view-options" @click="closeViewOptions">完成</button>
                </div>
                <div class="world-view-options__group">
                  <span class="world-view-options__label">显示方式</span>
                  <span class="world-object-view-toggle" role="group" aria-label="人物与设定显示方式">
                    <button class="btn btn-sm" :aria-pressed="localObjectViewMode === 'card'" data-action="set-object-view" data-view-mode="card" @click="setObjectViewMode('card')">卡片</button>
                    <button class="btn btn-sm" :aria-pressed="localObjectViewMode === 'table'" data-action="set-object-view" data-view-mode="table" @click="setObjectViewMode('table')">表格</button>
                  </span>
                </div>
                <div class="world-view-options__group">
                  <span class="world-view-options__label">资料范围</span>
                  <span class="world-discovery-mode-toggle" role="group" aria-label="资料范围">
                    <button class="btn btn-sm" :aria-pressed="discoveryMode === 'hot'" data-action="set-discovery-mode" data-mode="hot" @click="setDiscoveryMode('hot')">最近相关</button>
                    <button class="btn btn-sm" :aria-pressed="discoveryMode === 'normal'" data-action="set-discovery-mode" data-mode="normal" @click="setDiscoveryMode('normal')">全部资料</button>
                  </span>
                </div>
              </div>
            </details>
          </template>
          <button v-if="subView === 'aliases'" class="btn btn-sm btn-primary" data-action="create-alias" @click="showAliasCreateForm(reviewTypeCatalog)">新建别名</button>
        </div>
      </div>
    </div>
    <WorldSidebarToolCard v-if="sidebarToolActions.length" :actions="sidebarToolActions" :show-smart-dedup="subView === 'relations'" @select="handleSidebarTool" />
    <component
      :is="activeTab"
      v-if="activeTab"
      v-bind="$props"
      :object-view-mode="localObjectViewMode"
      :default-display-mode="subView === 'bible' ? 'gallery' : undefined"
    />
    <OwnerAiDrawer
      v-if="aiDrawerMounted"
      :open="aiDrawerOpen"
      owner="world"
      :initial-mode="props.bibleDeepLink?.ownerAiMode || null"
      :project-id="props.projectId"
      :source-page-id="props.bibleDeepLink?.pageId || props.bibleDeepLink?.ownerAiSourcePageId || null"
      :target-kind="props.bibleDeepLink?.ownerAiTarget || null"
      :preset="props.bibleDeepLink?.ownerAiPreset || null"
      :checkpoint-id="props.bibleDeepLink?.ownerAiCheckpointId || null"
      @close="aiDrawerOpen = false"
    />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue"
import { getAppState, getRouter } from "../../bridge/index.js"
import { worldSession as session } from "./worldSession.js"
import { objectQueryFromState } from "./logic/worldQuery.js"
import { clearBulkSelection } from "./logic/worldBulkSelection.js"
import { showEntityCreateForm } from "./logic/worldEntityOps.js"
import { showAliasCreateForm, showRelationCreateForm } from "./logic/worldRelationsAliasesOps.js"
import WorldObjectsTab from "./components/WorldObjectsTab.vue"
import WorldRelationsTab from "./components/WorldRelationsTab.vue"
import WorldAliasesTab from "./components/WorldAliasesTab.vue"
import WorldSidebarToolCard from "./components/WorldSidebarToolCard.vue"

const lazyView = (loader) => defineAsyncComponent({
  loader,
  onError(_error, retry, fail, attempts) {
    if (attempts < 2) retry()
    else fail()
  },
})
const WorldReviewTab = lazyView(() => import("./components/WorldReviewTab.vue"))
const WorldBibleTab = lazyView(() => import("./bible/WorldBibleTab.vue"))
const OwnerAiDrawer = lazyView(() => import("../../components/OwnerAiDrawer.vue"))

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "bible" },
  reviewSubView: { type: String, default: "" },
  reviewKind: { type: String, default: "all" },
  entityTypes: { type: Array, default: () => [] },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
  reviewCounts: { type: Object, default: () => ({ objects: 0, aliases: 0, relations: 0 }) },
  objectFilters: { type: Object, default: () => ({}) },
  objectViewMode: { type: String, default: "table" },
  discoveryMode: { type: String, default: "hot" },
  entities: { type: Array, default: () => [] },
  entitiesTotal: { type: Number, default: 0 },
  entitiesLoadError: { type: String, default: null },
  rankingFacets: { type: Object, default: null },
  rankingContext: { type: Object, default: null },
  batches: { type: Array, default: () => [] },
  candidateFilters: { type: Object, default: () => ({}) },
  candidates: { type: Array, default: () => [] },
  candidateTotal: { type: Number, default: 0 },
  candidateLoadError: { type: String, default: null },
  aliasReviewFilters: { type: Object, default: () => ({}) },
  aliasGroups: { type: Array, default: () => [] },
  aliasGroupTotal: { type: Number, default: 0 },
  aliasItemTotal: { type: Number, default: 0 },
  aliasReviewLoadError: { type: String, default: null },
  relationReviewFilters: { type: Object, default: () => ({}) },
  relationGroups: { type: Array, default: () => [] },
  relationGroupTotal: { type: Number, default: 0 },
  relationItemTotal: { type: Number, default: 0 },
  relationReviewLoadError: { type: String, default: null },
  relations: { type: Array, default: () => [] },
  relationsTotal: { type: Number, default: 0 },
  relationsLoadError: { type: String, default: null },
  aliases: { type: Array, default: () => [] },
  aliasesTotal: { type: Number, default: 0 },
  aliasesLoadError: { type: String, default: null },
  bible: { type: Object, default: null },
  worldCardFilters: { type: Object, default: () => ({ q: "", kind: "all", type: "", state: "", layout: "cards" }) },
  bibleDeepLink: { type: Object, default: () => ({ draftId: "", pageId: "" }) },
  knowledgeCharacterId: { type: String, default: "" },
})

const rootEl = ref(null)
const viewOptionsEl = ref(null)
const aiDrawerOpen = ref(Boolean(props.bibleDeepLink?.ownerAiOpen))
const aiDrawerMounted = ref(aiDrawerOpen.value)
function openOwnerAi() {
  aiDrawerMounted.value = true
  aiDrawerOpen.value = true
}
watch(() => props.bibleDeepLink?.ownerAiOpen, (open) => {
  if (!open) return
  aiDrawerMounted.value = true
  aiDrawerOpen.value = true
})
const localObjectViewMode = ref(props.objectViewMode === "card" ? "card" : "table")
watch(() => props.objectViewMode, (mode) => { localObjectViewMode.value = mode === "card" ? "card" : "table" })

const TAB_COMPONENTS = {
  objects: WorldObjectsTab,
  review: WorldReviewTab,
  "review-objects": WorldReviewTab,
  "review-aliases": WorldReviewTab,
  "review-relations": WorldReviewTab,
  relations: WorldRelationsTab,
  aliases: WorldAliasesTab,
  bible: WorldBibleTab,
}

const objectToolsOpen = computed(() => (
  props.subView === "bible" && props.bibleDeepLink?.openObjectTools
))
const activeTab = computed(() => (
  objectToolsOpen.value
    ? WorldObjectsTab
    : TAB_COMPONENTS[props.reviewSubView || props.subView] || null
))

const reviewTotal = computed(() => (
  Object.values(props.reviewCounts || {}).reduce((sum, value) => sum + Number(value || 0), 0)
))
const reviewCountLabel = computed(() => reviewTotal.value > 99 ? "99+" : String(reviewTotal.value))
const nextReviewKind = computed(() => ["objects", "aliases", "relations"].find((kind) => Number(props.reviewCounts?.[kind] || 0)) || "all")
const sidebarToolActions = computed(() => {
  if (props.subView === "relations") return [
    { key: "new-relation", label: "新建关系", primary: true },
    { key: "review-relations", label: "待决定关系", badge: props.reviewCounts?.relations || 0 },
    { key: "ai", label: "AI 工具" },
    { key: "library", label: "返回资料库" },
    { key: "more", label: "更多工具" },
  ]
  if (props.reviewSubView) return [
    { key: "start-review", label: "开始处理", primary: true, disabled: !reviewTotal.value },
    { key: "review-objects", label: "对象", badge: props.reviewCounts?.objects || 0 },
    { key: "review-aliases", label: "别名", badge: props.reviewCounts?.aliases || 0 },
    { key: "review-relations", label: "关系", badge: props.reviewCounts?.relations || 0 },
    { key: "library", label: "返回资料库" },
  ]
  return []
})

function handleSidebarTool(key) {
  if (key === "new-relation") { showRelationCreateForm(props.reviewTypeCatalog); return }
  if (key === "start-review") { navigateReview(nextReviewKind.value); return }
  if (key.startsWith("review-")) { navigateReview(key.slice(7)); return }
  if (key === "ai") { openOwnerAi(); return }
  if (key === "library") { navigateSub("bible"); return }
  if (key === "more") getRouter()?.navigate("world", "bible", true, new URLSearchParams({ open: "object-tools" }))
}

/** 对应 vanilla _renderHeaderTitle（worldView.js:756-779）。 */
const headerTitle = computed(() => {
  if (props.subView === "objects" || objectToolsOpen.value) return { text: "人物与设定工具", count: props.entitiesTotal }
  if (props.reviewSubView) return { text: "需要决定", count: reviewTotal.value }
  if (props.subView === "relations") return { text: "关系", count: props.relationsTotal }
  if (props.subView === "aliases") return { text: "别名", count: props.aliasesTotal }
  return null
})

const projectTitle = computed(() => {
  const project = getAppState()?.currentProject
  return project?.title || project?.name || ""
})

function navigateSub(sub) {
  getRouter()?.navigate("world", sub)
}

function returnToLibrary() {
  try {
    localStorage.setItem(`worldBible:${props.projectId}:displayMode`, "gallery")
  } catch {
    // 偏好不可写时仍可返回 canonical 资料库路由。
  }
  navigateSub("bible")
}

function navigateReview(kind = "all") {
  const query = new URLSearchParams()
  if (kind !== "all") query.set("kind", kind)
  getRouter()?.navigate("world", "review", true, query)
}

function navigateObjectsQuery(nextFilters, viewMode = localObjectViewMode.value, mode = props.discoveryMode) {
  const query = objectQueryFromState(nextFilters, viewMode, mode)
  if (objectToolsOpen.value) {
    query.set("kind", "entity")
    query.set("open", "object-tools")
  }
  if (session.objectFilterDraft) session.objectFilterDraft.routeSignature = query.toString()
  getRouter()?.navigate("world", "objects", true, query)
}

/** 对应 vanilla _setObjectViewMode（worldView.js:1293 区域）。 */
function setObjectViewMode(mode) {
  const next = mode === "card" ? "card" : "table"
  if (next === localObjectViewMode.value) return
  localObjectViewMode.value = next
  const query = objectQueryFromState(props.objectFilters, next, props.discoveryMode)
  if (objectToolsOpen.value) {
    query.set("kind", "entity")
    query.set("open", "object-tools")
  }
  if (session.objectFilterDraft) session.objectFilterDraft.routeSignature = query.toString()
  if (getRouter()?.commitCurrentQuery?.(query) !== true) navigateObjectsQuery(props.objectFilters, next)
}

/** 对应 vanilla _setDiscoveryMode（worldView.js:1293 区域）：记偏好、清批量、复位 focus/skip。 */
function setDiscoveryMode(mode) {
  if (mode !== "normal" && mode !== "hot") return
  if (mode === props.discoveryMode) return
  try {
    localStorage.setItem(`novel_view_mode:${props.projectId || "none"}:world-objects`, mode)
  } catch {
    // 偏好写入失败不阻断列表使用。
  }
  clearBulkSelection("world-objects")
  navigateObjectsQuery({ ...props.objectFilters, focus: "", skip: 0 }, localObjectViewMode.value, mode)
}

/** 对应 vanilla _toggleAutoExtract（worldView.js:842-845）；响应式重绘取代 router.refresh。 */
function toggleExtract() {
  session.autoExtractOpen = !session.autoExtractOpen
}

function closeViewOptions() {
  viewOptionsEl.value?.removeAttribute("open")
}

onMounted(() => {
  // app.js 监听该事件填充 [data-role="smart-dedup-action"]（worldView.js:660,672 同款契约）
  rootEl.value?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
})
</script>

<style scoped>
@media (max-width: 760px) {
  .world-toolbar .subnav-item { min-height: 44px; }
}
</style>
