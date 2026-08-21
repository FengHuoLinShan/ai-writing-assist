<template>
  <details class="panel world-health-panel" open data-section="world-health">
    <summary>
      <strong>世界健康</strong>
      <span class="badge" :class="gateClass">{{ statusLabel }}</span>
      <span class="world-bible-open-questions__hint">{{ statusHint }}</span>
    </summary>

    <div class="world-health-body">
      <div v-if="!policy.active" class="world-health-callout">
        <p>当前可自愿运行校验，但发布和设定采用尚未启用强制门禁，旧项目行为不变。</p>
        <button
          type="button"
          class="btn btn-sm"
          data-action="world-health-activate-policy"
          :disabled="activating"
          @click="activatePolicy"
        >{{ activating ? "正在启用…" : "启用发布前校验" }}</button>
      </div>
      <p v-else class="world-health-callout is-pass">
        发布前校验已启用·{{ policy.semantic_enabled ? "含语义审计" : "结构与世界引擎校验" }}
      </p>
      <p v-if="policy.semantic_enabled" class="world-bible-empty-hint" :class="{ 'form-error': policy.will_exceed_budget }">
        全面语义审计预计 {{ Number(policy.estimated_packets || 0).toLocaleString("zh-CN") }} 个分片、{{ Number(policy.estimated_input_characters || 0).toLocaleString("zh-CN") }} 字符。
        <template v-if="policy.will_exceed_budget">已超出当前上限，提交后将阻断为“证据不足”。</template>
      </p>

      <div class="world-health-metrics" aria-label="世界健康摘要">
        <span><strong>{{ decisionCount }}</strong>项待我决定</span>
        <span><strong>{{ gapCount }}</strong>项待补证据</span>
        <span><strong>{{ invalidatedCount }}</strong>项失效或不完整</span>
      </div>

      <div class="world-bible-panel__actions">
        <button
          v-if="targetId && targetType !== 'world_adoption_package' && !requiresFullScope"
          type="button"
          class="btn btn-sm btn-primary"
          data-action="world-health-run-targeted"
          :disabled="busy"
          @click="startRun('targeted')"
        >{{ busy && pendingScope === "targeted" ? `正在${targetLabel}…` : targetLabel }}</button>
        <button
          type="button"
          class="btn btn-sm"
          data-action="world-health-run-full"
          :disabled="busy"
          @click="startRun('full')"
        >{{ busy && pendingScope === "full" ? `正在${fullRunLabel}…` : fullRunLabel }}</button>
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-health-history" :disabled="historyLoading" @click="loadHistory">
          {{ historyLoading ? "正在加载…" : "最近回执" }}
        </button>
      </div>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-else-if="busy" class="world-bible-empty-hint" role="status">校验在后台进行，离开后也会保留进度。</p>
      <p v-else-if="!run" class="world-bible-empty-hint">尚未校验。可先检查当前工作稿，准备采用整体设定时再做全面校验。</p>

      <template v-if="run">
        <p v-if="run.status === 'stale'" class="world-health-callout is-blocked">校验后资料已变化，请重新运行；旧回执不再能用于发布或采用。</p>
        <p v-else-if="run.gate === 'block'" class="world-health-callout is-blocked">当前有阻断项，修正或完成作者裁定后再校验。</p>
        <p v-else-if="run.gate === 'warn' && !warningsAccepted" class="world-health-callout">没有硬阻断，但存在需作者明确承担的风险。</p>

        <ul v-if="visibleFindings.length" class="world-health-findings" aria-label="校验问题">
          <li v-for="finding in visibleFindings" :key="finding.finding_id" :class="`is-${finding.severity}`">
            <div>
              <strong>{{ actionLabel(finding.action) }}</strong>
              <p>{{ finding.message }}</p>
              <small v-if="finding.location">{{ locationLabel(finding.location) }}</small>
            </div>
            <button v-if="sourceTarget(finding)" type="button" class="btn btn-sm btn-ghost" @click="emit('open-source', sourceTarget(finding))">打开来源</button>
          </li>
        </ul>
        <p v-else-if="run.status === 'completed'" class="world-health-callout is-pass">本次范围未发现需处理的问题。</p>
        <p v-if="(run.findings || []).length > visibleFindings.length" class="world-bible-empty-hint">还有 {{ run.findings.length - visibleFindings.length }} 项，请先处理前 50 项后重新校验。</p>

        <form v-if="run.gate === 'warn' && !warningsAccepted && run.status === 'completed'" class="world-health-warning-form" @submit.prevent="acceptWarnings">
          <label>为什么可以带着这些风险继续？
            <textarea v-model.trim="warningReason" class="form-input" rows="2" maxlength="1000" required></textarea>
          </label>
          <button type="submit" class="btn btn-sm" data-action="world-health-accept-warnings" :disabled="accepting || !warningReason">{{ accepting ? "正在记录…" : "签收全部提示" }}</button>
        </form>
        <p v-else-if="warningsAccepted" class="world-health-callout is-pass">已记录作者对本次提示的签收。</p>
      </template>

      <ol v-if="history.length" class="world-health-history" aria-label="最近校验回执">
        <li v-for="item in history" :key="item.id">
          <button type="button" class="btn btn-ghost" @click="selectHistory(item)">
            <strong>{{ item.scope === "full" ? "全面校验" : "定向校验" }}</strong>
            <span>{{ runStatusLabel(item) }} · {{ formatTime(item.finished_at || item.created_at) }}</span>
          </button>
        </li>
      </ol>
    </div>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { createOperationId, pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { getApi, getConfirm, getToast } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  targetType: { type: String, default: "world_bible_draft" },
  targetId: { type: String, default: "" },
  requiresFullScope: { type: Boolean, default: false },
  initialRun: { type: Object, default: null },
  policyStatus: { type: Object, default: () => ({ active: false }) },
})
const emit = defineEmits(["open-source", "policy-updated", "updated"])
const api = getApi()
const confirm = getConfirm()
const toast = getToast()
const run = ref(props.initialRun)
const policy = ref(props.policyStatus || { active: false })
const history = ref([])
const error = ref("")
const pendingScope = ref("")
const historyLoading = ref(false)
const accepting = ref(false)
const activating = ref(false)
const warningReason = ref("")
let generation = 0
let poller = null

const busy = computed(() => ["queued", "running"].includes(run.value?.status) || Boolean(pendingScope.value))
const findings = computed(() => Array.isArray(run.value?.findings) ? run.value.findings : [])
const visibleFindings = computed(() => [...findings.value].sort((a, b) => (a.severity === "error" ? -1 : 1) - (b.severity === "error" ? -1 : 1)).slice(0, 50))
const decisionCount = computed(() => findings.value.filter((item) => item.action === "AUTHOR-REQUIRED").length)
const gapCategories = new Set(["facet-gap", "pressure-not-run", "missing-world-state", "reproduction-loop-gap", "coupling-chain-gap", "situated-test-gap", "rule-economics-gap", "candidate-mountain"])
const gapCount = computed(() => findings.value.filter((item) => gapCategories.has(item.category)).length)
const invalidatedCount = computed(() => Number(run.value?.omissions?.length || 0)
  + findings.value.filter((item) => item.category === "downstream-invalidation-missing").length
  + (run.value?.status === "stale" ? 1 : 0))
const warningsAccepted = computed(() => Boolean(run.value?.warning_receipt?.receipt_hash))
const statusLabel = computed(() => runStatusLabel(run.value))
const statusHint = computed(() => run.value
  ? `${run.value.scope === "full" ? "全面" : "定向"}回执 · ${formatTime(run.value.finished_at || run.value.created_at)}`
  : "尚无回执")
const gateClass = computed(() => ({ pass: "badge-canonical", warn: "badge-draft", block: "badge-failed" })[run.value?.gate] || "")
const targetLabel = computed(() => props.targetType === "world_adoption_package" ? "校验这份采用包" : "校验当前工作稿")
const fullRunLabel = computed(() => props.targetType === "world_adoption_package"
  ? "全面校验并准备采用"
  : props.requiresFullScope ? "全面校验并准备发布" : "全面校验")

watch(() => props.initialRun, (value) => {
  run.value = value
  recoverPolling()
})
watch(() => props.policyStatus, (value) => {
  policy.value = value || { active: false }
})

async function activatePolicy() {
  if (activating.value || !confirm("启用后，世界书发布和设定采用必须先完成当前版本的校验。是否继续？")) return false
  activating.value = true
  error.value = ""
  try {
    await api.world.activateWorldValidationPolicy(props.projectId)
    policy.value = { active: true, policy_version: "project-default-v1", semantic_enabled: false }
    emit("policy-updated", policy.value)
    toast("已启用发布前校验", "success")
    return true
  } catch (err) {
    error.value = err?.message || "无法启用发布前校验。"
    return false
  } finally {
    activating.value = false
  }
}

function runStatusLabel(value) {
  if (!value) return "未运行"
  if (["queued", "running"].includes(value.status)) return "校验中"
  if (value.status === "failed") return "校验失败"
  if (value.status === "stale") return "已失效"
  return ({ pass: "已通过", warn: "有提示", block: "需修正" })[value.gate] || "已完成"
}
const actionLabel = (action) => ({ CLOSE: "必须修正", SPLIT: "需拆分理清", "KEEP-GATE": "请核对", CANDIDATE: "待补证据", "AUTHOR-REQUIRED": "需作者决定" })[action] || "请核对"
const locationLabel = (location) => {
  const key = String(location || "").split(":", 1)[0]
  return ({
    facets: "世界切面覆盖",
    pressure_tests: "压力测试",
    reproduction_loops: "世界循环",
    coupling_chains: "耦合链",
    situated_tests: "情境测试",
  })[key] || "来源中的具体位置"
}
function sourceTarget(finding) {
  const match = String(finding?.source_key || "").match(/^(page|draft):(.+)$/)
  return match ? { kind: match[1], id: match[2] } : null
}
function formatTime(value) {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

async function startRun(scope) {
  if (busy.value) return false
  if (scope === "targeted" && !props.targetId) return false
  const token = ++generation
  pendingScope.value = scope
  error.value = ""
  stopPolling()
  try {
    const created = await api.world.createWorldValidationRun({
      novel_id: props.projectId,
      operation_id: createOperationId(),
      scope,
      trigger: "world_health",
      ...(scope === "targeted" ? { target_type: props.targetType, target_id: props.targetId } : {}),
    })
    if (token !== generation) return false
    run.value = created
    emit("updated", created)
    startPolling(created)
    return true
  } catch (err) {
    if (token === generation) error.value = err?.message || "无法启动校验。"
    return false
  } finally {
    if (token === generation) pendingScope.value = ""
  }
}

function startPolling(value) {
  if (!value?.task_id || !["queued", "running"].includes(value.status)) return
  stopPolling()
  const token = generation
  poller = pollTaskProgress({
    taskId: value.task_id,
    workflowType: "world_validation",
    apiClient: { tasks: { get: (id) => api.tasks.get(id, props.projectId) } },
    intervalMs: 900,
    onDone: () => refreshRun(value.id, token, true),
    onFailed: (progress) => {
      if (token !== generation) return
      error.value = progress.errorMessage || "校验任务失败。"
      refreshRun(value.id, token)
    },
  })
}

async function refreshRun(runId, token, announce = false) {
  try {
    const current = await api.world.getWorldValidationRun(runId, props.projectId)
    if (token !== generation) return
    run.value = current
    emit("updated", current)
    if (announce) toast("世界书校验已完成", current.gate === "block" ? "warning" : "success")
  } catch (err) {
    if (token === generation) error.value = err?.message || "无法读取校验结果。"
  }
}

function recoverPolling() {
  generation += 1
  stopPolling()
  if (["queued", "running"].includes(run.value?.status)) startPolling(run.value)
}

async function acceptWarnings() {
  if (!run.value?.receipt_hash || !warningReason.value || accepting.value) return false
  accepting.value = true
  error.value = ""
  try {
    const accepted = await api.world.acceptWorldValidationWarnings(run.value.id, props.projectId, {
      expected_receipt_hash: run.value.receipt_hash,
      finding_ids: findings.value.filter((item) => item.severity === "warning").map((item) => item.finding_id),
      reason: warningReason.value,
    })
    run.value = accepted
    emit("updated", accepted)
    toast("已记录你对本次提示的签收", "success")
    return true
  } catch (err) {
    error.value = err?.message || "无法签收这份回执。"
    return false
  } finally {
    accepting.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  error.value = ""
  try {
    const result = await api.world.listWorldValidationRuns(props.projectId, 10)
    history.value = result?.items || []
  } catch (err) {
    error.value = err?.message || "无法加载最近回执。"
  } finally {
    historyLoading.value = false
  }
}

function selectHistory(item) {
  generation += 1
  stopPolling()
  run.value = item
  if (["queued", "running"].includes(item.status)) startPolling(item)
}
function stopPolling() {
  poller?.stop?.()
  poller = null
}

onMounted(recoverPolling)
onBeforeUnmount(() => {
  generation += 1
  stopPolling()
})
</script>
