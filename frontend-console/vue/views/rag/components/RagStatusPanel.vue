<script setup>
import { computed, ref } from "vue"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"
import { getApi, getAppState } from "../../../bridge/index.js"
import {
  EVIDENCE_HEALTH_LABELS,
  cacheText,
  chunkPreview,
  percentText,
  runtimeLabel,
  traceDroppedCount,
  traceTimeText,
} from "../logic/statusView.js"
import { ragSearchSession } from "../ragSearchSession.js"

/**
 * 索引维护页 — DOM 契约对齐 vanilla _renderStatus/_renderDiagnostics 等。
 * statusFields 为 RagView 注入的 reactive 状态；rebuildForm 为重建范围表单。
 */
const props = defineProps({
  statusFields: { type: Object, required: true },
  evidenceHealth: { type: Object, default: null },
  apiAvailable: { type: Boolean, default: false },
})

const rebuildForm = defineModel("rebuildForm", { type: Object, required: true })

const emit = defineEmits([
  "rebuild",
  "prewarm",
  "retry-embeddings",
  "retry-task",
  "navigate-search",
])

const session = ragSearchSession
const fields = props.statusFields

// ── 检索记录（vanilla _retrievalTraces*，重挂载即重置）──
const tracesState = ref("idle")
const traces = ref([])
const tracesError = ref("")

async function loadRetrievalTraces() {
  if (tracesState.value === "loading") return
  tracesState.value = "loading"
  tracesError.value = ""
  try {
    const projectId = getAppState()?.currentProjectId
    const result = await getApi().context.listRetrievalTraces(projectId, {
      content_mode: "canonical",
      limit: 20,
    })
    traces.value = Array.isArray(result) ? result : (result?.items || [])
    tracesState.value = "loaded"
  } catch (err) {
    traces.value = []
    tracesState.value = "error"
    tracesError.value = err.message || "未知错误"
  }
}

const tracesButtonText = computed(() => (
  tracesState.value === "loading"
    ? "加载中..."
    : tracesState.value === "loaded"
      ? "刷新近期检索记录"
      : "查看近期检索记录"
))

const statusBadgeOk = computed(() => props.apiAvailable)
const countDisplay = computed(() => (fields.totalChunks !== null ? String(fields.totalChunks) : "-"))
const canonicalFreshness = computed(() => fields.indexFreshness?.canonical || {})
const workingFreshness = computed(() => fields.indexFreshness?.working || {})

const workerLabel = computed(() => runtimeLabel(session.prewarmState, fields.embeddingRuntime))
const actualDim = computed(() => fields.indexedEmbeddingDim ?? fields.embeddingDim ?? "-")
const configuredDim = computed(() => fields.configuredEmbeddingDim ?? "-")
const avgLatency = computed(() => (fields.metrics?.avg_latency_ms != null ? `${fields.metrics.avg_latency_ms}ms` : "-"))
const embeddingAvg = computed(() => (fields.metrics?.embedding_avg_ms != null ? `${fields.metrics.embedding_avg_ms}ms` : "-"))
const degradedRate = computed(() => (fields.metrics?.degraded_rate != null ? percentText(fields.metrics.degraded_rate) : "-"))
const cacheStatsText = computed(() => cacheText(fields.embeddingRuntime?.cache_stats))

// vanilla：维度漂移或预热警告时诊断默认展开（渲染期计算一次）
const diagnosticsOpen = ref(Boolean(fields.embeddingDimensionMismatch || session.prewarmWarning))

const health = computed(() => props.evidenceHealth)
const healthScene = computed(() => health.value?.scene_span_coverage || {})
const healthMapping = computed(() => health.value?.rag_mapping_coverage || {})
const healthRetrieval = computed(() => health.value?.retrieval_summary || {})
const healthReasons = computed(() => (
  Array.isArray(health.value?.health_reasons) ? health.value.health_reasons.join("；") : ""
))

const rebuildProgress = computed(() => session.rebuildProgress)
const canRetryTask = computed(() => (
  Array.isArray(rebuildProgress.value?.availableActions)
  && rebuildProgress.value.availableActions.includes("retry")
))

const statusItems = computed(() => fields.statusItems || [])
</script>

<template>
  <div v-if="!apiAvailable && fields.totalChunks === null" class="empty-state">
    <div class="empty-icon">&#128269;</div>
    <p>与服务器连接断开</p>
    <p class="rag-empty-copy">请检查网络或刷新页面，后端服务可能尚未启动。</p>
  </div>

  <template v-else>
    <div class="rag-status-stack">
      <div class="card rag-status-card">
        <div class="card-title">小说检索索引概览</div>
        <div class="rag-status-metrics">
          <div class="rag-status-metric">
            <strong class="rag-status-value"><span class="badge" :class="statusBadgeOk ? 'badge-canonical' : 'badge-draft'">{{ statusBadgeOk ? "正常" : "未连接" }}</span></strong><br>
            <span class="rag-status-label">索引是否可用</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ countDisplay }}</strong><br>
            <span class="rag-status-label">已索引章节片段</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(fields.embeddingFailedCount) }}</strong><br>
            <span class="rag-status-label">降级片段</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ canonicalFreshness.fresh ?? 0 }}/{{ canonicalFreshness.total ?? 0 }}</strong><br>
            <span class="rag-status-label">已发布索引新鲜度</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ workingFreshness.fresh ?? 0 }}/{{ workingFreshness.total ?? 0 }}</strong><br>
            <span class="rag-status-label">工作稿索引新鲜度</span>
          </div>
        </div>
      </div>

      <div v-if="health" class="card rag-status-card" :class="{ 'rag-status-warning-card': health.health_state === 'degraded' }">
        <div class="card-title">创作证据健康</div>
        <div class="rag-status-metrics">
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ EVIDENCE_HEALTH_LABELS[health.health_state] || health.health_state }}</strong><br>
            <span class="rag-status-label">24 小时健康状态</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ percentText(healthScene.precise_span_rate) }}</strong><br>
            <span class="rag-status-label">Scene 精确定位</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ percentText(healthMapping.eligible_mapping_rate) }}</strong><br>
            <span class="rag-status-label">应映射片段覆盖</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(healthRetrieval.query_count ?? 0) }}</strong><br>
            <span class="rag-status-label">近期 context 检索</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(healthRetrieval.empty_count ?? 0) }}</strong><br>
            <span class="rag-status-label">空证据运行</span>
          </div>
        </div>
        <p v-if="healthReasons" class="rag-empty-copy">原因：{{ healthReasons }}</p>
      </div>

      <div id="rag-diagnostics">
        <details class="card rag-diagnostics-card" :open="diagnosticsOpen" @toggle="diagnosticsOpen = $event.target.open">
          <summary class="card-title">技术诊断详情</summary>
          <div class="rag-diagnostics-grid">
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ String(actualDim) }}</strong><br><span class="rag-diagnostics-label">实际维度</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ String(configuredDim) }}</strong><br><span class="rag-diagnostics-label">配置维度</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ workerLabel }}</strong><br><span class="rag-diagnostics-label">worker</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ avgLatency }}</strong><br><span class="rag-diagnostics-label">平均检索</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ embeddingAvg }}</strong><br><span class="rag-diagnostics-label">embedding</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ degradedRate }}</strong><br><span class="rag-diagnostics-label">降级率</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ String(fields.retryableEmbeddingCount || 0) }}</strong><br><span class="rag-diagnostics-label">可重试</span></div>
            <div class="rag-status-metric"><strong class="rag-diagnostics-value">{{ cacheStatsText }}</strong><br><span class="rag-diagnostics-label">缓存命中/未命中</span></div>
          </div>
          <p v-if="fields.embeddingDimensionMismatch" class="rag-diagnostics-warning">向量维度配置漂移，请同步配置后重启后端。</p>
          <p v-if="session.prewarmWarning" class="rag-diagnostics-warning">{{ session.prewarmWarning }}</p>
          <div class="rag-retrieval-traces">
            <button class="btn btn-sm" data-action="load-retrieval-traces" :disabled="tracesState === 'loading'" @click="loadRetrievalTraces">{{ tracesButtonText }}</button>
            <p v-if="tracesState === 'loading'" class="rag-empty-copy">正在加载隐私安全的检索摘要…</p>
            <p v-else-if="tracesState === 'error'" class="rag-diagnostics-warning">检索记录加载失败：{{ tracesError || "未知错误" }}</p>
            <p v-else-if="tracesState === 'loaded' && !traces.length" class="rag-empty-copy">暂无近期检索记录。</p>
            <div v-else-if="tracesState === 'loaded'" class="rag-retrieval-trace-list" aria-label="近期检索记录">
              <article v-for="(trace, index) in traces" :key="index" class="rag-retrieval-trace">
                <div><strong>{{ trace.retrieval_purpose || trace.consumer_action || "context" }}</strong> · {{ trace.content_mode || "-" }} · {{ traceTimeText(trace) }}</div>
                <div class="rag-empty-copy">候选 {{ trace.candidate_count ?? 0 }} · 去重 {{ trace.unique_count ?? 0 }} · 回读 {{ trace.hydrated_count ?? 0 }} · 丢弃 {{ traceDroppedCount(trace) }}</div>
                <div v-if="trace.safe_empty_reason" class="rag-diagnostics-warning">空证据原因：{{ trace.safe_empty_reason }}</div>
                <div v-if="(trace.warning_codes || []).length" class="rag-diagnostics-warning">警告：{{ trace.warning_codes.join("、") }}</div>
              </article>
            </div>
          </div>
        </details>
      </div>

      <div v-if="fields.statusDegraded" class="card rag-status-card rag-status-warning-card">
        <div class="card-title rag-status-warning-title">索引不完整</div>
        <p class="rag-empty-copy">{{ (fields.statusWarnings || []).join("；") || "部分索引已降级，抽取结果可能不准确。" }}</p>
      </div>

      <div v-if="fields.totalChunks === 0" class="empty-state">
        <div class="empty-icon">&#128194;</div>
        <p>还没有检索数据</p>
        <p class="rag-empty-copy">导入正文后，系统会自动分析内容并建立检索索引。</p>
      </div>

      <div id="rag-rebuild-progress">
        <WorkflowProgressCard
          v-if="rebuildProgress"
          :progress="rebuildProgress"
          variant="card"
          title="重建 RAG 索引"
        >
          <div class="workflow-progress__destination">完成后本页索引概览会更新，可继续测试搜索。</div>
          <div v-if="canRetryTask" class="workflow-progress__actions">
            <button class="btn btn-sm" data-action="retry-task" :data-task-id="rebuildProgress.taskId || ''" :disabled="session.taskRetryPending" @click="emit('retry-task')">{{ session.taskRetryPending ? "重试中..." : "重试任务" }}</button>
          </div>
        </WorkflowProgressCard>
        <div v-else-if="session.rebuildInfo" class="empty-state">
          <p class="rag-empty-copy">{{ session.rebuildInfo }}</p>
        </div>
      </div>

      <div class="card rag-chunk-list-card">
        <div class="card-title">最近片段</div>
        <p v-if="statusItems.length === 0" class="rag-empty-copy">暂无片段数据</p>
        <div v-else class="rag-chunk-table-wrap">
          <table class="data-table rag-chunk-table">
            <thead>
              <tr>
                <th>片段</th>
                <th>章节</th>
                <th>字数</th>
                <th>状态</th>
                <th>实体</th>
                <th>人物</th>
                <th>线索</th>
                <th>场景</th>
                <th>预览</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in statusItems" :key="index">
                <td>{{ String(item.chunk_index ?? "-") }}</td>
                <td>{{ String(item.chapter_index ?? "-") }}</td>
                <td>{{ String(item.char_count ?? "-") }}</td>
                <td>{{ item.embedding_status || "-" }}</td>
                <td>{{ (item.entity_ids || []).length }}</td>
                <td>{{ (item.character_ids || []).length }}</td>
                <td>{{ (item.thread_ids || []).length }}</td>
                <td>{{ item.scene_id ? 1 : 0 }}</td>
                <td class="rag-chunk-preview" :title="item.text || item.summary || ''">{{ chunkPreview(item.text || item.summary || "") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="rag-rebuild-form">
      <div class="rag-rebuild-range">
        <label for="rag-rebuild-content-mode">正文版本</label>
        <select class="form-input rag-rebuild-input" id="rag-rebuild-content-mode" v-model="rebuildForm.contentMode">
          <option value="canonical">已发布</option>
          <option value="working">工作稿</option>
        </select>
        <label for="rag-rebuild-start">起始章节</label>
        <input class="form-input rag-rebuild-input" id="rag-rebuild-start" type="number" min="1" placeholder="起始" v-model="rebuildForm.start" />
        <label for="rag-rebuild-end">结束章节</label>
        <input class="form-input rag-rebuild-input" id="rag-rebuild-end" type="number" min="1" placeholder="结束" v-model="rebuildForm.end" />
      </div>
      <button class="btn" data-action="nav-search" @click="emit('navigate-search')">返回检索</button>
    </div>
  </template>
</template>
