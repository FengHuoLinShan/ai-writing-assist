<!--
  OutlineHeader — outline 非 scenes 子视图的头部（vanilla _renderOutlineHeader
  L366-395 + _renderOutlineHeaderTitle L333-339 + _renderOutlineHeaderActions
  L340-365）。DOM class/data-action 逐节点保留（e2e/视觉基线契约）。
-->
<template>
  <div class="view-header view-header--with-tabs outline-toolbar">
    <div class="subnav">
      <span class="subnav-item" :class="{ active: subView === 'story-outline' }" data-action="nav-story-outline" @click="navigateSub('story-outline')">小说总纲</span>
      <span class="subnav-item" :class="{ active: subView === 'arcs' }" data-action="nav-arcs" @click="navigateSub('arcs')">篇章纲</span>
      <span class="subnav-item" :class="{ active: subView === 'threads' }" data-action="nav-threads" @click="navigateSub('threads')">剧情线</span>
      <span class="subnav-item" :class="{ active: subView === 'scenes' }" data-action="nav-scenes" @click="navigateSub('scenes')">场景工作台</span>
    </div>
    <div class="view-header__tail">
      <span class="view-header__title">
        <template v-if="subView === 'story-outline'">小说总纲<span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="subView === 'threads'">剧情线 <span class="view-header__count">共 {{ structureTotals.threads }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
        <template v-else-if="subView === 'arcs'">篇章纲 <span class="view-header__count">共 {{ structureTotals.arcs }} 个</span><span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span></template>
      </span>
      <div class="view-header__actions">
        <template v-if="subView === 'threads'">
          <button class="btn btn-sm btn-primary" data-action="create-thread" @click="showCreateThreadForm()">新建剧情线</button>
          <button class="btn btn-sm" data-action="ai-create-plot-thread" @click="showOutlineLayerAiForm('plot_thread')">AI 创作剧情线</button>
          <button class="btn btn-sm" data-action="analyze-outline" :disabled="analysisBusy" @click="showOutlineAnalysisForm()">{{ analysisBusy ? "AI 分析中" : "AI 分析大纲" }}</button>
          <button class="btn btn-sm" data-action="plot-structure-auto-extract" :disabled="plotExtractBusy" @click="showPlotStructureAutoExtractForm()">{{ plotExtractBusy ? "提取中..." : "从正文提取剧情线" }}</button>
        </template>
        <template v-else-if="subView === 'arcs'">
          <button class="btn btn-sm btn-primary" data-action="create-arc" @click="showCreateArcForm()">新建篇章纲</button>
          <button class="btn btn-sm" data-action="ai-create-outline-arc" @click="showOutlineLayerAiForm('outline_arc')">AI 创作篇章纲</button>
          <button class="btn btn-sm" data-action="analyze-outline" :disabled="analysisBusy" @click="showOutlineAnalysisForm()">{{ analysisBusy ? "AI 分析中" : "AI 分析大纲" }}</button>
          <button class="btn btn-sm" data-action="plot-structure-auto-extract" :disabled="plotExtractBusy" @click="showPlotStructureAutoExtractForm()">{{ plotExtractBusy ? "提取中..." : "从正文提取篇章纲" }}</button>
        </template>
        <span data-role="smart-dedup-action"></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { getAppState, getRouter } from "../../../bridge/index.js"
import { showCreateArcForm, showCreateThreadForm } from "../logic/outlineStructureOps.js"
import {
  showOutlineAnalysisForm,
  showOutlineLayerAiForm,
  showPlotStructureAutoExtractForm,
} from "../ai/outlineAiOps.js"
import { outlineAnalysisManager, plotAutoExtractManager } from "../ai/outlineWorkflowManagers.js"

const props = defineProps({
  subView: { type: String, default: "story-outline" },
  structureTotals: { type: Object, default: () => ({ threads: 0, arcs: 0, foreshadowing: 0, reveals: 0 }) },
})

const projectTitle = computed(() => {
  const project = getAppState()?.currentProject
  return project?.title || project?.name || ""
})

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
</script>
