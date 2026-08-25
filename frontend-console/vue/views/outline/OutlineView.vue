<!--
  OutlineView — outline 视图 Vue 外壳（island 根组件，直接拥有
  story-outline/threads/arcs/scenes 四个子标签）。
  组件根负责子标签分派、进度/结果区与场景工作台的所有权切换。
-->
<template>
  <template v-if="subView === 'scenes'">
    <OutlineHeader v-if="outlineGenerateReview" :sub-view="subView" :review-mode="true" />
    <SceneWorkbenchView
      v-else
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
  </template>
  <template v-else>
    <OutlineHeader :sub-view="subView" :structure-totals="structureTotals" :review-mode="outlineGenerateReview" />
  </template>
  <template v-if="subView === 'threads' || subView === 'arcs'">
    <section v-if="hasAnyProgress && !outlineGenerateReview" class="outline-task-status" aria-labelledby="outline-active-tasks-title">
      <h3 id="outline-active-tasks-title" class="outline-task-status__title">AI 任务</h3>
      <OutlineAnalysisProgressCard />
      <OutlineGenerateProgressCard />
      <PlotAutoExtractProgressCard />
    </section>
    <OutlineAnalysisResultCard v-if="!outlineGenerateReview" />
  </template>
  <OutlineScenePreviewPage
    v-if="subView === 'scenes' && outlineGenerateReview"
    :project-id="projectId"
  />
  <OutlineStoryEditorPage
    v-else-if="subView === 'story-outline' && editorMode"
    :project-id="projectId"
    :current="current"
    :load-error="loadError"
  />
  <OutlineStoryTab
    v-else-if="subView === 'story-outline'"
    :project-id="projectId"
    :current="current"
    :history="history"
    :history-total="historyTotal"
    :characters="characters"
    :entities="entities"
    :load-error="loadError"
    :asset-load-error="assetLoadError"
  />
  <OutlineThreadPreviewPage
    v-else-if="subView === 'threads' && outlineGenerateReview"
    :project-id="projectId"
  />
  <OutlineArcPreviewPage
    v-else-if="subView === 'arcs' && outlineGenerateReview"
    :project-id="projectId"
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
    :information-focus="informationFocus"
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
import OutlineArcPreviewPage from "./ai/OutlineArcPreviewPage.vue"
import OutlineScenePreviewPage from "./ai/OutlineScenePreviewPage.vue"
import OutlineThreadPreviewPage from "./ai/OutlineThreadPreviewPage.vue"
import PlotAutoExtractProgressCard from "./ai/PlotAutoExtractProgressCard.vue"
import OutlineAnalysisResultCard from "./ai/OutlineAnalysisResultCard.vue"
import OutlineStoryEditorPage from "./story/OutlineStoryEditorPage.vue"
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
  editorMode: { type: Boolean, default: false },
  structureFilters: { type: Object, default: () => ({}) },
  outlineGenerateReview: { type: Boolean, default: false },
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
  informationFocus: { type: String, default: null },
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
