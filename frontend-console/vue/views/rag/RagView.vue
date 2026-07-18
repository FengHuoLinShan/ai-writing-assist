<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue"
import RagSearchView from "./RagSearchView.vue"
import RagStatusPanel from "./components/RagStatusPanel.vue"
import { getApi, getRouter, useStateKey } from "../../bridge/index.js"
import { useRagWorkflow } from "./useRagWorkflow.js"
import { ensurePrewarm } from "./prewarmManager.js"
import { ragSearchSession } from "./ragSearchSession.js"

/**
 * 小说检索根组件 — header（子标签导航 + 状态页操作）+ search/status 分支。
 * 数据由 island load() 预取传入（对应 vanilla onEnter）。
 */
const props = defineProps({
  projectId: { type: String, default: null },
  apiAvailable: { type: Boolean, default: false },
  status: { type: Object, default: null },
  evidenceHealth: { type: Object, default: null },
  characters: { type: Array, default: () => [] },
  scenes: { type: Array, default: () => [] },
})

const currentSubView = useStateKey("currentSubView")
const subView = computed(() => currentSubView.value || "search")

const statusFields = reactive({
  totalChunks: null,
  embeddingFailedCount: 0,
  retryableEmbeddingCount: 0,
  statusWarnings: [],
  statusDegraded: false,
  embeddingDim: null,
  configuredEmbeddingDim: null,
  indexedEmbeddingDim: null,
  embeddingDimensionMismatch: false,
  embeddingRuntime: { started: false, healthy: false, cache_stats: {} },
  metrics: null,
  statusItems: [],
  indexFreshness: {},
})

/** 对应 vanilla _applyStatus。 */
function applyStatus(data = {}) {
  statusFields.totalChunks = data.total || 0
  statusFields.embeddingFailedCount = data.embedding_failed_count || 0
  statusFields.embeddingDim = data.embedding_dim ?? null
  statusFields.configuredEmbeddingDim = data.configured_embedding_dim ?? null
  statusFields.indexedEmbeddingDim = data.indexed_embedding_dim ?? null
  statusFields.embeddingDimensionMismatch = Boolean(data.embedding_dimension_mismatch)
  statusFields.embeddingRuntime = data.embedding_runtime || { started: false, healthy: false, cache_stats: {} }
  statusFields.retryableEmbeddingCount = data.retryable_embedding_count || 0
  statusFields.statusWarnings = data.warnings || []
  statusFields.statusDegraded = Boolean(data.degraded)
  statusFields.statusItems = data.items || []
  statusFields.indexFreshness = data.index_freshness?.by_content_mode || {}
}

if (props.status) applyStatus(props.status)
const apiAvailable = ref(props.apiAvailable)

/** 对应 vanilla _refreshStatusFromServer（失败保持现有显示）。 */
async function refreshStatus() {
  if (!props.projectId) return
  try {
    const data = await getApi().rag.status(props.projectId)
    applyStatus(data)
    apiAvailable.value = true
  } catch {
    // 状态刷新失败不影响已展示内容
  }
}

const workflow = useRagWorkflow({ statusFields, refreshStatus })

// 预热结果回写（对应 vanilla _prewarm 的 _embeddingDim/_embeddingRuntime 更新）：
// 请求由 prewarmManager 模块级管理（island load 触发/手动按钮强制），
// 完成可能晚于组件挂载，故初始应用一次并持续监听。
function applyPrewarmResult(result) {
  if (!result) return
  if (result.embedding_dim != null) statusFields.embeddingDim = result.embedding_dim
  statusFields.embeddingRuntime = {
    ...(statusFields.embeddingRuntime || {}),
    ...result.embedding_runtime,
  }
}
applyPrewarmResult(ragSearchSession.prewarmResult)
watch(() => ragSearchSession.prewarmResult, applyPrewarmResult)

/** 手动"预热检索引擎"按钮（vanilla 无条件发起）。 */
function manualPrewarm() {
  void ensurePrewarm({ force: true })
}

const rebuildForm = reactive({ contentMode: "canonical", start: "", end: "" })

function navigateSub(sub) {
  getRouter().navigate("rag", sub)
}

onMounted(async () => {
  // vanilla _refreshMetrics（后台，不阻塞首屏）
  if (getApi().rag.metrics) {
    try {
      const data = await getApi().rag.metrics()
      statusFields.metrics = data.metrics || null
      if (data.embedding_runtime) statusFields.embeddingRuntime = data.embedding_runtime
    } catch {
      // 诊断数据失败不影响状态页
    }
  }
  // vanilla onEnter 末尾的工作流恢复（后台预热已上移到 island load）
  workflow.recoverRebuildWorkflow()
})
</script>

<template>
  <div class="view-header view-header--with-tabs">
    <div class="subnav">
      <span class="subnav-item" :class="{ active: subView === 'search' }" data-action="nav-search" @click="navigateSub('search')">检索</span>
      <span class="subnav-item" :class="{ active: subView === 'status' }" data-action="nav-status" @click="navigateSub('status')">索引维护</span>
    </div>
    <div class="view-header__actions">
      <template v-if="subView === 'status'">
        <button class="btn btn-sm" data-action="rebuild-index" @click="workflow.rebuildIndex(rebuildForm)">重建索引</button>
        <button class="btn btn-sm" data-action="prewarm-rag" @click="manualPrewarm">预热检索引擎</button>
        <button v-if="statusFields.retryableEmbeddingCount > 0" class="btn btn-sm" data-action="retry-embeddings" @click="workflow.retryEmbeddings()">重试失败向量</button>
      </template>
    </div>
  </div>

  <RagSearchView
    v-if="subView === 'search'"
    :project-id="props.projectId"
    :characters="props.characters"
    :scenes="props.scenes"
  />
  <RagStatusPanel
    v-else
    :status-fields="statusFields"
    :evidence-health="props.evidenceHealth"
    :api-available="apiAvailable"
    v-model:rebuild-form="rebuildForm"
    @rebuild="workflow.rebuildIndex(rebuildForm)"
    @prewarm="manualPrewarm"
    @retry-embeddings="workflow.retryEmbeddings()"
    @retry-task="workflow.retryFailedTask()"
    @navigate-search="navigateSub('search')"
  />
</template>
