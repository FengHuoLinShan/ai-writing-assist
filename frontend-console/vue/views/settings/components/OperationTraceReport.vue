<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getAppState } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, default: null },
})

const PERIODS = [
  { value: "30d", label: "近 30 天" },
  { value: "90d", label: "近 90 天" },
  { value: "180d", label: "近 180 天" },
  { value: "all", label: "全部可用记录" },
]
const EVENT_GROUPS = [
  { value: "all", label: "全部事件" },
  { value: "author", label: "作者决定" },
  { value: "execution", label: "执行与恢复" },
  { value: "other", label: "提议与预览" },
]
const EVENT_LABELS = {
  proposed: "提议",
  previewed: "预览",
  confirmed: "作者接受",
  declined: "作者拒绝",
  edited: "作者修改",
  executed: "执行完成",
  failed: "执行失败",
  restored: "恢复",
  undone: "撤销",
  outcome_unknown: "结果未知",
}
const FIELD_LABELS = {
  title: "标题",
  name: "名称",
  content: "内容",
  category: "类别",
  status: "状态",
  target_id: "目标",
  entity_id: "对象",
  scene_id: "场景",
  chapter_index: "章节",
}
const TYPE_LABELS = {
  string: "文本",
  number: "数字",
  integer: "整数",
  boolean: "开关",
  array: "列表",
  object: "资料",
}
const PERIOD_LABELS = Object.fromEntries(PERIODS.map(({ value, label }) => [value, label]))

const period = ref("30d")
const eventGroup = ref("all")
const report = ref(null)
const loading = ref(false)
const loadError = ref("")
const exporting = ref(false)
const exportMessage = ref("")
const exportError = ref("")
let disposed = false
let loadGeneration = 0
let exportGeneration = 0
let loadController = null
let exportController = null

const filteredEvents = computed(() => (
  (report.value?.events || []).filter((row) => {
    if (eventGroup.value === "author") return ["confirmed", "declined", "edited"].includes(row.event)
    if (eventGroup.value === "execution") return ["executed", "failed", "restored", "undone", "outcome_unknown"].includes(row.event)
    if (eventGroup.value === "other") return ["proposed", "previewed"].includes(row.event)
    return true
  })
))

const totalEvents = computed(() => (
  (report.value?.events || []).reduce((total, row) => total + Number(row.count || 0), 0)
))

function isCurrentProject(projectId) {
  const state = getAppState()
  return !disposed
    && Boolean(projectId)
    && props.projectId === projectId
    && (!state || (
      state.currentProjectId === projectId
      && state.currentView === "project-settings"
    ))
}

function errorMessage(error) {
  if (error?.status === 409) return "作品状态已变化，请刷新当前作品的留痕报表。"
  if (error?.status === 404 || error?.status === 403) return "当前作品不可读取留痕报表。"
  return error?.message || "留痕报表暂时无法读取，请稍后重试。"
}

async function loadReport() {
  const projectId = props.projectId
  const generation = ++loadGeneration
  loadController?.abort()
  loadController = null
  report.value = null
  loadError.value = ""
  exportMessage.value = ""
  exportError.value = ""
  if (!projectId || !isCurrentProject(projectId)) {
    loading.value = false
    return
  }
  const controller = new AbortController()
  loadController = controller
  loading.value = true
  try {
    const result = await getApi().assistant.operationTraceReport(
      projectId,
      period.value,
      { signal: controller.signal },
    )
    if (generation !== loadGeneration || !isCurrentProject(projectId)) return
    report.value = result
  } catch (error) {
    if (generation !== loadGeneration || !isCurrentProject(projectId) || error?.name === "AbortError") return
    loadError.value = errorMessage(error)
  } finally {
    if (generation === loadGeneration) {
      loading.value = false
      loadController = null
    }
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 30000)
}

async function exportReport(format) {
  const projectId = props.projectId
  if (!projectId || exporting.value || !report.value || !isCurrentProject(projectId)) return
  const generation = ++exportGeneration
  exportController?.abort()
  const controller = new AbortController()
  exportController = controller
  exporting.value = true
  exportMessage.value = ""
  exportError.value = ""
  try {
    const blob = await getApi().assistant.exportOperationTraceReport(
      projectId,
      period.value,
      format,
      { signal: controller.signal },
    )
    if (generation !== exportGeneration || !isCurrentProject(projectId)) return
    downloadBlob(blob, `operation-trace-report-${period.value}.${format}`)
    exportMessage.value = `${PERIOD_LABELS[period.value]}报告已下载。`
  } catch (error) {
    if (generation !== exportGeneration || !isCurrentProject(projectId) || error?.name === "AbortError") return
    exportError.value = errorMessage(error)
  } finally {
    if (generation === exportGeneration) {
      exporting.value = false
      exportController = null
    }
  }
}

function operationLabel(operation) {
  return report.value?.operation_labels?.[operation] || "历史操作（名称不可用）"
}

function eventLabel(event) {
  return EVENT_LABELS[event] || "其他已记录事件"
}

function statusLabel(status) {
  if (status === "measurable" || status === "recorded_sample") return "有可核对样本"
  if (status === "partial") return "部分可测，存在缺口"
  return "不可测：缺少证据"
}

function formatRate(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "不可测"
}

function profileLabel(profile) {
  const values = []
  for (const [field, shape] of Object.entries(profile?.fields || {})) {
    const label = FIELD_LABELS[field] || "其他参数"
    if (shape.present !== true) {
      values.push(`${label}：未提供`)
      continue
    }
    const details = []
    if (shape.type) details.push(TYPE_LABELS[shape.type] || "已提供")
    if (shape.length) details.push(`长度 ${shape.length}`)
    if (shape.size) details.push(`数值范围 ${shape.size}`)
    if (shape.count) details.push(`${shape.count} 项`)
    if (shape.field_count) details.push(`${shape.field_count} 个字段`)
    values.push(`${label}：${details.join("，") || "已提供"}`)
  }
  if (profile?.unknown_fields_present) values.push("另有未登记参数字段")
  return values.length ? values.join("；") : "无可展示的参数形状"
}

function formatDate(value) {
  return value || "—"
}

watch([() => props.projectId, period], () => {
  exportGeneration += 1
  exportController?.abort()
  exportController = null
  exporting.value = false
  void loadReport()
}, { immediate: true })

onBeforeUnmount(() => {
  disposed = true
  loadGeneration += 1
  exportGeneration += 1
  loadController?.abort()
  exportController?.abort()
})
</script>

<template>
  <section class="operation-trace-report" aria-labelledby="operation-trace-title" :aria-busy="loading || exporting">
    <header class="otr-heading">
      <div>
        <p class="otr-eyebrow">当前作品 · 作者私有</p>
        <h2 id="operation-trace-title">真实操作留痕</h2>
        <p class="otr-intro">查看已记录的提议、作者决定、执行、恢复、耗时与可归属用量。这里只呈现匿名汇总，不包含正文或资产标识。</p>
      </div>
      <div class="otr-export-actions" aria-label="导出报表">
        <button type="button" class="otr-button otr-button-secondary" :disabled="loading || exporting || !report" @click="exportReport('csv')">
          {{ exporting ? "准备导出…" : "导出 CSV" }}
        </button>
        <button type="button" class="otr-button otr-button-secondary" :disabled="loading || exporting || !report" @click="exportReport('json')">导出 JSON</button>
      </div>
    </header>

    <div class="otr-toolbar">
      <label>
        <span>时间范围</span>
        <select v-model="period" aria-label="操作留痕时间范围">
          <option v-for="item in PERIODS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label>
        <span>事件类型</span>
        <select v-model="eventGroup" aria-label="操作留痕事件类型">
          <option v-for="item in EVENT_GROUPS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <button type="button" class="otr-button otr-refresh" :disabled="loading" @click="loadReport">{{ loading ? "正在读取…" : "刷新报表" }}</button>
      <p v-if="report" class="otr-range" role="status">
        UTC {{ formatDate(report.window_start) }} 至 {{ report.window_end }} · 截点 {{ report.as_of }} · {{ totalEvents.toLocaleString() }} 条事件
      </p>
    </div>

    <p v-if="loading" class="otr-state" role="status">正在读取当前作品的匿名汇总…</p>
    <div v-else-if="loadError" class="otr-error" role="alert">
      <p>{{ loadError }}</p>
      <button type="button" class="otr-button" @click="loadReport">重新读取</button>
    </div>
    <div v-else-if="report" class="otr-content">
      <section class="otr-coverage" aria-labelledby="otr-coverage-title">
        <div>
          <h3 id="otr-coverage-title">记录覆盖</h3>
          <p class="otr-coverage-status">{{ report.coverage.status === "no_records" ? "当前范围没有留痕记录" : statusLabel(report.coverage.status) }}</p>
          <p>{{ report.coverage.note }}</p>
          <p>实际记录日期：{{ report.coverage.first_record_date || "无" }} 至 {{ report.coverage.last_record_date || "无" }}；有记录的 UTC 日期 {{ report.coverage.days_with_records }} 天。</p>
          <p>留痕当前{{ report.collection_enabled_now ? "已开启" : "已关闭" }}。关闭留痕不会删除已有汇总，但关闭期间及写入失败造成的缺口不能回溯。</p>
        </div>
        <dl class="otr-gap-list">
          <div><dt>缺少新版计量汇总的历史事件</dt><dd>{{ report.coverage.missing_metric_event_count }}</dd></div>
          <div><dt>没有可归属用量账本的事件</dt><dd>{{ report.coverage.unmeasured_usage_event_count }}</dd></div>
          <div><dt>耗时无样本 / 用量不完整</dt><dd>{{ report.coverage.missing_duration_event_count }} / {{ report.coverage.incomplete_usage_event_count }}</dd></div>
          <div><dt>用量结果未知 / 已记录待结算量</dt><dd>{{ report.coverage.unknown_usage_event_count }} / {{ report.coverage.pending_usage_total ?? "不可测" }}</dd></div>
          <div><dt>缺少可关联生命周期证据的事件</dt><dd>{{ report.coverage.missing_lifecycle_event_count }}</dd></div>
          <div><dt>旧摘要或关联不完整序列</dt><dd>{{ report.coverage.incomplete_sequence_count }}</dd></div>
        </dl>
      </section>

      <p v-if="report.coverage.status === 'no_records'" class="otr-empty" role="status">
        这个时间范围没有已记录样本。报表不会把缺少记录解释为零次操作、零耗时或零用量。
      </p>

      <section class="otr-section" aria-labelledby="otr-operations-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-operations-title">真实操作候选</h3><p>按本窗口内已记录事件数排序，供作者观察；不会自动挑选或新增操作配方。</p></div>
        </div>
        <div v-if="report.operation_candidates.length" class="otr-candidate-list">
          <div v-for="item in report.operation_candidates" :key="item.operation" class="otr-candidate">
            <span>{{ operationLabel(item.operation) }}</span><strong>{{ item.recorded_event_count.toLocaleString() }}</strong>
          </div>
        </div>
        <p v-else class="otr-empty">没有可排序的真实操作样本。</p>
      </section>

      <section class="otr-section" aria-labelledby="otr-events-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-events-title">操作事件</h3><p>重复确认按同一匿名调用去重计算接受状态；原始事件数仍用于说明记录量。</p></div>
          <span class="otr-count">{{ filteredEvents.length }} 项</span>
        </div>
        <div v-if="filteredEvents.length" class="otr-table-wrap">
          <table class="otr-table">
            <thead><tr><th scope="col">UTC 日期</th><th scope="col">操作</th><th scope="col">事件</th><th scope="col">记录数</th></tr></thead>
            <tbody><tr v-for="(row, index) in filteredEvents" :key="`${row.date}-${row.operation}-${row.event}-${index}`"><td>{{ row.date }}</td><td>{{ operationLabel(row.operation) }}</td><td>{{ eventLabel(row.event) }}</td><td>{{ row.count.toLocaleString() }}</td></tr></tbody>
          </table>
        </div>
        <p v-else class="otr-empty">当前筛选没有事件。</p>
      </section>

      <section class="otr-section" aria-labelledby="otr-lifecycle-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-lifecycle-title">接受、修改与恢复</h3><p>接受率只按同一 UTC 日、同一操作与可关联提议中的明确接受/拒绝计算；执行完成不等于作者接受。</p></div>
        </div>
        <div v-if="report.lifecycle.length" class="otr-table-wrap">
          <table class="otr-table otr-wide-table">
            <thead><tr><th scope="col">操作</th><th scope="col">提议</th><th scope="col">接受 / 拒绝</th><th scope="col">明确决定接受率</th><th scope="col">先修改后接受</th><th scope="col">执行成功 / 失败 / 未知</th><th scope="col">恢复 / 撤销</th><th scope="col">执行后恢复率</th><th scope="col">覆盖</th></tr></thead>
            <tbody>
              <tr v-for="row in report.lifecycle" :key="row.operation">
                <td>{{ operationLabel(row.operation) }}</td><td>{{ row.proposals }}</td><td>{{ row.accepted }} / {{ row.declined }}</td>
                <td>{{ formatRate(row.acceptance_rate) }}<small>分母 {{ row.acceptance_rate_denominator }} · {{ statusLabel(row.acceptance_rate_status) }}</small></td>
                <td>{{ row.edited_then_accepted }}<small>{{ formatRate(row.edited_acceptance_rate) }}</small></td>
                <td>{{ row.execution_groups }} / {{ row.failed_execution_groups }} / {{ row.unknown_execution_groups }}</td><td>{{ row.restored_events }} / {{ row.undone_events }}<small>可关联 {{ row.matched_restoration_groups }} 组</small></td>
                <td>{{ formatRate(row.restoration_rate) }}<small>分母 {{ row.restoration_rate_denominator }} · {{ statusLabel(row.restoration_rate_status) }}</small></td>
                <td>{{ statusLabel(row.status) }}<small v-if="row.missing_lifecycle_event_count">缺口 {{ row.missing_lifecycle_event_count }}</small></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="otr-empty">没有可测的作者决定或恢复样本；历史缺少关联证据时不会推算接受率。</p>
        <p class="otr-method-note">“结果未知”单独列示，不计为成功或失败。“先修改后接受”要求同一匿名调用有已记录修改并随后确认。执行后恢复率以本窗口可关联的执行组为分母，每组最多计一次；明细仍在保留期内可跨 UTC 日关联，匿名归档或旧版缺口会标为部分可测。</p>
      </section>

      <section class="otr-section" aria-labelledby="otr-metrics-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-metrics-title">耗时与用量</h3><p>只有有证据的样本才显示数值；Goal 仅归属可从串行步骤账本精确差分的请求与词元。</p></div>
        </div>
        <div v-if="report.metrics.length" class="otr-table-wrap">
          <table class="otr-table otr-wide-table">
            <thead><tr><th scope="col">操作 / 事件</th><th scope="col">耗时均值</th><th scope="col">耗时样本</th><th scope="col">已归属请求</th><th scope="col">工具尝试 / 网页请求</th><th scope="col">输入 / 输出词元</th><th scope="col">待结算用量</th><th scope="col">用量覆盖</th></tr></thead>
            <tbody>
              <tr v-for="row in report.metrics" :key="`${row.operation}-${row.event}`">
                <td>{{ operationLabel(row.operation) }}<small>{{ eventLabel(row.event) }}</small></td>
                <td>{{ row.duration.average_ms == null ? "不可测" : `${row.duration.average_ms.toLocaleString()} ms` }}</td>
                <td>{{ row.duration.sample_count }} / {{ row.event_count }}<small>{{ statusLabel(row.duration.status) }}</small></td>
                <td>{{ row.usage.fields.requests?.total ?? "不可测" }}<small v-if="row.usage.unknown_event_count">另有 {{ row.usage.unknown_event_count }} 次用量未知</small></td>
                <td>{{ row.usage.fields.tool_attempts?.total ?? "不可测" }} / {{ row.usage.fields.web_requests?.total ?? "不可测" }}</td>
                <td>{{ row.usage.fields.prompt_tokens?.total ?? "不可测" }} / {{ row.usage.fields.completion_tokens?.total ?? "不可测" }}</td>
                <td>{{ row.usage.fields.pending_usage?.total ?? "不可测" }}</td>
                <td>{{ statusLabel(row.usage.status) }}<small v-if="row.usage.pending_total">待结算 {{ row.usage.pending_total }}</small></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="otr-empty">当前范围没有可以核对的耗时或用量账本。没有记录不代表零消耗。</p>
        <p class="otr-method-note">Goal 规划阶段的根用量不会分摊到具体操作；工具尝试数和网页请求数在当前 Goal 根账本中没有可逐操作证明的字段，因此保持不可测。</p>
      </section>

      <section class="otr-section" aria-labelledby="otr-sequences-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-sequences-title">终态操作序列</h3><p>按 UTC 日期与匿名会话 / 运行 / 调用边界分组，按数据库事件顺序构造。</p></div>
        </div>
        <div v-if="report.sequences.length" class="otr-sequence-list">
          <article v-for="(row, index) in report.sequences" :key="`${row.date}-${row.operations.join('|')}-${index}`" class="otr-sequence">
            <div class="otr-sequence-meta"><time>{{ row.date }}</time><strong>{{ row.count }} 次</strong><span :class="row.complete ? 'otr-complete' : 'otr-partial'">{{ row.complete ? "序列完整" : "旧摘要或边界不完整" }}</span></div>
            <ol><li v-for="(operation, step) in row.operations" :key="`${operation}-${step}`">{{ operationLabel(operation) }}</li></ol>
          </article>
        </div>
        <p v-else class="otr-empty">当前范围没有终态序列。</p>
      </section>

      <section class="otr-section" aria-labelledby="otr-parameters-title">
        <div class="otr-section-heading">
          <div><h3 id="otr-parameters-title">参数形状</h3><p>只汇总声明字段的类型与粗粒度范围；字段值、文本摘要及文本哈希不出现在此报表。</p></div>
        </div>
        <div v-if="report.parameter_profiles.length" class="otr-profile-list">
          <article v-for="(row, index) in report.parameter_profiles" :key="`${row.operation}-${row.event}-${index}`" class="otr-profile">
            <div><strong>{{ operationLabel(row.operation) }}</strong><span>{{ eventLabel(row.event) }} · {{ row.count }} 次</span></div>
            <p>{{ profileLabel(row.profile) }}</p>
          </article>
        </div>
        <p v-else class="otr-empty">没有可展示的参数形状。</p>
      </section>

      <footer class="otr-footer">
        <p>报告只包含当前作者项目的匿名汇总，不含所有者、会话、运行、调用、目标或资产 ID、正文、提示词、密钥或可逆参数；文件由浏览器下载，不会自动上传。</p>
        <p v-if="exportMessage" class="otr-success" role="status">{{ exportMessage }}</p>
        <p v-if="exportError" class="otr-inline-error" role="alert">{{ exportError }}</p>
      </footer>
    </div>
  </section>
</template>

<style scoped>
.operation-trace-report {
  --otr-ink: var(--text-primary, #26332e);
  --otr-muted: var(--text-secondary, #66736d);
  --otr-line: var(--border-color, #dce4df);
  --otr-surface: var(--surface-color, #fff);
  --otr-soft: color-mix(in srgb, var(--surface-color, #fff) 90%, #dbe9df);
  color: var(--otr-ink);
  display: grid;
  gap: 1.25rem;
  max-width: 1120px;
  margin: 0 auto;
  padding: clamp(1rem, 2.5vw, 2rem);
}
.otr-heading, .otr-section-heading, .otr-toolbar, .otr-sequence-meta {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: .8rem 1rem;
  justify-content: space-between;
}
.otr-heading { align-items: flex-start; }
.otr-heading h2 { font-size: clamp(1.45rem, 3vw, 2rem); margin: .15rem 0 .4rem; }
.otr-eyebrow { color: var(--otr-muted); font-size: .78rem; font-weight: 700; letter-spacing: .07em; margin: 0; text-transform: uppercase; }
.otr-intro, .otr-section-heading p, .otr-coverage p, .otr-method-note, .otr-footer p { color: var(--otr-muted); line-height: 1.55; margin: .35rem 0; max-width: 78ch; }
.otr-export-actions, .otr-toolbar { display: flex; flex-wrap: wrap; gap: .65rem; }
.otr-toolbar { background: var(--otr-soft); border: 1px solid var(--otr-line); border-radius: .9rem; padding: .85rem 1rem; }
.otr-toolbar label { display: grid; gap: .25rem; min-width: 9rem; }
.otr-toolbar label span { color: var(--otr-muted); font-size: .78rem; font-weight: 650; }
.otr-toolbar select { background: var(--otr-surface); border: 1px solid var(--otr-line); border-radius: .5rem; color: var(--otr-ink); min-height: 2.5rem; padding: .4rem .65rem; }
.otr-range { color: var(--otr-muted); font-size: .85rem; margin: 0 0 0 auto; }
.otr-button { background: #315c49; border: 1px solid #315c49; border-radius: .55rem; color: white; cursor: pointer; font: inherit; font-weight: 650; min-height: 2.55rem; padding: .5rem .85rem; }
.otr-button-secondary { background: var(--otr-surface); color: #315c49; }
.otr-button:disabled { cursor: not-allowed; opacity: .55; }
.otr-button:focus-visible, .otr-toolbar select:focus-visible { outline: 3px solid #e5ad4a; outline-offset: 2px; }
.otr-content, .otr-section { display: grid; gap: .85rem; }
.otr-coverage { background: var(--otr-soft); border: 1px solid var(--otr-line); border-radius: .9rem; display: grid; gap: 1rem; grid-template-columns: minmax(0, 1.5fr) minmax(15rem, .8fr); padding: 1rem 1.1rem; }
.otr-coverage h3, .otr-section h3 { margin: 0; }
.otr-coverage-status { color: #315c49 !important; font-weight: 750; }
.otr-gap-list { align-content: start; display: grid; gap: .5rem; margin: 0; }
.otr-gap-list div { border-bottom: 1px solid var(--otr-line); display: flex; gap: .75rem; justify-content: space-between; padding: .35rem 0; }
.otr-gap-list dt { color: var(--otr-muted); font-size: .86rem; }
.otr-gap-list dd { font-variant-numeric: tabular-nums; font-weight: 750; margin: 0; }
.otr-section { border: 1px solid var(--otr-line); border-radius: .9rem; padding: 1rem; }
.otr-section-heading { align-items: flex-start; }
.otr-count { color: var(--otr-muted); font-size: .82rem; white-space: nowrap; }
.otr-candidate-list { display: grid; gap: .5rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr)); }
.otr-candidate { align-items: center; background: var(--otr-soft); border-radius: .6rem; display: flex; gap: .7rem; justify-content: space-between; min-width: 0; padding: .65rem .75rem; }
.otr-candidate span { overflow-wrap: anywhere; }
.otr-candidate strong { font-variant-numeric: tabular-nums; white-space: nowrap; }
.otr-table-wrap { max-width: 100%; overflow-x: auto; }
.otr-table { border-collapse: collapse; font-size: .88rem; min-width: 35rem; width: 100%; }
.otr-wide-table { min-width: 62rem; }
.otr-table th, .otr-table td { border-bottom: 1px solid var(--otr-line); padding: .65rem .55rem; text-align: left; vertical-align: top; }
.otr-table th { color: var(--otr-muted); font-size: .78rem; font-weight: 700; }
.otr-table td { font-variant-numeric: tabular-nums; }
.otr-table small { color: var(--otr-muted); display: block; font-size: .76rem; line-height: 1.4; margin-top: .2rem; }
.otr-sequence-list, .otr-profile-list { display: grid; gap: .65rem; }
.otr-sequence, .otr-profile { background: var(--otr-soft); border-radius: .65rem; padding: .75rem .85rem; }
.otr-sequence ol { display: flex; flex-wrap: wrap; gap: .4rem 1.4rem; margin: .6rem 0 0; padding-left: 1.3rem; }
.otr-sequence li { padding-right: .2rem; }
.otr-sequence-meta { justify-content: flex-start; }
.otr-sequence-meta time { color: var(--otr-muted); font-size: .82rem; }
.otr-complete, .otr-partial { border-radius: 999px; font-size: .75rem; font-weight: 700; padding: .18rem .55rem; }
.otr-complete { background: #e1f2e6; color: #245a35; }
.otr-partial { background: #fff0d5; color: #784c10; }
.otr-profile > div { align-items: baseline; display: flex; flex-wrap: wrap; gap: .35rem .8rem; }
.otr-profile span, .otr-profile p { color: var(--otr-muted); font-size: .84rem; margin: .35rem 0 0; overflow-wrap: anywhere; }
.otr-method-note { background: var(--otr-soft); border-radius: .55rem; font-size: .82rem; padding: .65rem .75rem; }
.otr-empty, .otr-state { color: var(--otr-muted); margin: .25rem 0; }
.otr-error, .otr-inline-error { color: #a22e29; }
.otr-success { color: #27623b !important; font-weight: 700; }
.otr-footer { border-top: 1px solid var(--otr-line); padding-top: .6rem; }
.otr-footer p { font-size: .82rem; }
@media (max-width: 600px) {
  .operation-trace-report { padding: .85rem; }
  .otr-heading { display: grid; }
  .otr-export-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .otr-export-actions .otr-button { padding-inline: .4rem; }
  .otr-toolbar { align-items: stretch; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .otr-toolbar label { min-width: 0; }
  .otr-toolbar select { max-width: 100%; }
  .otr-refresh { grid-column: 1 / 2; }
  .otr-range { grid-column: 1 / -1; margin: 0; }
  .otr-coverage { grid-template-columns: 1fr; }
  .otr-section { padding: .8rem; }
  .otr-sequence-meta { align-items: flex-start; gap: .45rem .7rem; }
}
</style>
