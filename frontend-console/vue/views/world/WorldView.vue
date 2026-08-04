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
        <button type="button" class="subnav-item" :class="{ active: subView === 'objects' }" :aria-current="subView === 'objects' ? 'page' : undefined" data-subview="objects" data-action="nav-objects" @click="navigateSub('objects')">对象库</button>
        <button type="button" class="subnav-item" :class="{ active: !!reviewSubView }" :aria-current="reviewSubView ? 'page' : undefined" data-subview="review-objects" data-action="nav-review" @click="navigateSub('review-objects')">待处理 ({{ reviewTotal }})</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'relations' }" :aria-current="subView === 'relations' ? 'page' : undefined" data-subview="relations" data-action="nav-relations" @click="navigateSub('relations')">关系</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'aliases' }" :aria-current="subView === 'aliases' ? 'page' : undefined" data-subview="aliases" data-action="nav-aliases" @click="navigateSub('aliases')">别名</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'bible' }" :aria-current="subView === 'bible' ? 'page' : undefined" data-subview="bible" data-action="nav-bible" @click="navigateSub('bible')">世界书</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'map' }" :aria-current="subView === 'map' ? 'page' : undefined" data-subview="map" data-action="nav-map" @click="navigateMap">地图</button>
      </div>
      <div class="view-header__tail">
        <span v-if="headerTitle" class="view-header__title">
          {{ headerTitle.text }} <span class="view-header__count">共 {{ headerTitle.count }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span>
        </span>
        <div class="view-header__actions">
          <template v-if="subView === 'objects'">
            <span class="world-discovery-mode-toggle" aria-label="对象检索模式">
              <button class="btn btn-sm" :class="{ 'btn-primary': discoveryMode === 'normal' }" data-action="set-discovery-mode" data-mode="normal" @click="setDiscoveryMode('normal')">普通</button>
              <button class="btn btn-sm" :class="{ 'btn-primary': discoveryMode === 'hot' }" data-action="set-discovery-mode" data-mode="hot" @click="setDiscoveryMode('hot')">热点</button>
            </span>
            <button id="btn-new-entity" class="btn btn-sm btn-primary" data-action="new" @click="showEntityCreateForm()">新建对象</button>
            <button class="btn btn-sm" data-action="toggle-extract" @click="toggleExtract">{{ session.autoExtractOpen ? "▾" : "▸" }} 自动提取</button>
            <span class="world-object-view-toggle" aria-label="对象库视图">
              <button class="btn btn-sm" :class="{ 'btn-primary': objectViewMode === 'table' }" data-action="set-object-view" data-view-mode="table" @click="setObjectViewMode('table')">表格</button>
              <button class="btn btn-sm" :class="{ 'btn-primary': objectViewMode === 'card' }" data-action="set-object-view" data-view-mode="card" @click="setObjectViewMode('card')">卡片</button>
            </span>
          </template>
          <button v-if="subView === 'relations'" class="btn btn-sm btn-primary" data-action="create-relation" @click="showRelationCreateForm()">新建关系</button>
          <button v-if="subView === 'aliases'" class="btn btn-sm btn-primary" data-action="create-alias" @click="showAliasCreateForm()">新建别名</button>
          <span data-role="smart-dedup-action"></span>
        </div>
      </div>
    </div>
    <component :is="activeTab" v-bind="$props" v-if="activeTab" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { getAppState, getRouter } from "../../bridge/index.js"
import { buildMapQuery } from "../../../views/mapRouteContext.js"
import { worldSession as session } from "./worldSession.js"
import { objectQueryFromState } from "./logic/worldQuery.js"
import { clearBulkSelection } from "./logic/worldBulkSelection.js"
import { showEntityCreateForm } from "./logic/worldEntityOps.js"
import { showAliasCreateForm, showRelationCreateForm } from "./logic/worldRelationsAliasesOps.js"
import WorldObjectsTab from "./components/WorldObjectsTab.vue"
import WorldReviewTab from "./components/WorldReviewTab.vue"
import WorldRelationsTab from "./components/WorldRelationsTab.vue"
import WorldAliasesTab from "./components/WorldAliasesTab.vue"
import WorldBibleTab from "./bible/WorldBibleTab.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "objects" },
  reviewSubView: { type: String, default: "" },
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
  bibleDeepLink: { type: Object, default: () => ({ draftId: "", pageId: "" }) },
})

const rootEl = ref(null)

const TAB_COMPONENTS = {
  objects: WorldObjectsTab,
  "review-objects": WorldReviewTab,
  "review-aliases": WorldReviewTab,
  "review-relations": WorldReviewTab,
  relations: WorldRelationsTab,
  aliases: WorldAliasesTab,
  bible: WorldBibleTab,
}

const activeTab = computed(() => TAB_COMPONENTS[props.reviewSubView || props.subView] || null)

const reviewTotal = computed(() => (
  Object.values(props.reviewCounts || {}).reduce((sum, value) => sum + Number(value || 0), 0)
))

/** 对应 vanilla _renderHeaderTitle（worldView.js:756-779）。 */
const headerTitle = computed(() => {
  if (props.subView === "objects") return { text: "世界对象", count: props.entitiesTotal }
  if (props.reviewSubView === "review-objects") return { text: "待处理对象", count: props.candidateTotal }
  if (props.reviewSubView === "review-aliases") return { text: "待处理别名", count: props.aliasItemTotal }
  if (props.reviewSubView === "review-relations") return { text: "待处理关系", count: props.relationItemTotal }
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

/** 对应 vanilla nav-map（worldView.js:3875-3878）。 */
function navigateMap() {
  getRouter()?.navigate("map", null, true, buildMapQuery({
    projectId: props.projectId,
    mode: "overview",
  }))
}

function navigateObjectsQuery(nextFilters, viewMode = props.objectViewMode, mode = props.discoveryMode) {
  getRouter()?.navigate("world", "objects", true, objectQueryFromState(nextFilters, viewMode, mode))
}

/** 对应 vanilla _setObjectViewMode（worldView.js:1293 区域）。 */
function setObjectViewMode(mode) {
  navigateObjectsQuery(props.objectFilters, mode === "card" ? "card" : "table")
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
  navigateObjectsQuery({ ...props.objectFilters, focus: "", skip: 0 }, props.objectViewMode, mode)
}

/** 对应 vanilla _toggleAutoExtract（worldView.js:842-845）；响应式重绘取代 router.refresh。 */
function toggleExtract() {
  session.autoExtractOpen = !session.autoExtractOpen
}

onMounted(() => {
  // app.js 监听该事件填充 [data-role="smart-dedup-action"]（worldView.js:660,672 同款契约）
  rootEl.value?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
})
</script>
