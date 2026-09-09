<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getApi, getAppState, getRouter } from '../bridge/index.js'
import TargetedCompletionPanel from './TargetedCompletionPanel.vue'
const emit = defineEmits(['prepare'])
const props = defineProps({ projectId: { type: String, required: true } })
const historyExpanded = ref(false), assetCounts = ref(null)
const items = ref([]), total = ref(0), skip = ref(0), loading = ref(false), error = ref(''), expanded = ref('')
const visibleItems = computed(() => historyExpanded.value ? items.value : items.value.slice(0, 3))
let alive = true, epoch = 0, timer
const labels = { deep_import: '完整整理', scene_auto_extraction: '场景整理', world_object_auto_extraction: '世界资料整理', plot_structure_auto_extraction: '剧情结构整理', targeted_completion: '专项查漏' }
async function load(offset = skip.value) {
  const token = ++epoch
  loading.value = true; error.value = ''; clearTimeout(timer)
  try {
    const result = await getApi().imports.recentWorkflows(props.projectId, offset)
    if (!alive || token !== epoch || getAppState()?.currentProjectId !== props.projectId) return
    items.value = result.items; total.value = result.total; skip.value = offset
    if (items.value.some(item => ['pending', 'running'].includes(item.status))) timer = setTimeout(() => load(), 4000)
  } catch (err) { if (alive && token === epoch) error.value = err.message || '整理记录读取失败' }
  finally { if (alive && token === epoch) loading.value = false }
}
async function resumeRun(item) {
  loading.value = true; error.value = ''
  try { await getApi().imports.resumeDeepImport(item.task_id); await load() }
  catch (err) { error.value = err.message || '继续整理失败，原成果保留' }
  finally { loading.value = false }
}
function prepareRetry(item, selectedStage = null) {
  const stage = selectedStage || { deep_import: 'deep', scene_auto_extraction: 'scenes', world_object_auto_extraction: 'world_objects', plot_structure_auto_extraction: 'plot_structure' }[item.workflow_type]
  if (stage) emit('prepare', { stage, start: item.start_chapter, end: item.end_chapter })
}
function outcome(item) {
  if (['pending', 'running'].includes(item.status)) return '正在整理，可离开后继续查看'
  if (item.status === 'cancelled') return '已停止，已完成的成果保留。'
  if (item.workflow_type === 'plot_structure_auto_extraction' && item.failed_stages?.includes('plot_structure') && !(item.asset_summary?.adopted || item.asset_summary?.review)) return '本次未得到可用结构；已有资料保留，可重新核对本阶段。'
  if (item.status === 'failed' || item.quality_status === 'failed') return '本次未完成，请核对原因或从检查点继续。'
  return item.message || '查看本次成果'
}
async function loadCounts() {
  const api = getApi(), projectId = props.projectId
  const responses = await Promise.allSettled([
    api.world.listEntities({ novel_id: projectId, display_state: 'active', skip: 0, limit: 1 }),
    api.outline.listThreads(projectId, { status: 'canonical', skip: 0, limit: 1 }),
    api.outline.listArcs(projectId, { status: 'canonical', skip: 0, limit: 1 }),
  ])
  if (alive && getAppState()?.currentProjectId === projectId) assetCounts.value = responses.map(result => result.status === 'fulfilled' && Number.isFinite(result.value?.total) ? result.value.total : '—')
}
function openResults(kind) {
  const view = kind === 'world' ? 'world' : 'outline'
  getRouter()?.navigate(view, kind === 'world' ? 'review' : 'threads')
}
onMounted(() => { void load(0); void loadCounts() })
onBeforeUnmount(() => { alive = false; epoch += 1; clearTimeout(timer) })
</script>
<template>
  <section class="organization-history" aria-label="项目整理进度">
    <h4>已有成果与最近整理</h4>
    <p>先使用基础成果；可选查漏由你决定何时继续。</p><p v-if="assetCounts">当前已采用：{{ assetCounts[0] }} 张资料卡 · {{ assetCounts[1] }} 条剧情线 · {{ assetCounts[2] }} 个篇章</p>
    <div class="organization-actions"><button class="btn btn-sm" type="button" @click="openResults('world')">审阅世界资料</button><button class="btn btn-sm" type="button" @click="openResults('outline')">查看剧情结构</button><button class="btn btn-sm" type="button" :disabled="loading" @click="load()">刷新进度</button></div>
    <p v-if="error" role="alert">{{ error }}</p><p v-else-if="loading && !items.length" role="status">正在读取整理记录…</p><p v-else-if="!items.length">还没有整理记录，可从下方开始。</p>
    <article v-for="item in visibleItems" :key="item.task_id">
      <strong>{{ labels[item.workflow_type] || '资料整理' }} · 第 {{ item.start_chapter }}—{{ item.end_chapter }} 章</strong>
      <p>{{ outcome(item) }}</p>
      <p>结束时记录：采用 {{ item.asset_summary?.adopted || 0 }} · 待审 {{ item.asset_summary?.review || 0 }} · 未采用 {{ item.asset_summary?.not_adopted || 0 }}</p>
      <button v-for="stage in item.failed_stages || []" :key="stage" type="button" class="btn btn-sm" @click="prepareRetry(item, stage)">重新核对{{ { scenes: '场景', world_objects: '世界资料', plot_structure: '剧情结构' }[stage] }}</button>
      <button v-if="item.recovery_required" type="button" class="btn btn-sm" :disabled="loading" @click="resumeRun(item)">从检查点继续这次整理</button>
      <button v-else-if="['failed', 'cancelled'].includes(item.status) || item.quality_status === 'failed'" type="button" class="btn btn-sm" @click="prepareRetry(item)">重新核对本次范围</button>
      <button v-if="item.targeted_completion?.status" type="button" class="btn btn-sm" @click="expanded = expanded === item.task_id ? '' : item.task_id">{{ item.targeted_completion.status === 'deferred' ? '继续这批查漏' : '查看查漏进度' }}</button>
      <TargetedCompletionPanel v-if="expanded === item.task_id" :project-id="projectId" :source-task-id="item.task_id" :initial-open="true" :defer-requested="item.defer_requested" @updated="load()" @applied="load()" />
    </article>
    <button v-if="items.length > 3" type="button" class="btn btn-sm" @click="historyExpanded = !historyExpanded">{{ historyExpanded ? '收起较早记录' : `查看本页其余 ${items.length - 3} 次整理` }}</button>
    <div v-if="total > 20" class="organization-actions"><button type="button" class="btn" :disabled="loading || skip === 0" @click="load(skip - 20)">上一页</button><span>共 {{ total }} 次整理</span><button type="button" class="btn" :disabled="loading || skip + 20 >= total" @click="load(skip + 20)">下一页</button></div>
  </section>
</template>
<style scoped>
.organization-history{display:grid;gap:12px;margin-bottom:20px}.organization-history article{padding:12px;border:1px solid var(--border);border-radius:var(--radius-md)}.organization-history p{margin:6px 0;overflow-wrap:anywhere}.organization-history article>p{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.organization-actions{display:flex;gap:8px;flex-wrap:wrap}.organization-actions button{min-height:44px}
</style>
