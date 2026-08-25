<script setup>
import { computed, ref, watch } from "vue"
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
import { validateRebuildRange } from "../useRagWorkflow.js"

/**
 * 索引维护页 — DOM 契约对齐 vanilla _renderStatus/_renderDiagnostics 等。
 * statusFields 为 RagView 注入的 reactive 状态；rebuildForm 为重建范围表单。
 */
const props = defineProps({
  statusFields: { type: Object, required: true },
  evidenceHealth: { type: Object, default: null },
  apiAvailable: { type: Boolean, default: false },
  maintenanceBusy: { type: Boolean, default: false },
})

const rebuildForm = defineModel("rebuildForm", { type: Object, required: true })

const emit = defineEmits([
  "rebuild",
  "prewarm",
  "retry-embeddings",
  "retry-task",
  "retry-status",
  "navigate-search",
])

const session = ragSearchSession
const fields = props.statusFields

function authorStatusText(value) {
  return String(value || "")
    .replaceAll("Scene", "场景")
    .replaceAll("context", "上下文")
    .replace(/embedding/gi, "语义匹配")
}

// ── 检索记录（vanilla _retrievalTraces*，重挂载即重置）──
const tracesState = ref("idle")
const traces = ref([])

async function loadRetrievalTraces() {
  if (tracesState.value === "loading") return
  tracesState.value = "loading"
  try {
    const projectId = getAppState()?.currentProjectId
    const result = await getApi().context.listRetrievalTraces(projectId, {
      content_mode: "canonical",
      limit: 20,
    })
    traces.value = Array.isArray(result) ? result : (result?.items || [])
    tracesState.value = "loaded"
  } catch {
    traces.value = []
    tracesState.value = "error"
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

const diagnosticsNeedAttention = computed(() => Boolean(
  fields.embeddingDimensionMismatch || session.prewarmWarning,
))
const diagnosticsOpen = ref(diagnosticsNeedAttention.value)
watch(
  diagnosticsNeedAttention,
  (value) => {
    if (value) diagnosticsOpen.value = true
  },
)

const health = computed(() => props.evidenceHealth)
const healthScene = computed(() => health.value?.scene_span_coverage || {})
const healthMapping = computed(() => health.value?.rag_mapping_coverage || {})
const healthRetrieval = computed(() => health.value?.retrieval_summary || {})
const healthReasons = computed(() => (
  Array.isArray(health.value?.health_reasons)
    ? authorStatusText(health.value.health_reasons.join("；"))
    : ""
))

const rebuildProgress = computed(() => session.rebuildProgress)
const rangeError = computed(() => validateRebuildRange(rebuildForm.value).error)
const rebuildButtonText = computed(() => (
  props.maintenanceBusy
    ? (rebuildProgress.value ? "修复进行中" : "正在启动…")
    : "修复查找功能"
))
const statusWarningText = computed(() => (
  authorStatusText((fields.statusWarnings || []).join("；")) || "部分资料暂时无法完整查找。"
))
const canRetryTask = computed(() => (
  Array.isArray(rebuildProgress.value?.availableActions)
  && rebuildProgress.value.availableActions.includes("retry")
))

const statusItems = computed(() => fields.statusItems || [])
</script>

<template>
  <section v-if="!apiAvailable && fields.totalChunks === null" class="empty-state rag-status-offline" role="alert">
    <h2>暂时无法连接查找服务</h2>
    <p class="rag-empty-copy">正文不受影响。请检查网络后重试，或先返回查找页。</p>
    <div class="actions">
      <button type="button" class="btn btn-primary" data-action="retry-rag-status" @click="emit('retry-status')">重新连接</button>
      <button type="button" class="btn" data-action="nav-search" @click="emit('navigate-search')">返回查找</button>
    </div>
  </section>

  <template v-else>
    <section class="card rag-repair-card">
      <div class="rag-repair-card__intro">
        <h2>{{ fields.statusDegraded || fields.totalChunks === 0 ? '查找资料尚未准备好' : '查找资料状态' }}</h2>
        <p>{{ fields.statusDegraded ? '部分资料可能暂时找不到。修复期间仍可继续手写正文。' : '如果查找结果不全，可以重新整理当前作品的可查找资料。' }}</p>
      </div>
      <form class="rag-rebuild-form" novalidate @submit.prevent="emit('rebuild')">
        <div class="rag-rebuild-fields" aria-labelledby="rag-rebuild-range-title">
          <h3 id="rag-rebuild-range-title">修复范围</h3>
          <label class="rag-rebuild-field" for="rag-rebuild-content-mode">
            <span>使用哪一版正文</span>
            <select class="form-input" id="rag-rebuild-content-mode" v-model="rebuildForm.contentMode" :disabled="maintenanceBusy">
              <option value="canonical">已发布正文</option>
              <option value="working">工作稿</option>
            </select>
          </label>
          <div class="rag-rebuild-range">
            <label class="rag-rebuild-field" for="rag-rebuild-start">
              <span>从第几章</span>
              <input
                class="form-input"
                id="rag-rebuild-start"
                type="number"
                min="1"
                inputmode="numeric"
                placeholder="全部"
                v-model="rebuildForm.start"
                :disabled="maintenanceBusy"
                :aria-invalid="rangeError ? 'true' : undefined"
                :aria-describedby="rangeError ? 'rag-rebuild-range-help rag-rebuild-range-error' : 'rag-rebuild-range-help'"
              />
            </label>
            <label class="rag-rebuild-field" for="rag-rebuild-end">
              <span>到第几章</span>
              <input
                class="form-input"
                id="rag-rebuild-end"
                type="number"
                min="1"
                inputmode="numeric"
                placeholder="全部"
                v-model="rebuildForm.end"
                :disabled="maintenanceBusy"
                :aria-invalid="rangeError ? 'true' : undefined"
                :aria-describedby="rangeError ? 'rag-rebuild-range-help rag-rebuild-range-error' : 'rag-rebuild-range-help'"
              />
            </label>
          </div>
          <p id="rag-rebuild-range-help" class="rag-rebuild-hint">两项都留空会整理全部章节；只整理一段时，请同时填写起止章节。</p>
          <p v-if="rangeError" id="rag-rebuild-range-error" class="rag-rebuild-error" role="alert">{{ rangeError }}</p>
        </div>
        <div class="rag-repair-card__actions">
          <button class="btn btn-primary" type="submit" data-action="rebuild-index" :disabled="maintenanceBusy || Boolean(rangeError)">{{ rebuildButtonText }}</button>
          <button class="btn" type="button" data-action="nav-search" @click="emit('navigate-search')">返回查找</button>
        </div>
      </form>
    </section>

    <div class="rag-status-stack">
      <div id="rag-rebuild-progress">
        <WorkflowProgressCard
          v-if="rebuildProgress"
          :progress="rebuildProgress"
          variant="card"
          title="正在修复查找功能"
        >
          <div class="workflow-progress__destination">完成后本页会自动更新，可以直接返回查找。</div>
          <div v-if="canRetryTask" class="workflow-progress__actions">
            <button type="button" class="btn btn-sm" data-action="retry-task" :data-task-id="rebuildProgress.taskId || ''" :disabled="session.taskRetryPending" @click="emit('retry-task')">{{ session.taskRetryPending ? "重试中..." : "重试任务" }}</button>
          </div>
        </WorkflowProgressCard>
        <div v-else-if="session.rebuildInfo" class="rag-status-message" role="status">
          <p>{{ session.rebuildInfo }}</p>
        </div>
      </div>

      <div v-if="fields.statusDegraded" class="rag-status-message rag-status-message--warning" role="status">
        <strong>部分资料暂时找不到</strong>
        <p>{{ statusWarningText }}</p>
      </div>

      <div v-if="fields.totalChunks === 0" class="rag-status-message" role="status">
        <strong>还没有可查找资料</strong>
        <p>导入或写入正文后，可以在上方选择正文版本并开始修复。</p>
      </div>

      <div class="rag-status-overview">
        <section class="card rag-status-card">
        <div class="card-title">查找资料概览</div>
        <div class="rag-status-metrics">
          <div class="rag-status-metric">
            <strong class="rag-status-value"><span class="badge" :class="statusBadgeOk ? 'badge-canonical' : 'badge-draft'">{{ statusBadgeOk ? "正常" : "未连接" }}</span></strong><br>
            <span class="rag-status-label">查找功能</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ countDisplay }}</strong><br>
            <span class="rag-status-label">可查找片段</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(fields.embeddingFailedCount) }}</strong><br>
            <span class="rag-status-label">待完善片段</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ canonicalFreshness.fresh ?? 0 }}/{{ canonicalFreshness.total ?? 0 }}</strong><br>
            <span class="rag-status-label">已发布正文</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ workingFreshness.fresh ?? 0 }}/{{ workingFreshness.total ?? 0 }}</strong><br>
            <span class="rag-status-label">工作稿已准备</span>
          </div>
        </div>
        </section>

        <section v-if="health" class="card rag-status-card" :class="{ 'rag-status-warning-card': health.health_state === 'degraded' }">
        <div class="card-title">查找质量</div>
        <div class="rag-status-metrics">
          <div class="rag-status-metric">
            <strong class="rag-status-value rag-status-value--state">{{ EVIDENCE_HEALTH_LABELS[health.health_state] || health.health_state }}</strong><br>
            <span class="rag-status-label">近期状态</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ percentText(healthScene.precise_span_rate) }}</strong><br>
            <span class="rag-status-label">可精确定位场景</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ percentText(healthMapping.eligible_mapping_rate) }}</strong><br>
            <span class="rag-status-label">应收录片段</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(healthRetrieval.query_count ?? 0) }}</strong><br>
            <span class="rag-status-label">近期查找</span>
          </div>
          <div class="rag-status-metric">
            <strong class="rag-status-value">{{ String(healthRetrieval.empty_count ?? 0) }}</strong><br>
            <span class="rag-status-label">未找到资料</span>
          </div>
        </div>
        <p v-if="healthReasons" class="rag-empty-copy">原因：{{ healthReasons }}</p>
        <p v-if="health.health_state === 'degraded'" class="rag-empty-copy" data-author-action="can_improve">
          这表示当前查找证据还不完整，不代表作品内容有错，也不会阻止手写正文。
        </p>
        </section>
      </div>
    </div>

    <details class="rag-diagnostic-details" :open="diagnosticsOpen" @toggle="diagnosticsOpen = $event.target.open">
      <summary>诊断详情</summary>
      <div class="rag-diagnostic-stack">
      <div id="rag-diagnostics">
        <section class="rag-diagnostic-section rag-diagnostics-card" aria-labelledby="rag-technical-title">
          <h3 id="rag-technical-title">技术信息</h3>
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
          <p v-if="session.prewarmWarning" class="rag-diagnostics-warning">{{ authorStatusText(session.prewarmWarning) }}</p>
          <div class="rag-retrieval-traces">
            <button type="button" class="btn btn-sm" data-action="load-retrieval-traces" :disabled="tracesState === 'loading'" @click="loadRetrievalTraces">{{ tracesButtonText }}</button>
            <p v-if="tracesState === 'loading'" class="rag-empty-copy">正在加载隐私安全的检索摘要…</p>
            <p v-else-if="tracesState === 'error'" class="rag-diagnostics-warning">近期检索记录暂时无法读取，请稍后重试。</p>
            <p v-else-if="tracesState === 'loaded' && !traces.length" class="rag-empty-copy">暂无近期检索记录。</p>
            <div v-else-if="tracesState === 'loaded'" class="rag-retrieval-trace-list" aria-label="近期检索记录">
              <article v-for="(trace, index) in traces" :key="index" class="rag-retrieval-trace">
                <div><strong>{{ trace.retrieval_purpose || trace.consumer_action || "检索记录" }}</strong> · {{ trace.content_mode === "canonical" ? "已发布" : trace.content_mode === "working" ? "工作稿" : "未标注版本" }} · {{ traceTimeText(trace) }}</div>
                <div class="rag-empty-copy">候选 {{ trace.candidate_count ?? 0 }} · 去重 {{ trace.unique_count ?? 0 }} · 回读 {{ trace.hydrated_count ?? 0 }} · 丢弃 {{ traceDroppedCount(trace) }}</div>
                <div v-if="trace.safe_empty_reason" class="rag-diagnostics-warning">空证据原因：{{ trace.safe_empty_reason }}</div>
                <div v-if="(trace.warning_codes || []).length" class="rag-diagnostics-warning">警告：{{ trace.warning_codes.join("、") }}</div>
              </article>
            </div>
          </div>
        </section>
      </div>

      <section class="rag-diagnostic-section rag-maintenance-tools" aria-labelledby="rag-maintenance-title">
        <div>
          <h3 id="rag-maintenance-title">维护工具</h3>
          <p>只有查找功能持续异常时才需要使用。</p>
        </div>
        <div class="rag-maintenance-tools__actions">
          <button type="button" class="btn btn-sm" data-action="prewarm-rag" :disabled="session.prewarmState === 'running'" @click="emit('prewarm')">{{ session.prewarmState === "running" ? "正在重新连接…" : "重新连接查找功能" }}</button>
          <button v-if="fields.retryableEmbeddingCount > 0" type="button" class="btn btn-sm" data-action="retry-embeddings" :disabled="maintenanceBusy" @click="emit('retry-embeddings')">重试 {{ fields.retryableEmbeddingCount }} 个未完成片段</button>
        </div>
      </section>

      <section class="rag-diagnostic-section rag-chunk-list-card" aria-labelledby="rag-chunk-list-title">
        <h3 id="rag-chunk-list-title">最近片段</h3>
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
      </section>
      </div>
    </details>
  </template>
</template>
