<!--
  OutlineHeader — outline 四个子视图的共享头部（vanilla _renderOutlineHeader
  L366-395 + _renderOutlineHeaderTitle L333-339 + _renderOutlineHeaderActions
  L340-365）。稳定 class/data-action 保留（e2e/视觉基线契约）。
-->
<template>
  <WorkspaceToolCard v-if="subView === 'threads' || subView === 'arcs' || reviewMode" title="故事工具"
    :context="subViewLabel" :actions="toolActions" :more-actions="moreTools" action-prefix="outline-tool" @select="runTool">
    <template v-if="!reviewMode" #more><SmartDedupAction /></template>
  </WorkspaceToolCard>
  <div ref="headerEl" class="view-header view-header--with-tabs outline-toolbar">
    <div class="subnav">
      <button type="button" class="subnav-item" :class="{ active: subView === 'story-outline' }" :aria-current="subView === 'story-outline' ? 'page' : undefined" data-action="nav-story-outline" @click="navigateSub('story-outline')">故事总览</button>
      <button type="button" class="subnav-item" :class="{ active: subView === 'arcs' }" :aria-current="subView === 'arcs' ? 'page' : undefined" data-action="nav-arcs" @click="navigateSub('arcs')">篇章</button>
      <button type="button" class="subnav-item" :class="{ active: subView === 'threads' }" :aria-current="subView === 'threads' ? 'page' : undefined" data-action="nav-threads" @click="navigateSub('threads')">剧情线</button>
      <button type="button" class="subnav-item" :class="{ active: subView === 'scenes' }" :aria-current="subView === 'scenes' ? 'page' : undefined" data-action="nav-scenes" @click="navigateSub('scenes')">场景</button>
    </div>
    <div class="view-header__tail">
      <span class="view-header__title">
        <template v-if="subView === 'story-outline'">故事总览<span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="reviewMode && (subView === 'threads' || subView === 'arcs' || subView === 'scenes')">{{ subViewLabel }}<span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="subView === 'threads'">剧情线 <span class="view-header__count">共 {{ structureTotals.threads }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="subView === 'arcs'">篇章 <span class="view-header__count">共 {{ structureTotals.arcs }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="subView === 'scenes'">场景 <span v-if="itemCount != null" class="view-header__count">共 {{ itemCount }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
      </span>
      <div
        class="view-header__actions"
        :class="{
          'scene-workbench-actions': subView === 'scenes',
          'outline-structure-actions': subView === 'threads' || subView === 'arcs',
        }"
        :aria-label="subView === 'scenes' ? '场景操作' : subView === 'threads' ? '剧情线操作' : subView === 'arcs' ? '篇章操作' : undefined"
      >
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"
import { getAppState, getRouteQuery, getRouter } from "../../../bridge/index.js"
import { showCreateArcForm, showCreateThreadForm } from "../logic/outlineStructureOps.js"
import {
  showOutlineGeneratePreview,
  showOutlineAnalysisForm,
  showOutlineLayerAiForm,
  showPlotStructureAutoExtractForm,
} from "../ai/outlineAiOps.js"
import { outlineAnalysisManager, outlineGenerateManager, plotAutoExtractManager } from "../ai/outlineWorkflowManagers.js"

import WorkspaceToolCard from "../../../components/WorkspaceToolCard.vue"
import SmartDedupAction from "../../../components/SmartDedupAction.vue"
import { focusWorkspaceTool } from "../../../components/workspaceTools.js"
import { getBulkSelection } from "../logic/outlineBulkSelection.js"
const headerEl = ref(null)
const props = defineProps({
  subView: { type: String, default: "story-outline" },
  itemCount: { type: Number, default: null },
  structureTotals: { type: Object, default: () => ({ threads: 0, arcs: 0, foreshadowing: 0, reveals: 0 }) },
  reviewMode: { type: Boolean, default: false },
})

const projectTitle = computed(() => {
  const project = getAppState()?.currentProject
  return project?.title || project?.name || ""
})
const subViewLabel = computed(() => ({ threads: "剧情线", arcs: "篇章", scenes: "场景" })[props.subView] || "故事结构")

/** vanilla _renderOutlineHeaderActions 的 analysisBusy（提交中或任务未终态）。 */
const analysisBusy = computed(() => {
  const progress = outlineAnalysisManager.state.progress
  return Boolean(outlineAnalysisManager.state.submitting || (progress && !progress.terminal))
})

const plotExtractBusy = computed(() => {
  const progress = plotAutoExtractManager.state.progress
  return Boolean(plotAutoExtractManager.state.submitting || (progress && !progress.terminal))
})

function navigateSub(sub) {
  getRouter()?.navigate("outline", sub)
}

function closeReview() {
  const router = getRouter()
  const query = getRouteQuery()
  query.delete("review")
  router?.replace?.("outline", props.subView, query)
}


const target = computed(() => props.subView === "threads" ? "plot_thread" : "outline_arc")
const selectedIds = computed(() => [...getBulkSelection(props.subView === "threads" ? "outline-threads" : "outline-arcs")])
const generationBusy = computed(() => outlineGenerateManager.state.submitting || (outlineGenerateManager.state.progress && !outlineGenerateManager.state.progress.terminal))
const moreTools = computed(() => props.reviewMode ? [] : props.subView === "threads"
  ? [{ key: "analyze", label: "检查故事结构", dataAction: "analyze-outline", disabled: analysisBusy.value }]
  : [])
const toolActions = computed(() => {
  if (props.reviewMode) return [
    { key: "review-current", label: "继续核对建议", primary: true },
    { key: "return", label: "返回" + subViewLabel.value, dataAction: "close-outline-generate-preview" },
  ]
  const thread = props.subView === "threads"
  const base = [
    { key: "create", label: thread ? "新建剧情线" : "新建篇章", dataAction: thread ? "create-thread" : "create-arc" },
    { key: "ai", label: selectedIds.value.length ? "AI 修订所选" : thread ? "AI 创作剧情线" : "AI 规划篇章", badge: selectedIds.value.length, dataAction: thread ? "ai-create-plot-thread" : "ai-create-outline-arc", disabled: Boolean(generationBusy.value) },
    { key: "extract", label: thread ? "从正文整理剧情线" : "从正文整理篇章", dataAction: "plot-structure-auto-extract", disabled: plotExtractBusy.value },
    thread ? { key: "information", label: "查看伏笔与揭示" } : { key: "analyze", label: "检查故事结构", dataAction: "analyze-outline", disabled: analysisBusy.value },
  ]
  let primary = base[selectedIds.value.length ? 1 : 0]
  if (generationBusy.value || analysisBusy.value || plotExtractBusy.value) primary = { key: "progress", label: "查看运行进度" }
  else if (outlineGenerateManager.state.preview) primary = { key: "preview", label: "检查建议", dataAction: "view-outline-generate-preview" }
  else if (outlineAnalysisManager.state.progress?.failed || plotAutoExtractManager.state.progress?.failed || outlineGenerateManager.state.progress?.failed) primary = { key: "progress", label: "查看失败与恢复" }
  return [{ ...primary, primary: true }, ...base.filter(action => action.key !== primary.key)]
})
function runTool(key) {
  if (![...toolActions.value, ...moreTools.value].some(action => action.key === key && !action.disabled)) return
  if (key === "create") return props.subView === "threads" ? showCreateThreadForm() : showCreateArcForm()
  if (key === "ai") return showOutlineLayerAiForm(target.value, { selectedIds: selectedIds.value })
  if (key === "extract") return showPlotStructureAutoExtractForm()
  if (key === "analyze") return showOutlineAnalysisForm()
  if (key === "preview") return showOutlineGeneratePreview()
  if (key === "return") return closeReview()
  const selector = { progress: ".outline-task-status", information: "#outline-thread-information", "review-current": ".outline-thread-review, .outline-arc-review, .outline-scene-review" }[key]
  if (selector) return focusWorkspaceTool(headerEl.value?.parentElement, selector)
}
</script>
