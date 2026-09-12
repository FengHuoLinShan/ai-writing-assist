<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getAppState, getRouter } from "../bridge/index.js"
import TargetedCompletionPanel from "./TargetedCompletionPanel.vue"

const emit = defineEmits(["prepare"])
const props = defineProps({ projectId: { type: String, required: true } })
const historyExpanded = ref(false)
const activeTab = ref("history")
const assetCounts = ref(null)
const items = ref([])
const total = ref(0)
const skip = ref(0)
const loading = ref(false)
const error = ref("")
const expanded = ref("")
const cleanupPreview = ref(null)
const cleanupBusy = ref(false)
const cleanupError = ref("")
let alive = true
let epoch = 0
let timer

const labels = {
  deep_import: "完整整理",
  scene_auto_extraction: "场景整理",
  world_object_auto_extraction: "世界资料整理",
  plot_structure_auto_extraction: "剧情结构整理",
  targeted_completion: "专项查漏",
}
const assetLabels = {
  adopted: "已采用",
  review: "待审",
  not_adopted: "未采用",
  scenes: "场景",
  world_objects: "世界资料",
  entities: "世界资料",
  plot_threads: "剧情线",
  outline_arcs: "篇章",
  structure_assets: "剧情结构",
}
const recycleItems = computed(() => items.value.filter((item) => (
  item.status === "cancelled"
  && (item.cleanup_eligible || ["partial", "complete"].includes(item.cleanup_status))
)))
const selectedItems = computed(() => activeTab.value === "recycle" ? recycleItems.value : items.value)
const visibleItems = computed(() => historyExpanded.value ? selectedItems.value : selectedItems.value.slice(0, 3))

async function load(offset = skip.value) {
  const projectId = props.projectId
  const token = ++epoch
  loading.value = true
  error.value = ""
  clearTimeout(timer)
  try {
    const result = await getApi().imports.recentWorkflows(projectId, offset)
    if (!alive || token !== epoch || getAppState()?.currentProjectId !== projectId) return
    items.value = result.items || []
    total.value = Number(result.total || 0)
    skip.value = offset
    if (items.value.some((item) => ["pending", "running"].includes(item.status))) {
      timer = setTimeout(() => load(), 4000)
    }
  } catch (err) {
    if (alive && token === epoch) error.value = err.message || "整理记录读取失败"
  } finally {
    if (alive && token === epoch) loading.value = false
  }
}

async function resumeRun(item) {
  loading.value = true
  error.value = ""
  try {
    await getApi().imports.resumeDeepImport(item.task_id)
    await load()
  } catch (err) {
    error.value = err.message || "继续整理失败，原成果保留"
  } finally {
    loading.value = false
  }
}

function prepareRetry(item, selectedStage = null) {
  const stage = selectedStage || {
    deep_import: "deep",
    scene_auto_extraction: "scenes",
    world_object_auto_extraction: "world_objects",
    plot_structure_auto_extraction: "plot_structure",
  }[item.workflow_type]
  if (stage) emit("prepare", { stage, start: item.start_chapter, end: item.end_chapter })
}

function outcome(item) {
  if (["pending", "running"].includes(item.status)) return "正在整理，可离开后继续查看"
  if (item.status === "cancelled") return "已停止。停止只会停止整理，已经产生的内容仍会保留。"
  if (item.workflow_type === "plot_structure_auto_extraction" && item.failed_stages?.includes("plot_structure") && !(item.asset_summary?.adopted || item.asset_summary?.review)) return "本次未得到可用结构；已有资料保留，可重新核对本阶段。"
  if (item.status === "failed" || item.quality_status === "failed") return "本次未完成，请核对原因或从检查点继续。"
  return item.message || "查看本次成果"
}

function cleanupOutcome(item) {
  if (item.cleanup_status === "complete") return "已处理，历史记录仍然保留。"
  if (item.cleanup_status === "partial") return "部分内容受后续修改或引用保护，可重新预览。"
  return "停止只会停止整理，内容仍保留；你可以查看范围后决定是否清理。"
}

function assetSummaryText(summary = {}) {
  const values = Object.entries(summary)
    .filter(([key, value]) => assetLabels[key] && Number(value) > 0)
    .map(([key, value]) => `${assetLabels[key]} ${Number(value)}`)
  return values.join(" · ") || "当前记录没有可清理的成果计数"
}

async function previewCleanup(item) {
  const projectId = props.projectId
  const token = epoch
  cleanupBusy.value = true
  cleanupError.value = ""
  try {
    const preview = await getApi().imports.previewCancelledCleanup(item.task_id, projectId)
    if (!alive || token !== epoch || getAppState()?.currentProjectId !== projectId) return
    cleanupPreview.value = preview
  } catch (err) {
    if (alive && token === epoch) cleanupError.value = err.message || "清理范围读取失败"
  } finally {
    if (alive && token === epoch) cleanupBusy.value = false
  }
}

async function executeCleanup() {
  const preview = cleanupPreview.value
  const projectId = props.projectId
  if (!preview?.task_id || !preview.cleanup_fingerprint) return
  const token = epoch
  cleanupBusy.value = true
  cleanupError.value = ""
  try {
    const result = await getApi().imports.cleanupCancelled(preview.task_id, {
      novel_id: projectId,
      expected_cleanup_fingerprint: preview.cleanup_fingerprint,
      confirmed: true,
    })
    if (!alive || token !== epoch || getAppState()?.currentProjectId !== projectId) return
    cleanupPreview.value = { ...preview, ...result }
    cleanupBusy.value = false
    await load()
  } catch (err) {
    if (alive && token === epoch) cleanupError.value = err.message || "清理失败，请刷新范围后重试"
  } finally {
    if (alive && token === epoch) cleanupBusy.value = false
  }
}

async function loadCounts() {
  const api = getApi()
  const projectId = props.projectId
  const responses = await Promise.allSettled([
    api.world.listEntities({ novel_id: projectId, display_state: "active", skip: 0, limit: 1 }),
    api.outline.listThreads(projectId, { status: "canonical", skip: 0, limit: 1 }),
    api.outline.listArcs(projectId, { status: "canonical", skip: 0, limit: 1 }),
  ])
  if (alive && getAppState()?.currentProjectId === projectId) {
    assetCounts.value = responses.map((result) => (
      result.status === "fulfilled" && Number.isFinite(result.value?.total)
        ? result.value.total
        : "—"
    ))
  }
}

function openResults(kind) {
  const view = kind === "world" ? "world" : "outline"
  getRouter()?.navigate(view, kind === "world" ? "review" : "threads")
}

watch(() => props.projectId, () => {
  epoch += 1
  clearTimeout(timer)
  items.value = []
  cleanupPreview.value = null
  cleanupError.value = ""
  historyExpanded.value = false
  void load(0)
  void loadCounts()
}, { immediate: true })

onBeforeUnmount(() => {
  alive = false
  epoch += 1
  clearTimeout(timer)
})
</script>

<template>
  <section class="organization-history" aria-label="项目整理进度">
    <h4>已有成果与最近整理</h4>
    <p>先使用基础成果；可选查漏由你决定何时继续。</p>
    <p v-if="assetCounts">当前已采用：{{ assetCounts[0] }} 张资料卡 · {{ assetCounts[1] }} 条剧情线 · {{ assetCounts[2] }} 个篇章</p>
    <div class="organization-actions">
      <button class="btn btn-sm" type="button" @click="openResults('world')">审阅世界资料</button>
      <button class="btn btn-sm" type="button" @click="openResults('outline')">查看剧情结构</button>
      <button class="btn btn-sm" type="button" :disabled="loading" @click="load()">刷新进度</button>
    </div>
    <div class="organization-tabs" role="tablist" aria-label="整理记录分类">
      <button type="button" role="tab" :aria-selected="activeTab === 'history'" :class="{ active: activeTab === 'history' }" @click="activeTab = 'history'">整理记录</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'recycle'" :class="{ active: activeTab === 'recycle' }" @click="activeTab = 'recycle'">回收站<span v-if="recycleItems.length"> {{ recycleItems.length }}</span></button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !items.length" role="status">正在读取整理记录…</p>
    <p v-else-if="activeTab === 'history' && !items.length">还没有整理记录，可从下方开始。</p>
    <p v-else-if="activeTab === 'recycle' && !recycleItems.length">回收站是空的。取消整理不会自动删除内容。</p>
    <article v-for="item in visibleItems" :key="item.task_id">
      <strong>{{ labels[item.workflow_type] || '资料整理' }} · 第 {{ item.start_chapter }}—{{ item.end_chapter }} 章</strong>
      <template v-if="activeTab === 'history'">
        <p>{{ outcome(item) }}</p>
        <p>结束时记录：采用 {{ item.asset_summary?.adopted || 0 }} · 待审 {{ item.asset_summary?.review || 0 }} · 未采用 {{ item.asset_summary?.not_adopted || 0 }}</p>
        <button v-for="stage in item.failed_stages || []" :key="stage" type="button" class="btn btn-sm" @click="prepareRetry(item, stage)">重新核对{{ { scenes: '场景', world_objects: '世界资料', plot_structure: '剧情结构' }[stage] }}</button>
        <button v-if="item.recovery_required" type="button" class="btn btn-sm" :disabled="loading" @click="resumeRun(item)">从检查点继续这次整理</button>
        <button v-else-if="['failed', 'cancelled'].includes(item.status) || item.quality_status === 'failed'" type="button" class="btn btn-sm" @click="prepareRetry(item)">重新核对本次范围</button>
        <button v-if="item.targeted_completion?.status" type="button" class="btn btn-sm" @click="expanded = expanded === item.task_id ? '' : item.task_id">{{ item.targeted_completion.status === 'deferred' ? '继续这批查漏' : '查看查漏进度' }}</button>
        <TargetedCompletionPanel v-if="expanded === item.task_id" :project-id="projectId" :source-task-id="item.task_id" :initial-open="true" :defer-requested="item.defer_requested" @updated="load()" @applied="load()" />
      </template>
      <template v-else>
        <p>{{ cleanupOutcome(item) }}</p>
        <p>{{ assetSummaryText(item.asset_summary) }}</p>
        <button v-if="item.cleanup_status !== 'complete'" type="button" class="btn btn-sm" :disabled="cleanupBusy" data-action="preview-import-cleanup" @click="previewCleanup(item)">查看清理范围</button>
      </template>
    </article>
    <aside v-if="activeTab === 'recycle' && cleanupPreview" class="organization-cleanup-preview" aria-label="清理本次整理产生的内容">
      <strong>清理本次整理产生的内容</strong>
      <p>{{ assetSummaryText(cleanupPreview.asset_summary) }}</p>
      <p>只会把本次整理自动产生、且之后没有被作者编辑的内容移入历史；不会永久删除，其他整理和人工内容不受影响。</p>
      <p v-if="cleanupPreview.cleanup_status === 'partial'" role="status">部分内容受后续修改或引用保护，将继续保留。</p>
      <p v-if="cleanupError" role="alert">{{ cleanupError }}</p>
      <div class="organization-actions">
        <button type="button" class="btn btn-ghost" :disabled="cleanupBusy" @click="cleanupPreview = null">取消</button>
        <button v-if="cleanupPreview.cleanup_status !== 'complete'" type="button" class="btn btn-primary" :disabled="cleanupBusy || !cleanupPreview.cleanup_eligible" data-action="confirm-import-cleanup" @click="executeCleanup">{{ cleanupBusy ? '正在清理…' : '确认清理' }}</button>
      </div>
    </aside>
    <button v-if="selectedItems.length > 3" type="button" class="btn btn-sm" @click="historyExpanded = !historyExpanded">{{ historyExpanded ? '收起较早记录' : `查看本页其余 ${selectedItems.length - 3} 次整理` }}</button>
    <div v-if="activeTab === 'history' && total > 20" class="organization-actions">
      <button type="button" class="btn" :disabled="loading || skip === 0" @click="load(skip - 20)">上一页</button>
      <span>共 {{ total }} 次整理</span>
      <button type="button" class="btn" :disabled="loading || skip + 20 >= total" @click="load(skip + 20)">下一页</button>
    </div>
  </section>
</template>

<style scoped>
.organization-history{display:grid;gap:12px;margin-bottom:20px}.organization-history article,.organization-cleanup-preview{padding:12px;border:1px solid var(--border);border-radius:var(--radius-md)}.organization-history p{margin:6px 0;overflow-wrap:anywhere}.organization-history article>p{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.organization-actions,.organization-tabs{display:flex;gap:8px;flex-wrap:wrap}.organization-actions button,.organization-tabs button{min-height:44px}.organization-tabs button{padding:8px 14px;border:1px solid var(--border);border-radius:999px;background:var(--surface,#fff);color:var(--text-secondary);cursor:pointer}.organization-tabs button.active{border-color:var(--primary,#6366f1);background:var(--primary-soft,#eef2ff);color:var(--primary,#6366f1);font-weight:700}.organization-cleanup-preview{display:grid;gap:8px;background:var(--surface-soft,#f8fafc)}
</style>
