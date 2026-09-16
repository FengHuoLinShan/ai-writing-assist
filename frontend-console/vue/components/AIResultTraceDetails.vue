<template>
  <details class="ai-result-trace" @toggle="handleToggle">
    <summary>查看本次依据与运行记录</summary>
    <div v-if="loading" class="ai-result-trace__muted" role="status">正在读取记录…</div>
    <div v-else-if="error" class="ai-result-trace__error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="btn btn-sm" @click.prevent="load(true)">重试</button>
    </div>
    <div v-else-if="confirmation" class="ai-result-trace__body">
      <section>
        <strong>参考资料</strong>
        <p>{{ confirmation.task || "本次 AI 操作" }} · {{ scopeLabel }} · {{ confirmationTime }}</p>
        <div v-if="selectedGroups.length" class="ai-result-trace__chips">
          <span v-for="group in selectedGroups" :key="group.key">{{ group.label }} {{ group.count }}</span>
        </div>
        <p v-else class="ai-result-trace__muted">旧记录未保留可展示的资料分组。</p>
      </section>

      <section>
        <strong>运行与结果</strong>
        <p>{{ resultStateLabel }}<template v-if="progress"> · {{ progress.statusLabel }}</template></p>
        <p v-if="progress?.stage && progress.stage !== progress.status" class="ai-result-trace__muted">当前阶段：{{ stageLabel }}</p>
        <p v-if="taskUnavailable" class="ai-result-trace__muted">运行详情已不可用，资料和成果回执仍保留。</p>
        <p v-if="progress?.errorMessage" class="ai-result-trace__error" role="alert">{{ progress.errorMessage }}</p>
        <p v-if="progress?.possibleCharge" class="ai-result-trace__warning" role="status">该运行可能已产生调用费用。</p>
        <p v-if="progress?.partialResult" class="ai-result-trace__warning" role="status">该运行保留了部分成果。</p>
        <p v-if="actionLabels.length" class="ai-result-trace__muted">可用操作：{{ actionLabels.join("、") }}。</p>
        <p v-else-if="progress?.retryable" class="ai-result-trace__muted">可回到原任务继续或重试。</p>
      </section>

      <section v-if="review">
        <strong>知识复核</strong>
        <p>{{ reviewLabel }}</p>
        <ul v-if="reviewIssues.length">
          <li v-for="(issue, index) in reviewIssues" :key="`${index}:${issue.message || ''}`">{{ issue.message }}</li>
        </ul>
        <p v-if="remainingReviewIssues" class="ai-result-trace__muted">另有 {{ remainingReviewIssues }} 条问题记录。</p>
      </section>

      <section v-if="staleReasons.length" class="ai-result-trace__warning" role="alert">
        <strong>当时依据后来已变化</strong>
        <p>当前成果和历史保留；如要再次生成或采用新版，请回到原入口重新确认资料。</p>
      </section>

      <section v-if="resultRefs.length">
        <strong>已记录成果</strong>
        <div class="ai-result-trace__actions">
          <button
            v-for="(reference, index) in resultRefs"
            :key="`${reference.type}:${reference.id}`"
            type="button"
            class="btn btn-sm"
            @click="openResult(reference)"
          >{{ resultLabel(reference, index) }}</button>
        </div>
      </section>
    </div>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { normalizeTaskProgress } from "../../shared/workflowProgress.js"
import { getApi, getToast } from "../bridge/index.js"
import { locateAssistantSource } from "../shared/assistantNavigation.js"
import { phaseDisplayLabel, phaseStatusLabel } from "./progressUtils.js"

const props = defineProps({
  projectId: { type: String, required: true },
  confirmationId: { type: String, required: true },
  taskId: { type: String, default: null },
  knowledgeReview: { type: Object, default: null },
})

const loading = ref(false)
const error = ref("")
const confirmation = ref(null)
const task = ref(null)
const taskUnavailable = ref(false)
let generation = 0

const SOURCE_LABELS = {
  chapters: "章节",
  characters: "人物",
  context_sections: "参考分区",
  locations: "地点",
  outline_arcs: "篇章",
  plot_threads: "剧情线",
  scenes: "场景",
  threads: "剧情线",
  world_entities: "世界资料",
  writing_drafts: "正文",
}

const RESULT_LABELS = {
  outline_arc: "打开篇章成果",
  plot_thread: "打开剧情线成果",
  scene: "打开场景成果",
  writing_candidate: "打开正文建议",
  writing_draft: "打开正文成果",
}

const RESULT_STATES = {
  adopted: "已采用",
  applied: "已采用",
  cancelled: "已取消",
  completed: "待你处理",
  confirmed: "资料已确认",
  done: "待你处理",
  failed: "未完成",
  needs_review: "依据已变化",
  rejected: "已拒绝",
  running: "正在生成",
  stale_context: "依据已变化",
}

const REVIEW_LABELS = {
  blocked: "存在阻断问题",
  checking: "正在复核",
  legacy_unchecked: "旧成果未经统一复核",
  passed: "已通过",
  unverifiable: "当时资料不足，无法完整复核",
}
const ACTION_LABELS = {
  abandon: "放弃本次任务",
  cancel: "停止后续处理",
  dismiss: "关闭运行记录",
  restart_origin: "回到原页面重新开始",
  resume: "继续任务",
  retry: "重试任务",
}

const progress = computed(() => task.value
  ? normalizeTaskProgress(task.value, task.value.task_type)
  : null)
const selectedGroups = computed(() => Object.entries(confirmation.value?.selected_asset_ids || {})
  .map(([key, values]) => ({ key, label: SOURCE_LABELS[key] || "参考资料", count: Array.isArray(values) ? values.length : 0 }))
  .filter((item) => item.count > 0))
const resultRefs = computed(() => (confirmation.value?.result_refs || [])
  .filter((item) => item?.type && item?.id && item.type !== "task"))
const staleReasons = computed(() => Array.isArray(confirmation.value?.stale_reasons)
  ? confirmation.value.stale_reasons
  : [])
const review = computed(() => props.knowledgeReview || task.value?.result?.knowledge_review || null)
const actionLabels = computed(() => (progress.value?.availableActions || [])
  .map((action) => ACTION_LABELS[action])
  .filter(Boolean))
const reviewIssues = computed(() => (Array.isArray(review.value?.issues) ? review.value.issues : []).slice(0, 10))
const remainingReviewIssues = computed(() => Math.max(0, (review.value?.issues?.length || 0) - reviewIssues.value.length))
const reviewLabel = computed(() => REVIEW_LABELS[review.value?.status] || "已保留复核回执")
const resultStateLabel = computed(() => RESULT_STATES[confirmation.value?.result_status] || "已保留运行记录")
const scopeLabel = computed(() => ({ arc: "当前篇章", chapter: "当前章节", full: "全部资料", project: "当前项目", scene: "当前场景", world: "世界资料" })[confirmation.value?.scope] || "已确认范围")
const confirmationTime = computed(() => {
  const parsed = new Date(confirmation.value?.compiled_at || "")
  return Number.isNaN(parsed.getTime()) ? "已记录" : parsed.toLocaleString("zh-CN")
})
const stageLabel = computed(() => {
  const stage = String(progress.value?.stage || "").trim()
  const phaseLabel = phaseDisplayLabel(stage)
  if (phaseLabel !== stage) return phaseLabel
  const statusLabel = phaseStatusLabel(stage)
  if (statusLabel !== stage) return statusLabel
  return /^[a-z0-9_.:-]+$/i.test(stage) ? "处理中" : stage
})

async function load(force = false) {
  if (loading.value || (confirmation.value && !force)) return
  const token = ++generation
  loading.value = true
  error.value = ""
  taskUnavailable.value = false
  const api = getApi()
  const [confirmationResult, taskResult] = await Promise.allSettled([
    api.context.getConfirmation(props.confirmationId, props.projectId),
    props.taskId ? api.tasks.get(props.taskId, props.projectId) : Promise.resolve(null),
  ])
  if (token !== generation) return
  loading.value = false
  if (confirmationResult.status === "rejected") {
    error.value = confirmationResult.reason?.message || "本次记录暂时无法读取"
    confirmation.value = null
    task.value = null
    return
  }
  confirmation.value = confirmationResult.value
  if (taskResult.status === "fulfilled") task.value = taskResult.value
  else {
    task.value = null
    taskUnavailable.value = true
  }
}

function handleToggle(event) {
  if (event.currentTarget.open) void load()
}

function openResult(reference) {
  if (!locateAssistantSource(reference)) getToast()("请从原工作区打开这项成果", "warning")
}

function resultLabel(reference, index) {
  return RESULT_LABELS[reference.type] || `打开第 ${index + 1} 项成果`
}

watch(
  () => [props.projectId, props.confirmationId, props.taskId],
  () => {
    generation += 1
    loading.value = false
    error.value = ""
    confirmation.value = null
    task.value = null
    taskUnavailable.value = false
  },
)
onBeforeUnmount(() => { generation += 1 })
</script>

<style scoped>
.ai-result-trace{margin-top:12px;border-top:1px solid var(--border);padding-top:10px}.ai-result-trace>summary{cursor:pointer;font-weight:600;color:var(--text-primary)}.ai-result-trace__body{display:grid;gap:12px;margin-top:10px}.ai-result-trace__body section{display:grid;gap:5px}.ai-result-trace__body p,.ai-result-trace__body ul{margin:0}.ai-result-trace__body ul{padding-left:20px}.ai-result-trace__chips,.ai-result-trace__actions{display:flex;flex-wrap:wrap;gap:6px}.ai-result-trace__chips span{padding:3px 8px;border-radius:var(--radius-full);background:var(--bg-muted);font-size:var(--text-sm)}.ai-result-trace__muted{color:var(--text-secondary);font-size:var(--text-sm)}.ai-result-trace__warning{padding:8px;border-left:2px solid var(--warning);background:var(--warning-soft)}.ai-result-trace__error{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:10px;color:var(--error)}
</style>
