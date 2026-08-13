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
        <button type="button" class="subnav-item" :class="{ active: subView === 'objects' || subView === 'aliases' }" :aria-current="subView === 'objects' ? 'page' : undefined" data-subview="objects" data-action="nav-objects" @click="navigateSub('objects')">人物与设定</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'relations' }" :aria-current="subView === 'relations' ? 'page' : undefined" data-subview="relations" data-action="nav-relations" @click="navigateSub('relations')">关系</button>
        <button type="button" class="subnav-item" :class="{ active: subView === 'bible' }" :aria-current="subView === 'bible' ? 'page' : undefined" data-subview="bible" data-action="nav-bible" @click="navigateSub('bible')">世界笔记</button>
        <button type="button" class="subnav-item" :class="{ active: !!reviewSubView }" :aria-current="reviewSubView ? 'page' : undefined" data-action="nav-review" @click="navigateSub('review-objects')">需要决定 <span class="badge">{{ reviewTotal }}</span></button>
      </div>
      <div class="view-header__tail">
        <span v-if="headerTitle" class="view-header__title">
          {{ headerTitle.text }} <span class="view-header__count">共 {{ headerTitle.count }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span>
        </span>
        <div class="view-header__actions">
          <template v-if="subView === 'objects'">
            <button id="btn-new-entity" class="btn btn-sm btn-primary" data-action="new" @click="showEntityCreateForm()">新建人物或设定</button>
            <details class="world-view-options">
              <summary class="btn btn-sm">视图与整理</summary>
              <div class="world-view-options__panel">
                <button class="btn btn-sm" data-action="toggle-extract" @click="toggleExtract">{{ session.autoExtractOpen ? "收起" : "打开" }} AI 资料整理</button>
                <span class="world-object-view-toggle" role="group" aria-label="人物与设定视图">
                  <button class="btn btn-sm" :class="{ 'btn-primary': localObjectViewMode === 'card' }" data-action="set-object-view" data-view-mode="card" @click="setObjectViewMode('card')">卡片</button>
                  <button class="btn btn-sm" :class="{ 'btn-primary': localObjectViewMode === 'table' }" data-action="set-object-view" data-view-mode="table" @click="setObjectViewMode('table')">表格</button>
                </span>
                <span class="world-discovery-mode-toggle" role="group" aria-label="资料排序">
                  <button class="btn btn-sm" :class="{ 'btn-primary': discoveryMode === 'hot' }" data-action="set-discovery-mode" data-mode="hot" @click="setDiscoveryMode('hot')">最近相关</button>
                  <button class="btn btn-sm" :class="{ 'btn-primary': discoveryMode === 'normal' }" data-action="set-discovery-mode" data-mode="normal" @click="setDiscoveryMode('normal')">全部资料</button>
                </span>
              </div>
            </details>
          </template>
          <button v-if="subView === 'relations'" class="btn btn-sm btn-primary" data-action="create-relation" @click="showRelationCreateForm()">新建关系</button>
          <button v-if="subView === 'aliases'" class="btn btn-sm btn-primary" data-action="create-alias" @click="showAliasCreateForm()">新建别名</button>
          <span data-role="smart-dedup-action"></span>
        </div>
      </div>
    </div>
    <component :is="activeTab" v-bind="$props" :object-view-mode="localObjectViewMode" v-if="activeTab" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { getAppState, getRouter } from "../../bridge/index.js"
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
  knowledgeCharacterId: { type: String, default: "" },
})

const rootEl = ref(null)
const localObjectViewMode = ref(props.objectViewMode === "card" ? "card" : "table")
watch(() => props.objectViewMode, (mode) => { localObjectViewMode.value = mode === "card" ? "card" : "table" })

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
  if (props.subView === "objects") return { text: "人物与设定", count: props.entitiesTotal }
  if (props.reviewSubView === "review-objects") return { text: "待决定的人物与设定", count: props.candidateTotal }
  if (props.reviewSubView === "review-aliases") return { text: "待决定别名", count: props.aliasItemTotal }
  if (props.reviewSubView === "review-relations") return { text: "待决定关系", count: props.relationItemTotal }
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

function navigateObjectsQuery(nextFilters, viewMode = localObjectViewMode.value, mode = props.discoveryMode) {
  const query = objectQueryFromState(nextFilters, viewMode, mode)
  if (session.objectFilterDraft) session.objectFilterDraft.routeSignature = query.toString()
  getRouter()?.navigate("world", "objects", true, query)
}

/** 对应 vanilla _setObjectViewMode（worldView.js:1293 区域）。 */
function setObjectViewMode(mode) {
  const next = mode === "card" ? "card" : "table"
  if (next === localObjectViewMode.value) return
  localObjectViewMode.value = next
  const query = objectQueryFromState(props.objectFilters, next, props.discoveryMode)
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

onMounted(() => {
  // app.js 监听该事件填充 [data-role="smart-dedup-action"]（worldView.js:660,672 同款契约）
  rootEl.value?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
})
</script>
