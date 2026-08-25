<!--
  OutlineHeader — outline 四个子视图的共享头部（vanilla _renderOutlineHeader
  L366-395 + _renderOutlineHeaderTitle L333-339 + _renderOutlineHeaderActions
  L340-365）。稳定 class/data-action 保留（e2e/视觉基线契约）。
-->
<template>
  <div class="view-header view-header--with-tabs outline-toolbar">
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
        <slot name="actions">
          <template v-if="reviewMode && (subView === 'threads' || subView === 'arcs' || subView === 'scenes')">
            <button type="button" class="btn btn-sm" data-action="close-outline-generate-preview" @click="closeReview">返回{{ subViewLabel }}</button>
          </template>
          <template v-else-if="subView === 'threads'">
            <button type="button" class="btn btn-sm btn-primary" data-action="create-thread" @click="showCreateThreadForm()">新建剧情线</button>
            <button type="button" class="btn btn-sm" data-action="ai-create-plot-thread" @click="showOutlineLayerAiForm('plot_thread')">AI 创作剧情线</button>
            <details class="scene-workbench-tools outline-structure-tools">
              <summary class="btn btn-sm">分析与整理</summary>
              <div class="scene-workbench-tools__menu" @click.capture="closeToolMenu">
                <button type="button" class="btn btn-sm" data-action="analyze-outline" :disabled="analysisBusy" @click="showOutlineAnalysisForm()">{{ analysisBusy ? "AI 分析中" : "AI 分析大纲" }}</button>
                <button type="button" class="btn btn-sm" data-action="plot-structure-auto-extract" :disabled="plotExtractBusy" @click="showPlotStructureAutoExtractForm()">{{ plotExtractBusy ? "提取中..." : "从正文提取剧情线" }}</button>
                <span data-role="smart-dedup-action"></span>
              </div>
            </details>
          </template>
          <template v-else-if="subView === 'arcs'">
            <button type="button" class="btn btn-sm btn-primary" data-action="create-arc" @click="showCreateArcForm()">新建篇章</button>
            <button type="button" class="btn btn-sm" data-action="ai-create-outline-arc" @click="showOutlineLayerAiForm('outline_arc')">AI 规划篇章</button>
            <details class="scene-workbench-tools outline-structure-tools">
              <summary class="btn btn-sm">分析与整理</summary>
              <div class="scene-workbench-tools__menu" @click.capture="closeToolMenu">
                <button type="button" class="btn btn-sm" data-action="analyze-outline" :disabled="analysisBusy" @click="showOutlineAnalysisForm()">{{ analysisBusy ? "AI 分析中" : "AI 分析大纲" }}</button>
                <button type="button" class="btn btn-sm" data-action="plot-structure-auto-extract" :disabled="plotExtractBusy" @click="showPlotStructureAutoExtractForm()">{{ plotExtractBusy ? "整理中..." : "从正文整理篇章" }}</button>
                <span data-role="smart-dedup-action"></span>
              </div>
            </details>
          </template>
          <span v-else data-role="smart-dedup-action"></span>
        </slot>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { getAppState, getRouteQuery, getRouter } from "../../../bridge/index.js"
import { showCreateArcForm, showCreateThreadForm } from "../logic/outlineStructureOps.js"
import {
  showOutlineAnalysisForm,
  showOutlineLayerAiForm,
  showPlotStructureAutoExtractForm,
} from "../ai/outlineAiOps.js"
import { outlineAnalysisManager, plotAutoExtractManager } from "../ai/outlineWorkflowManagers.js"

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

function closeToolMenu(event) {
  if (!event.target.closest?.("button")) return
  const details = event.currentTarget.closest("details")
  details.open = false
  details.querySelector("summary")?.focus()
}
</script>
