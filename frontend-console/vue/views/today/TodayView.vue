<script setup>
import { computed } from "vue"
import { clearActiveWorkflow } from "../../../shared/workflowProgress.js"
import { getRouter } from "../../bridge/index.js"

const props = defineProps({
  project: { type: Object, default: null },
  summary: { type: Object, default: null },
  workflows: { type: Array, default: () => [] },
  loadError: { type: String, default: null },
})

const router = getRouter()
const projectTitle = computed(() => props.project?.title || props.project?.name || "当前作品")
const continuation = computed(() => props.summary?.continuation || null)
const writing = computed(() => props.summary?.writing || { chapter_count: 0, word_count: 0 })
const attention = computed(() => props.summary?.attention || {})
const importWorkflow = computed(() => (
  continuation.value
    ? null
    : props.workflows.find((workflow) => workflow.workflowType === "deep_import") || null
))
const resumeTitle = computed(() => {
  if (continuation.value) return continuation.value.title
  if (importWorkflow.value) return "继续整理导入内容"
  return "开始第一章"
})
const primaryLabel = computed(() => {
  if (continuation.value) return "继续写作"
  if (importWorkflow.value) return "继续整理"
  return "开始第一章"
})
const attentionItems = computed(() => [
  { key: "world_objects", label: "人物与设定", value: attention.value.world_objects || 0, view: "world", subView: "review-objects" },
  { key: "world_aliases", label: "别名", value: attention.value.world_aliases || 0, view: "world", subView: "review-aliases" },
  { key: "world_relations", label: "关系", value: attention.value.world_relations || 0, view: "world", subView: "review-relations" },
  { key: "outline_scenes", label: "场景", value: attention.value.outline_scenes || 0, view: "outline", subView: "scenes" },
  { key: "map_items", label: "地图资料", value: attention.value.map_items || 0, view: "map", subView: null },
])

const WORKFLOW_COPY = {
  deep_import: "正在整理导入内容",
  scene_auto_extraction: "正在整理正文结构",
  smart_dedup_scan: "正在检查重复资料",
  world_object_auto_extraction: "正在整理人物与设定",
  plot_structure_auto_extraction: "正在整理故事结构",
  map_observation_enrichment: "正在补充地图资料",
  publish_chapter: "正在更新正式正文",
  rag_reindex_novel: "正在准备查找资料",
  rag_retry_embeddings: "正在修复查找资料",
  story_outline_generate: "正在生成故事总览",
  outline_generate: "正在生成故事结构",
  writing_generate: "正在生成正文建议",
}

function openWriting() {
  const query = new URLSearchParams()
  if (continuation.value?.chapter_index != null) {
    query.set("chapter_index", String(continuation.value.chapter_index))
  }
  router.navigate("writing", null, true, query)
}

function runPrimaryAction() {
  if (importWorkflow.value) {
    openWorkflow(importWorkflow.value)
    return
  }
  openWriting()
}

function openAttention(item) {
  router.navigate(item.view, item.subView)
}

function workflowLabel(workflow) {
  if (workflow.stateUnknown) return "任务状态暂时无法读取"
  if (workflow.failed) return `${WORKFLOW_COPY[workflow.workflowType] || "后台整理"}需要处理`
  return WORKFLOW_COPY[workflow.workflowType] || "正在整理作品资料"
}

function workflowStatus(workflow) {
  if (workflow.stateUnknown) return "稍后重试，进度不会丢失"
  if (workflow.failed) return "原内容已保留，可以打开对应页面重试"
  if (workflow.percent != null) return `已完成 ${Math.round(workflow.percent)}%`
  return "可以离开此页，完成后会保留结果"
}

function workflowDestination(workflow) {
  if (["outline_generate", "story_outline_generate", "plot_structure_auto_extraction"].includes(workflow.workflowType)) return ["outline", "story-outline"]
  if (["rag_reindex_novel", "rag_retry_embeddings"].includes(workflow.workflowType)) return ["rag", "status"]
  if (workflow.workflowType === "map_observation_enrichment") return ["map", null]
  if (["world_object_auto_extraction", "smart_dedup_scan"].includes(workflow.workflowType)) return ["world", "review-objects"]
  if (workflow.view) return [workflow.view, null]
  return ["writing", null]
}

function openWorkflow(workflow) {
  const [view, subView] = workflowDestination(workflow)
  router.navigate(view, subView)
}

function dismissWorkflow(workflow) {
  clearActiveWorkflow(workflow.taskId)
  router.refresh()
}

function retry() {
  router.refresh()
}
</script>

<template>
  <main class="today-workspace" aria-labelledby="today-title">
    <header class="today-heading">
      <div>
        <span class="today-heading__eyebrow">今日工作</span>
        <h1 id="today-title">欢迎回到《{{ projectTitle }}》</h1>
        <p>从上次停下的地方继续，其他整理工作可以稍后处理。</p>
      </div>
      <button class="btn btn-sm btn-ghost" type="button" @click="router.navigate('project')">切换作品</button>
    </header>

    <section class="today-resume" aria-labelledby="today-resume-title">
      <div>
        <span class="today-resume__label">接着上次写</span>
        <h2 id="today-resume-title">{{ resumeTitle }}</h2>
        <p v-if="continuation">
          第 {{ continuation.chapter_index }} 章
          · {{ continuation.has_unpublished_changes ? '有尚未设为正式正文的修改' : '正文已保存' }}
        </p>
        <p v-else-if="importWorkflow">导入内容还在整理中，可以继续查看进度，也可以稍后回来。</p>
        <p v-else>准备好第一章后，作品的资料与结构会在创作过程中逐步生长。</p>
        <p v-if="summary" class="today-resume__stats">{{ writing.chapter_count }} 章 · {{ Number(writing.word_count || 0).toLocaleString() }} 字</p>
      </div>
      <button class="btn btn-primary today-resume__action" type="button" data-action="continue-writing" @click="runPrimaryAction">
        {{ primaryLabel }}
      </button>
    </section>

    <div v-if="loadError" class="today-inline-warning" role="alert">
      <div><strong>作品概览暂时没有更新</strong><p>{{ loadError }} 仍然可以直接进入写作。</p></div>
      <button class="btn btn-sm" type="button" @click="retry">重新加载</button>
    </div>

    <section v-if="summary" class="today-section" aria-labelledby="today-attention-title">
      <div class="today-section__heading">
        <div><h2 id="today-attention-title">需要你决定</h2><p>这些内容不会自动成为正式设定。</p></div>
        <span class="today-count">{{ attention.total || 0 }}</span>
      </div>
      <div class="today-attention-grid">
        <button v-for="item in attentionItems" :key="item.key" type="button" class="today-attention-card" @click="openAttention(item)">
          <strong>{{ item.value }}</strong><span>{{ item.label }}</span><i>{{ item.value ? '去处理' : '暂无待处理' }}</i>
        </button>
      </div>
    </section>

    <section v-if="workflows.length" class="today-section" aria-labelledby="today-workflows-title">
      <div class="today-section__heading"><div><h2 id="today-workflows-title">正在进行的整理</h2><p>离开页面不会中断，失败也不会覆盖原内容。</p></div></div>
      <div class="today-workflow-list">
        <article v-for="workflow in workflows" :key="workflow.taskId" class="today-workflow-card" :class="{ 'is-warning': workflow.failed || workflow.stateUnknown }">
          <div class="today-workflow-card__copy"><strong>{{ workflowLabel(workflow) }}</strong><span>{{ workflowStatus(workflow) }}</span></div>
          <progress v-if="workflow.percent != null && !workflow.failed" max="100" :value="workflow.percent" :aria-label="workflowStatus(workflow)"></progress>
          <div class="today-workflow-card__actions">
            <button class="btn btn-sm" type="button" @click="openWorkflow(workflow)">{{ workflow.failed ? '打开并处理' : '查看' }}</button>
            <button v-if="workflow.failed || workflow.stateUnknown" class="btn btn-sm btn-ghost" type="button" @click="dismissWorkflow(workflow)">从首页隐藏</button>
          </div>
        </article>
      </div>
    </section>
  </main>
</template>
