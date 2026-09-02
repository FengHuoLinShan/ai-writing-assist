<script setup>
import { computed, ref } from "vue"
import { clearActiveWorkflow } from "../../../shared/workflowProgress.js"
import { getApi, getConfirmAction, getRouter, getToast } from "../../bridge/index.js"
import { writeCreativeContinuation } from "../generate/generateSession.js"
import { openAuthorTaskSource } from "../writing/home/authorTaskSource.js"
import { readWritingPointer } from "../writing/writingSession.js"

const props = defineProps({
  project: { type: Object, default: null },
  summary: { type: Object, default: null },
  workflows: { type: Array, default: () => [] },
  creativeContinuation: { type: Object, default: null },
  worldContinuations: { type: Array, default: () => [] },
  continuationWarning: { type: String, default: null },
  worldLoadError: { type: String, default: null },
  loadError: { type: String, default: null },
  onOpenAi: { type: Function, default: null },
})

const router = getRouter()
const api = getApi()
const confirmAction = getConfirmAction()
const toast = getToast()
const dismissedWorkflowIds = ref(new Set())
const visibleWorkflows = computed(() => props.workflows.filter((workflow) => !dismissedWorkflowIds.value.has(workflow.taskId)))
const projectId = computed(() => props.summary?.project_id || props.project?.id || null)
const projectTitle = computed(() => props.project?.title || props.project?.name || "当前作品")
const continuation = computed(() => props.summary?.continuation || null)
const writing = computed(() => props.summary?.writing || { chapter_count: 0, word_count: 0 })
const attention = computed(() => props.summary?.attention || {})
const authorTasks = computed(() => props.summary?.author_tasks || {
  today_count: 0,
  inbox_count: 0,
  later_count: 0,
  preview: [],
})
const completedTaskIds = ref(new Set())
const authorTaskPreview = computed(() => Array.isArray(authorTasks.value.preview)
  ? authorTasks.value.preview.filter((task) => !completedTaskIds.value.has(task.id)).slice(0, 3)
  : [])
const taskBusyIds = ref(new Set())
const hasWritingContent = computed(() => Boolean(
  continuation.value || Number(writing.value.chapter_count || 0) > 0,
))
const worldTracks = computed(() => {
  const seen = new Set()
  return [props.creativeContinuation, ...props.worldContinuations].filter((item) => {
    if (!item?.key || seen.has(item.key)) return false
    seen.add(item.key)
    return true
  })
})
const primaryWorld = computed(() => (
  props.summary && !hasWritingContent.value ? worldTracks.value[0] || null : null
))
const secondaryWorld = computed(() => (
  hasWritingContent.value ? worldTracks.value[0] || null : null
))
const unfinishedWorld = computed(() => worldTracks.value.filter((item) => (
  item.key !== primaryWorld.value?.key && item.key !== secondaryWorld.value?.key
)))
const importWorkflow = computed(() => (
  !props.summary || hasWritingContent.value || primaryWorld.value
    ? null
    : visibleWorkflows.value.find((workflow) => workflow.workflowType === "deep_import") || null
))
const startWorldCore = computed(() => Boolean(
  props.summary
  && !primaryWorld.value
  && !continuation.value
  && !importWorkflow.value
  && Number(writing.value.chapter_count || 0) === 0
))
const resumeTitle = computed(() => {
  if (continuation.value) return `继续第 ${continuation.value.chapter_index} 章正文`
  if (hasWritingContent.value) return "继续正文写作"
  if (primaryWorld.value) return primaryWorld.value.title
  if (importWorkflow.value) return "继续整理导入内容"
  if (!props.summary) return "继续写作"
  return "开始第一章"
})
const primaryLabel = computed(() => {
  if (hasWritingContent.value) return "进入正文编辑"
  if (primaryWorld.value) return primaryWorld.value.destination === "world_suggestion_review" ? "去审查" : "继续创作"
  if (importWorkflow.value) return "继续整理"
  if (!props.summary) return "进入写作"
  return "开始第一章"
})
const resumeLabel = computed(() => hasWritingContent.value
  ? "正文写作"
  : primaryWorld.value ? "接着上次创作" : "接着上次写")
const attentionCategories = computed(() => [
  { key: "world_objects", label: "人物与设定", value: attention.value.world_objects || 0, view: "world", subView: "review", reviewKind: "objects" },
  { key: "world_aliases", label: "别名", value: attention.value.world_aliases || 0, view: "world", subView: "review", reviewKind: "aliases" },
  { key: "world_relations", label: "关系", value: attention.value.world_relations || 0, view: "world", subView: "review", reviewKind: "relations" },
  { key: "outline_scenes", label: "场景", value: attention.value.outline_scenes || 0, view: "outline", subView: "scenes" },
])
const hasProjectedAttention = computed(() => Array.isArray(attention.value.items))
const attentionRows = computed(() => hasProjectedAttention.value ? attention.value.items : [])
const attentionTotal = computed(() => hasProjectedAttention.value
  ? Number(attention.value.actionable_total || 0)
  : Number(attention.value.total || 0))
const moreAttentionTargets = computed(() => Array.isArray(attention.value.more_targets)
  ? attention.value.more_targets
  : [])

const SOURCE_LABELS = {
  writing_conflict: "正文",
  world_conflict: "世界设定",
  world_object: "人物与设定",
  world_alias_group: "别名",
  world_relation_group: "关系",
  world_suggestion: "创设建议",
  outline_scene_health: "场景结构",
  outline_fusion: "场景融合",
}

function sourceLabel(item) {
  return SOURCE_LABELS[item?.source_kind] || "作品"
}

function actionLabel(action) {
  return action === "needs_decision" ? "需要决定" : "可以改进"
}

function relevanceLabel(relevance) {
  if (relevance === "exact_scene") return "当前场景"
  if (relevance === "current_chapter") return "本章"
  return null
}

const WORKFLOW_COPY = {
  deep_import: "正在整理导入内容",
  scene_auto_extraction: "正在整理正文结构",
  smart_dedup_scan: "正在检查重复资料",
  world_object_auto_extraction: "正在整理人物与设定",
  plot_structure_auto_extraction: "正在整理故事结构",
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
    const pointer = readWritingPointer(projectId.value)
    if (pointer?.chapter === Number(continuation.value.chapter_index) && pointer.sceneId) {
      query.set("scene_id", pointer.sceneId)
    }
  }
  router.navigate("writing", null, true, query)
}

function openTasks(scope = "today") {
  router.navigate("writing", null, true, new URLSearchParams({ home: "1", panel: "tasks", scope }))
}

async function completeTask(task, event) {
  if (!task?.id || taskBusyIds.value.has(task.id)) return
  const checkbox = event?.currentTarget
  taskBusyIds.value = new Set([...taskBusyIds.value, task.id])
  try {
    await api.projects.patchAuthorTask(projectId.value, task.id, {
      status: "completed",
      expected_updated_at: task.updated_at || undefined,
    })
    completedTaskIds.value = new Set([...completedTaskIds.value, task.id])
    toast("任务已完成", "success")
    router.refresh()
  } catch (error) {
    if (checkbox) checkbox.checked = false
    toast(error?.message || "任务更新失败", "error")
    if (error?.status === 409) router.refresh()
  } finally {
    const next = new Set(taskBusyIds.value)
    next.delete(task.id)
    taskBusyIds.value = next
  }
}

function runPrimaryAction() {
  if (hasWritingContent.value) {
    openWriting()
    return
  }
  if (primaryWorld.value) {
    openCreativeContinuation(primaryWorld.value)
    return
  }
  if (importWorkflow.value) {
    openWorkflow(importWorkflow.value)
    return
  }
  openWriting()
}

function openWorldCore() {
  if (props.onOpenAi?.({ owner: "world", preset: "world_core", targetKind: "core_entity" })) return
  router.navigate("generate", null, true, new URLSearchParams({ tab: "world", target: "core_entity", preset: "world_core" }))
}

function openCreativeContinuation(item) {
  if (!item) return
  if (item.destination === "world_adoption_review") {
    router.navigate("world", "bible", true, new URLSearchParams({ adoption_package_id: item.route.package_id }))
    return
  }
  writeCreativeContinuation(projectId.value, { destination: item.destination, route: item.route })
  if (item.destination === "generate") {
    if (props.onOpenAi?.({
      owner: "world",
      sourcePageId: item.route.source_page_id || null,
      targetKind: item.route.target || "core_entity",
      preset: item.route.preset || "custom",
      checkpointId: item.route.checkpoint_id || null,
    })) return
    const query = new URLSearchParams({ tab: "world", target: item.route.target })
    if (item.route.source_page_id) query.set("source_page_id", item.route.source_page_id)
    if (item.route.preset) query.set("preset", item.route.preset)
    if (item.route.checkpoint_id) query.set("checkpoint_id", item.route.checkpoint_id)
    router.navigate("generate", null, true, query)
    return
  }
  if (item.destination === "world_bible_draft") {
    const query = new URLSearchParams({ draft_id: item.route.draft_id })
    if (item.route.page_id) query.set("page_id", item.route.page_id)
    router.navigate("world", "bible", true, query)
    return
  }
  router.navigate("world", "bible", true, new URLSearchParams({
    open: "suggestions",
    suggestion_id: item.route.suggestion_id,
  }))
}

function openAttention(item) {
  const target = item?.target || {}
  const query = new URLSearchParams()

  if (target.kind === "writing_conflict") {
    if (target.chapter_index != null) query.set("chapter_index", String(target.chapter_index))
    if (target.scene_id) query.set("scene_id", target.scene_id)
    if (target.item_id) query.set("conflict_item_id", target.item_id)
    query.set("open", "conflicts")
    router.navigate("writing", null, true, query)
  } else if (target.kind === "world_bible_conflict") {
    if (target.page_id) query.set("page_id", target.page_id)
    if (target.item_id) query.set("conflict_item_id", target.item_id)
    query.set("open", "conflicts")
    router.navigate("world", "bible", true, query)
  } else if (target.kind === "world_review_objects") {
    if (target.item_id) query.set("entity_id", target.item_id)
    if (target.chapter_index != null) query.set("source_chapter_index", String(target.chapter_index))
    query.set("kind", "objects")
    router.navigate("world", "review", true, query)
  } else if (target.kind === "world_review_aliases") {
    if (target.item_id) query.set("group_id", target.item_id)
    if (target.chapter_index != null) query.set("source_chapter_index", String(target.chapter_index))
    query.set("kind", "aliases")
    router.navigate("world", "review", true, query)
  } else if (target.kind === "world_review_relations") {
    if (target.item_id) query.set("group_id", target.item_id)
    if (target.chapter_index != null) query.set("source_chapter_index", String(target.chapter_index))
    query.set("kind", "relations")
    router.navigate("world", "review", true, query)
  } else if (target.kind === "world_suggestion") {
    if (target.suggestion_id) query.set("suggestion_id", target.suggestion_id)
    query.set("open", "suggestions")
    router.navigate("world", "bible", true, query)
  } else if (target.kind === "worldbook_import") {
    if (target.suggestion_id) query.set("suggestion_id", target.suggestion_id)
    query.set("open", "worldbook-import")
    router.navigate("world", "bible", true, query)
  } else if (target.kind === "world_adoption") {
    if (target.suggestion_id) query.set("adoption_package_id", target.suggestion_id)
    router.navigate("world", "bible", true, query)
  } else if (["outline_scene", "outline_fusion"].includes(target.kind)) {
    if (target.chapter_index != null) query.set("chapter_index", String(target.chapter_index))
    if (target.scene_id) query.set("scene_id", target.scene_id)
    if (target.suggestion_id) query.set("suggestion_id", target.suggestion_id)
    router.navigate("outline", "scenes", true, query)
  }
}

function openAttentionCategory(item) {
  const query = new URLSearchParams()
  if (item.reviewKind) query.set("kind", item.reviewKind)
  router.navigate(item.view, item.subView, true, query)
}

function openMoreAttention() {
  const target = moreAttentionTargets.value[0]
  if (target) return openAttention(target)
  const category = attentionCategories.value.find((item) => item.value)
  if (category) openAttentionCategory(category)
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
  if (["world_object_auto_extraction", "smart_dedup_scan"].includes(workflow.workflowType)) return ["world", "review-objects"]
  if (workflow.view) return [workflow.view, null]
  return ["writing", null]
}

function openWorkflow(workflow) {
  const [view, subView] = workflowDestination(workflow)
  if (view === "generate" && props.onOpenAi?.({ owner: "world" })) return
  router.navigate(view, subView)
}

function dismissWorkflow(workflow) {
  confirmAction(
    "从首页隐藏后，任务仍可以在对应页面找回。",
    () => {
      clearActiveWorkflow(workflow.taskId)
      dismissedWorkflowIds.value = new Set([...dismissedWorkflowIds.value, workflow.taskId])
      toast("已从首页隐藏", "success")
    },
    "从首页隐藏",
  )
}

function retry() {
  router.refresh()
}
</script>

<template>
  <main class="today-workspace" aria-labelledby="today-title">
    <header class="today-heading">
      <div>
        <span class="today-heading__eyebrow">写作首页</span>
        <h1 id="today-title">欢迎回到《{{ projectTitle }}》</h1>
        <p>从上次停下的地方继续，其他整理工作可以稍后处理。</p>
      </div>
      <button class="btn btn-sm btn-ghost" type="button" data-action="switch-project" @click="router.navigate('project')">切换作品</button>
    </header>

    <div class="today-resume-grid" :class="{ 'today-resume-grid--single': !secondaryWorld }">
      <section class="today-resume" aria-labelledby="today-resume-title">
        <div>
          <span class="today-resume__label">{{ resumeLabel }}</span>
          <h2 id="today-resume-title">{{ resumeTitle }}</h2>
          <template v-if="primaryWorld">
            <p>{{ primaryWorld.description }}</p>
            <p v-if="!creativeContinuation">本机未发送的文字和对话不会出现在其他设备。</p>
          </template>
          <p v-else-if="continuation">
            {{ continuation.title }}
            · {{ continuation.has_unpublished_changes ? '有尚未设为正式正文的修改' : '正文已保存' }}
          </p>
          <p v-else-if="importWorkflow">导入内容还在整理中，可以继续查看进度，也可以稍后回来。</p>
          <p v-else-if="startWorldCore">先写下第一章；如果你已有灵感，也可以先整理世界观。</p>
          <p v-else>准备好第一章后，作品的资料与结构会在创作过程中逐步生长。</p>
          <p v-if="summary" class="today-resume__stats">{{ writing.chapter_count }} 章 · {{ Number(writing.word_count || 0).toLocaleString() }} 字</p>
        </div>
        <div class="today-resume__actions">
          <button class="btn btn-primary today-resume__action" type="button" :data-action="primaryWorld ? 'continue-world' : 'continue-writing'" @click="runPrimaryAction">
            {{ primaryLabel }}
          </button>
          <button v-if="startWorldCore" class="btn btn-ghost" type="button" data-action="start-world-core" @click="openWorldCore">先整理世界观</button>
        </div>
      </section>

      <article v-if="secondaryWorld" class="today-resume-secondary" aria-labelledby="today-resume-secondary-title">
        <div>
          <span class="today-resume__label">未完成创作</span>
          <h2 id="today-resume-secondary-title">{{ secondaryWorld.title }}</h2>
          <p>{{ secondaryWorld.description }}</p>
          <p v-if="secondaryWorld.key !== creativeContinuation?.key">本机未发送的文字和对话不会出现在其他设备。</p>
        </div>
        <button class="btn" type="button" data-action="continue-world-secondary" @click="openCreativeContinuation(secondaryWorld)">
          {{ ['world_suggestion_review', 'world_adoption_review'].includes(secondaryWorld.destination) ? '去审查' : '打开工作稿' }}
        </button>
      </article>
    </div>

    <div v-if="loadError" class="today-inline-warning error-card" role="alert">
      <div><strong>作品概览暂时没有更新</strong><p>{{ loadError }} 仍然可以直接进入写作。</p></div>
      <button class="btn btn-sm" type="button" @click="retry">重新加载</button>
    </div>

    <div v-if="continuationWarning || worldLoadError" class="today-inline-warning" role="status">
      <div><strong>世界设定恢复提示</strong><p v-if="continuationWarning">{{ continuationWarning }}</p><p v-if="worldLoadError">{{ worldLoadError }}</p></div>
      <button v-if="worldLoadError" class="btn btn-sm" type="button" @click="retry">重新加载</button>
    </div>

    <section v-if="summary" class="today-section today-author-tasks" aria-labelledby="today-author-tasks-title">
      <div class="today-section__heading">
        <div>
          <h2 id="today-author-tasks-title">计划中的任务</h2>
          <p>今天 {{ authorTasks.today_count }} 项 · 收件箱 {{ authorTasks.inbox_count }} 项</p>
        </div>
        <div class="today-author-tasks__actions">
          <button type="button" class="btn btn-sm" @click="openTasks('inbox')">＋ 添加</button>
          <button type="button" class="btn btn-sm btn-ghost" @click="openTasks('today')">查看全部</button>
        </div>
      </div>
      <ul v-if="authorTaskPreview.length" class="today-author-task-list">
        <li v-for="task in authorTaskPreview" :key="task.id" class="today-author-task-row">
          <label class="today-author-task-row__check">
            <input type="checkbox" :disabled="taskBusyIds.has(task.id)" :aria-label="`完成任务：${task.title}`" @change="completeTask(task, $event)">
          </label>
          <strong>{{ task.title }}</strong>
          <button v-if="task.source?.available" type="button" class="btn btn-sm btn-ghost" @click="openAuthorTaskSource(task.source, router)">{{ task.source.label }} →</button>
          <span v-else-if="task.source">来源已失效</span>
        </li>
      </ul>
      <div v-else class="today-author-task-empty">
        <p>今天没有待办；需要时可以记下一项，不会混入系统决定或后台整理。</p>
      </div>
    </section>

    <section v-if="unfinishedWorld.length" class="today-section" aria-labelledby="today-unfinished-world-title">
      <div class="today-section__heading">
        <div>
          <h2 id="today-unfinished-world-title">未完成创作</h2>
          <p>{{ creativeContinuation ? '这些服务器工作稿和建议可以稍后继续。' : '服务器工作稿与建议可跨设备继续；本机未发送的文字和对话不会出现在其他设备。' }}</p>
        </div>
      </div>
      <div class="today-workflow-list">
        <article v-for="item in unfinishedWorld" :key="item.key" class="today-workflow-card">
          <div class="today-workflow-card__copy"><strong>{{ item.title }}</strong><span>{{ item.description }}</span></div>
          <div class="today-workflow-card__actions">
            <button class="btn btn-sm" type="button" @click="openCreativeContinuation(item)">{{ ['world_suggestion_review', 'world_adoption_review'].includes(item.destination) ? '去审查' : '打开工作稿' }}</button>
          </div>
        </article>
      </div>
    </section>

    <section class="today-section" aria-labelledby="today-attention-title">
      <div class="today-section__heading">
        <div><h2 id="today-attention-title">需要你决定</h2><p>按正在写的场景优先；不会自动修改作品。</p></div>
        <span v-if="summary && attentionTotal" class="today-count">{{ attentionTotal }}</span>
      </div>
      <div v-if="attentionRows.length" class="today-attention-list">
        <article v-for="item in attentionRows" :key="item.key" class="today-attention-row">
          <div class="today-attention-row__copy">
            <span class="today-attention-row__source">{{ sourceLabel(item) }}</span>
            <strong>{{ item.title }}</strong>
            <p>{{ item.summary }}</p>
          </div>
          <div class="today-attention-row__meta">
            <span class="badge" :class="{ 'badge-warning': item.author_action === 'needs_decision' }">{{ actionLabel(item.author_action) }}</span>
            <span v-if="relevanceLabel(item.relevance)" class="badge">{{ relevanceLabel(item.relevance) }}</span>
            <button class="btn btn-sm" type="button" @click="openAttention(item)">查看</button>
          </div>
        </article>
      </div>
      <div v-else-if="hasProjectedAttention" class="empty-state today-attention-empty"><p>当前没有需要你决定的内容</p></div>
      <div v-else class="today-attention-grid">
        <button v-for="item in attentionCategories" :key="item.key" type="button" class="today-attention-card" :disabled="Boolean(summary) && !item.value" @click="openAttentionCategory(item)">
          <strong>{{ summary ? item.value : '—' }}</strong><span>{{ item.label }}</span><i>{{ !summary ? '打开查看' : item.value ? '去处理' : '暂无待处理' }}</i>
        </button>
      </div>
      <div v-if="attention.has_more" class="today-attention-footer">
        <span>还有 {{ Math.max(0, attentionTotal - attentionRows.length) }} 项，可在对应页面继续处理。</span>
        <button type="button" class="btn btn-sm btn-ghost" @click="openMoreAttention">查看更多</button>
      </div>
    </section>

    <section v-if="visibleWorkflows.length" class="today-section" aria-labelledby="today-workflows-title">
      <div class="today-section__heading"><div><h2 id="today-workflows-title">正在进行的整理</h2><p>离开页面不会中断，失败也不会覆盖原内容。</p></div></div>
      <div class="today-workflow-list">
        <article v-for="workflow in visibleWorkflows" :key="workflow.taskId" class="today-workflow-card" :class="{ 'is-warning': workflow.failed || workflow.stateUnknown }">
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

<style scoped>
.today-author-tasks__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.today-author-task-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.today-author-task-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; min-height: 44px; padding: 8px 10px; border: 1px solid var(--border); }
.today-author-task-row__check { display: grid; width: 44px; height: 44px; place-items: center; cursor: pointer; }
.today-author-task-row__check input { width: 20px; height: 20px; }
.today-author-task-row span { color: var(--text-muted); }
.today-author-task-empty { padding: var(--space-5); border: 1px dashed var(--border); border-radius: var(--radius-xl); }
@media (max-width: 760px) {
  .today-author-task-row { grid-template-columns: auto minmax(0, 1fr); }
  .today-author-task-row > :last-child:not(strong) { grid-column: 2; justify-self: start; }
}
</style>
