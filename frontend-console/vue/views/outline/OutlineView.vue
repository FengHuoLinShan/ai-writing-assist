<!--
  OutlineView — outline 视图 Vue 外壳（island 根组件，直接拥有
  story-outline/threads/arcs/scenes 四个子标签）。
  组件根负责子标签分派、进度/结果区与场景工作台的所有权切换。
-->
<template>
  <SceneWorkbenchView
    v-if="subView === 'scenes'"
    :project-id="projectId"
    :workbench="workbench"
    :fusion-suggestions="fusionSuggestions"
    :view-mode="viewMode"
    :selected-scene-id="selectedSceneId"
    :focused-suggestion-id="focusedSuggestionId"
    :scene-filters="sceneFilters"
    :active-health="activeHealth"
    :advanced-filters-open="advancedFiltersOpen"
    :scene-load-error="sceneLoadError"
  />
  <template v-else>
    <OutlineHeader :sub-view="subView" :structure-totals="structureTotals" />
  </template>
  <template v-if="subView === 'threads' || subView === 'arcs'">
    <div v-if="hasAnyProgress" class="outline-toolbar-status">
      <OutlineAnalysisProgressCard />
      <OutlineGenerateProgressCard />
      <PlotAutoExtractProgressCard />
    </div>
    <OutlineAnalysisResultCard />
  </template>
  <OutlineStoryTab
    v-if="subView === 'story-outline'"
    :project-id="projectId"
    :current="current"
    :history="history"
    :history-total="historyTotal"
    :characters="characters"
    :entities="entities"
    :load-error="loadError"
    :asset-load-error="assetLoadError"
  />
  <OutlineThreadsTab
    v-else-if="subView === 'threads'"
    :project-id="projectId"
    :sub-view="subView"
    :threads="threads"
    :threads-total="structureTotals.threads"
    :threads-load-error="structureLoadErrors.threads || structureLoadErrors.foreshadowing || structureLoadErrors.reveals || null"
    :foreshadowing="foreshadowing"
    :reveals="reveals"
    :unassigned-foreshadowing="unassignedForeshadowing"
    :unassigned-reveals="unassignedReveals"
    :filters="structureFilters"
  />
  <OutlineArcsTab
    v-else-if="subView === 'arcs'"
    :project-id="projectId"
    :sub-view="subView"
    :arcs="arcs"
    :arcs-total="structureTotals.arcs"
    :arcs-load-error="structureLoadErrors.arcs || null"
    :filters="structureFilters"
  />
</template>

<script setup>
import { computed, onMounted } from "vue"
import OutlineHeader from "./components/OutlineHeader.vue"
import OutlineAnalysisProgressCard from "./ai/OutlineAnalysisProgressCard.vue"
import OutlineGenerateProgressCard from "./ai/OutlineGenerateProgressCard.vue"
import PlotAutoExtractProgressCard from "./ai/PlotAutoExtractProgressCard.vue"
import OutlineAnalysisResultCard from "./ai/OutlineAnalysisResultCard.vue"
import OutlineStoryTab from "./story/OutlineStoryTab.vue"
import OutlineThreadsTab from "./components/OutlineThreadsTab.vue"
import OutlineArcsTab from "./components/OutlineArcsTab.vue"
import SceneWorkbenchView from "../scene/SceneWorkbenchView.vue"
import {
  outlineAnalysisManager,
  outlineGenerateManager,
  plotAutoExtractManager,
} from "./ai/outlineWorkflowManagers.js"

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "story-outline" },
  structureFilters: { type: Object, default: () => ({}) },
  // story-outline 分支（storyOutlineData.loadStoryOutlineProps）
  current: { type: Object, default: null },
  history: { type: Array, default: () => [] },
  historyTotal: { type: Number, default: 0 },
  characters: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
  loadError: { type: String, default: null },
  assetLoadError: { type: String, default: null },
  // 结构分支（logic/outlineStructure.loadStructureProps）
  threads: { type: Array, default: () => [] },
  arcs: { type: Array, default: () => [] },
  foreshadowing: { type: Array, default: () => [] },
  reveals: { type: Array, default: () => [] },
  unassignedForeshadowing: { type: Array, default: () => [] },
  unassignedReveals: { type: Array, default: () => [] },
  structureTotals: { type: Object, default: () => ({ threads: 0, arcs: 0, foreshadowing: 0, reveals: 0 }) },
  structureLoadErrors: { type: Object, default: () => ({}) },
  // scenes 分支（sceneModel.loadSceneWorkbenchProps）
  workbench: { type: Object, default: null },
  fusionSuggestions: { type: Array, default: () => [] },
  viewMode: { type: String, default: "hot" },
  selectedSceneId: { type: String, default: null },
  focusedSuggestionId: { type: String, default: null },
  sceneFilters: { type: Object, default: () => ({}) },
  activeHealth: { type: String, default: null },
  advancedFiltersOpen: { type: Boolean, default: false },
  sceneLoadError: { type: String, default: null },
})

const hasAnyProgress = computed(() => Boolean(
  outlineAnalysisManager.state.progress
  || outlineGenerateManager.state.progress
  || plotAutoExtractManager.state.progress
))

onMounted(() => {
  // app.js 监听该事件填充 [data-role="smart-dedup-action"]（同 WorldView 契约）
  document.querySelector(".outline-toolbar")?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
})
</script>
