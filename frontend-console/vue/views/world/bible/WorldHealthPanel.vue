<template>
  <details
    ref="panelRef"
    class="panel world-health-panel"
    data-section="world-health"
    :open="requestedRunId === run?.id || busy || Boolean(error) || ['block'].includes(run?.gate) || ['failed', 'stale'].includes(run?.status)"
  >
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
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-health-edit-policy" @click="openPolicyEditor">编辑校验政策</button>
      </div>
      <p v-else class="world-health-callout is-pass">
        发布前校验已启用·{{ policy.semantic_enabled ? "含语义审计" : "结构与世界引擎校验" }}
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-health-edit-policy" @click="openPolicyEditor">编辑校验政策</button>
      </p>
      <p v-if="policy.draft" class="world-bible-empty-hint">
        政策已有工作稿（{{ policy.draft.policy.policy_version }}），需在资料库发布《世界书校验策略》页后生效；
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-health-open-policy-draft" @click="emit('open-source', { kind: 'draft', id: policy.draft.draft_id })">打开政策工作稿</button>
      </p>
      <p v-if="policy.semantic_enabled" class="world-bible-empty-hint" :class="{ 'form-error': policy.will_exceed_budget }">
        全面语义审计预计 {{ Number(policy.estimated_packets || 0).toLocaleString("zh-CN") }} 个分片、{{ Number(policy.estimated_input_characters || 0).toLocaleString("zh-CN") }} 字符。
        <template v-if="policy.will_exceed_budget">超限部分将分批执行，可从本面板“继续校验”续接。</template>
      </p>

      <div class="world-health-metrics" aria-label="世界健康摘要">
        <span><strong>{{ decisionCount }}</strong>项待我决定</span>
        <span><strong>{{ gapCount }}</strong>项待补证据</span>
        <span><strong>{{ invalidatedCount }}</strong>项失效或不完整</span>
        <span v-if="reviewRequired > 0"><strong>{{ reviewDone }}/{{ reviewRequired }}</strong>项已复核</span>
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
        <button
          v-if="gapRoot && gapRoot.id"
          type="button"
          class="btn btn-sm"
          data-action="world-health-semantic-gap"
          :disabled="busy"
          @click="startGapRun"
        >{{ busy && pendingScope === "gap" ? "正在发起查漏…" : "定向语义查漏" }}</button>
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-health-history" :disabled="historyLoading" @click="loadHistory">
          {{ historyLoading ? "正在加载…" : "最近回执" }}
        </button>
      </div>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-else-if="busy" class="world-bible-empty-hint" role="status">校验在后台进行，离开后也会保留进度。</p>
      <p v-else-if="!run" class="world-bible-empty-hint">尚未校验。可先检查当前工作稿，准备采用整体设定时再做全面校验。</p>

      <template v-if="run">
        <p v-if="run.status === 'stale'" class="world-health-callout is-blocked" data-field="world-health-stale">
          {{ staleReasonLabel }}，旧回执不再能用于发布或采用；请重新校验并重新复核。
        </p>
        <p v-else-if="run.status === 'failed'" class="world-health-callout is-blocked">
          校验中断（{{ run.error_code || "未知错误" }}）。已完成分片不会丢失，可继续校验收尾。
        </p>
        <p v-else-if="run.gate === 'block' && run.verdict === 'author-required'" class="world-health-callout is-blocked">
          存在需要作者裁定的项：逐项记录处置后即可继续发布或采用。
        </p>
        <p v-else-if="run.gate === 'block'" class="world-health-callout is-blocked">当前有阻断项，修正或完成作者裁定后再校验。</p>
        <p v-else-if="run.gate === 'warn' && !warningsAccepted" class="world-health-callout">没有硬阻断，但存在需作者明确承担的风险。</p>

        <div v-if="packetProgress" class="world-health-progress" data-section="world-health-progress">
          <div class="world-health-progress__bar">
            <span :style="{ width: packetProgressPercent + '%' }"></span>
          </div>
          <small>已检查分片 {{ packetProgress.done }}/{{ packetProgress.total }}<template v-if="omissionCount"> · 遗漏 {{ omissionCount }}（未覆盖部分不宣称完成）</template><template v-if="run.progress?.packets_completed === 0 && packetProgress.total"> · 尚未开始</template></small>
        </div>

        <button
          v-if="canContinue"
          type="button"
          class="btn btn-sm"
          data-action="world-health-continue-run"
          :disabled="continuing"
          @click="continueRun"
        >{{ continuing ? "正在续接…" : "继续校验（续接已检查分片）" }}</button>

        <div v-if="findingsTotal > 0 || pageFindings.length" class="world-health-findings-toolbar">
          <label>筛选
            <select v-model="filterSeverity" class="form-input" data-field="world-health-filter-severity" @change="resetFindingsPage">
              <option value="">全部级别</option>
              <option value="error">仅阻断</option>
              <option value="warning">仅提示</option>
            </select>
          </label>
          <label>
            <select v-model="filterAction" class="form-input" data-field="world-health-filter-action" @change="resetFindingsPage">
              <option value="">全部类型</option>
              <option v-for="action in actionOptions" :key="action" :value="action">{{ actionLabel(action) }}</option>
            </select>
          </label>
          <small class="world-bible-empty-hint">共 {{ findingsTotal }} 项 · 第 {{ findingsPageNo }}/{{ findingsPageCount || 1 }} 页</small>
        </div>

        <ul v-if="pageFindings.length" class="world-health-findings" aria-label="校验问题" data-section="world-health-findings">
          <li v-for="finding in pageFindings" :key="finding.finding_id" :class="`is-${finding.severity}`">
            <div>
              <strong>{{ actionLabel(finding.action) }}</strong>
              <p>{{ finding.message }}</p>
              <small v-if="finding.location">{{ locationLabel(finding.location) }}</small>
              <div v-if="dispositions[finding.finding_id]" class="world-health-disposition is-done" :data-disposition="dispositions[finding.finding_id]">
                已复核：{{ dispositionLabel(dispositions[finding.finding_id]) }}
              </div>
              <div v-else-if="isReviewable(finding)" class="world-health-disposition">
                <button type="button" class="btn btn-sm" :data-action="'review-resolved-' + finding.finding_id" :disabled="reviewSubmitting === finding.finding_id" @click="submitDisposition(finding, 'resolved')">已修正</button>
                <button type="button" class="btn btn-sm btn-ghost" :data-action="'review-acknowledged-' + finding.finding_id" :disabled="reviewSubmitting === finding.finding_id" @click="submitDisposition(finding, 'acknowledged')">已知悉</button>
                <button type="button" class="btn btn-sm btn-ghost" :data-action="'review-deferred-' + finding.finding_id" :disabled="reviewSubmitting === finding.finding_id" @click="submitDisposition(finding, 'deferred')">稍后再定</button>
              </div>
            </div>
            <button v-if="sourceTarget(finding)" type="button" class="btn btn-sm btn-ghost" data-action="world-health-open-source" @click="emit('open-source', sourceTarget(finding))">打开来源</button>
          </li>
        </ul>
        <p v-else-if="run.status === 'completed'" class="world-health-callout is-pass">本次范围未发现需处理的问题。</p>

        <div v-if="findingsPageCount > 1" class="world-health-pager">
          <button type="button" class="btn btn-sm btn-ghost" :disabled="findingsPageNo <= 1 || findingsLoading" @click="turnFindingsPage(findingsPageNo - 1)">上一页</button>
          <span>{{ findingsPageNo }} / {{ findingsPageCount }}</span>
          <button type="button" class="btn btn-sm btn-ghost" :disabled="findingsPageNo >= findingsPageCount || findingsLoading" @click="turnFindingsPage(findingsPageNo + 1)">下一页</button>
        </div>

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
            <strong>{{ historyScopeLabel(item) }}</strong>
            <span>{{ runStatusLabel(item) }} · {{ formatTime(item.finished_at || item.created_at) }}</span>
          </button>
        </li>
      </ol>
    </div>

    <div v-if="policyEditorOpen" class="world-policy-editor" data-section="world-policy-editor" role="dialog" aria-label="编辑校验政策">
      <div class="world-policy-editor__inner">
        <header>
          <strong>编辑校验政策</strong>
          <button type="button" class="btn btn-sm btn-ghost" data-action="world-policy-close" @click="policyEditorOpen = false">关闭</button>
        </header>
        <p class="world-bible-empty-hint">政策以《世界书校验策略》规则页版本化保存；保存为工作稿后仍需走发布校验才会生效，政策变化会使旧回执失效。</p>

        <div class="world-policy-editor__grid">
          <label>版本名
            <input v-model.trim="policyForm.policy_version" class="form-input" data-field="world-policy-version" maxlength="64" required />
          </label>
          <label class="world-policy-editor__check">
            <input type="checkbox" v-model="policyForm.semantic_enabled" data-field="world-policy-semantic" />
            启用语义审计（需配置必问项）
          </label>
        </div>

        <section>
          <h4>原则与禁区</h4>
          <p class="world-bible-empty-hint">“禁止匹配”与“不包含”是禁区；其余为原则。触发时按所选级别提示或阻断。</p>
          <ul class="world-policy-editor__rows">
            <li v-for="(rule, index) in policyForm.rules" :key="index">
              <select v-model="rule.operator" class="form-input" :data-field="'world-policy-rule-op-' + index">
                <option v-for="op in operatorOptions" :key="op" :value="op">{{ operatorLabel(op) }}</option>
              </select>
              <input v-model.trim="rule.value" class="form-input" :placeholder="rule.operator === 'max_chars' ? '字数上限' : '匹配内容'" :data-field="'world-policy-rule-value-' + index" />
              <select v-model="rule.severity" class="form-input">
                <option value="error">阻断</option>
                <option value="warning">提示</option>
              </select>
              <input v-model.trim="rule.message" class="form-input" placeholder="作者能看懂的提示语" :data-field="'world-policy-rule-message-' + index" />
              <button type="button" class="btn btn-sm btn-ghost" :data-action="'world-policy-rule-remove-' + index" @click="policyForm.rules.splice(index, 1)">移除</button>
            </li>
          </ul>
          <button type="button" class="btn btn-sm" data-action="world-policy-rule-add" @click="addRule">添加原则/禁区</button>
        </section>

        <section>
          <h4>必问项（按知识层分组）</h4>
          <ul class="world-policy-editor__rows">
            <li v-for="(question, index) in policyForm.required_questions" :key="index">
              <select v-model="question.gate" class="form-input" :data-field="'world-policy-question-gate-' + index">
                <option v-for="gate in gateOptions" :key="gate" :value="gate">{{ gateLabel(gate) }}</option>
              </select>
              <input v-model.trim="question.question" class="form-input" placeholder="每次语义审计必问的问题" :data-field="'world-policy-question-text-' + index" />
              <button type="button" class="btn btn-sm btn-ghost" :data-action="'world-policy-question-remove-' + index" @click="policyForm.required_questions.splice(index, 1)">移除</button>
            </li>
          </ul>
          <button type="button" class="btn btn-sm" data-action="world-policy-question-add" @click="addQuestion" :disabled="!policyForm.semantic_enabled">添加必问项</button>
        </section>

        <details>
          <summary>高级预算</summary>
          <div class="world-policy-editor__grid">
            <label>每分片字符上限<input v-model.number="policyForm.packet_character_limit" class="form-input" type="number" min="4000" max="80000" /></label>
            <label>每轮最多分片<input v-model.number="policyForm.max_packets" class="form-input" type="number" min="1" max="256" /></label>
            <label>每轮最多输入字符<input v-model.number="policyForm.max_input_characters" class="form-input" type="number" min="4000" max="8000000" /></label>
            <label>每分片输出 token<input v-model.number="policyForm.max_output_tokens_per_packet" class="form-input" type="number" min="256" max="8000" /></label>
            <label>每分片超时（秒）<input v-model.number="policyForm.per_packet_timeout_seconds" class="form-input" type="number" min="30" max="1800" /></label>
          </div>
        </details>

        <p v-if="policyError" class="form-error" role="alert">{{ policyError }}</p>
        <div class="world-bible-panel__actions">
          <button type="button" class="btn btn-sm btn-primary" data-action="world-policy-save" :disabled="policySaving" @click="savePolicyDraft">
            {{ policySaving ? "正在保存…" : "保存政策工作稿" }}
          </button>
        </div>
      </div>
    </div>
  </details>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { createOperationId, pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import { getApi, getConfirm, getRouteQuery, getToast } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  targetType: { type: String, default: "world_bible_draft" },
  targetId: { type: String, default: "" },
  requiresFullScope: { type: Boolean, default: false },
  initialRun: { type: Object, default: null },
  policyStatus: { type: Object, default: () => ({ active: false }) },
  gapRoot: { type: Object, default: null },
})
const emit = defineEmits(["open-source", "policy-updated", "updated", "gap-root-needed"])
const api = getApi()
const confirm = getConfirm()
const toast = getToast()
const run = ref(props.initialRun)
const panelRef = ref(null)
const requestedRunId = getRouteQuery().get("validation_run_id")
const policy = ref(props.policyStatus || { active: false })
const history = ref([])
const error = ref("")
const pendingScope = ref("")
const historyLoading = ref(false)
const accepting = ref(false)
const activating = ref(false)
const warningReason = ref("")
const continuing = ref(false)
const findingsLoading = ref(false)
const findingsPageNo = ref(1)
const findingsPageSize = 20
const findingsTotal = ref(0)
const pageFindings = ref([])
const dispositions = ref({})
const filterSeverity = ref("")
const filterAction = ref("")
const reviewSubmitting = ref("")
const policyEditorOpen = ref(false)
const policySaving = ref(false)
const policyError = ref("")
const policyForm = reactive(emptyPolicyForm())
let generation = 0
let poller = null

function emptyPolicyForm() {
  return {
    schema_version: "world_validation_policy.v1",
    enabled: true,
    policy_version: "project-v1",
    semantic_enabled: false,
    rules: [],
    required_questions: [],
    packet_character_limit: 32000,
    max_packets: 24,
    max_input_characters: 800000,
    max_output_tokens_per_packet: 1500,
    per_packet_timeout_seconds: 180,
    frontmatter_schemas: {},
  }
}

const busy = computed(() => ["queued", "running"].includes(run.value?.status) || Boolean(pendingScope.value))
const findings = computed(() => Array.isArray(run.value?.findings) ? run.value.findings : [])
const decisionCount = computed(() => findings.value.filter((item) => item.action === "AUTHOR-REQUIRED").length)
const gapCategories = new Set(["facet-gap", "pressure-not-run", "missing-world-state", "reproduction-loop-gap", "coupling-chain-gap", "situated-test-gap", "rule-economics-gap", "candidate-mountain"])
const gapCount = computed(() => findings.value.filter((item) => gapCategories.has(item.category)).length)
const omissionCount = computed(() => Number(run.value?.omissions?.length || 0))
const invalidatedCount = computed(() => omissionCount.value
  + findings.value.filter((item) => item.category === "downstream-invalidation-missing").length
  + (run.value?.status === "stale" ? 1 : 0))
const warningsAccepted = computed(() => Boolean(run.value?.warning_receipt?.receipt_hash))
const reviewRequired = computed(() => Number(run.value?.review?.required || 0))
const reviewDone = computed(() => Number(run.value?.review?.reviewed || 0))
const statusLabel = computed(() => runStatusLabel(run.value))
const statusHint = computed(() => run.value
  ? `${historyScopeLabel(run.value)} · ${formatTime(run.value.finished_at || run.value.created_at)}`
  : "尚无回执")
const gateClass = computed(() => ({ pass: "badge-canonical", warn: "badge-draft", block: "badge-failed" })[run.value?.gate] || "")
const targetLabel = computed(() => props.targetType === "world_adoption_package" ? "校验这份采用包" : "校验当前工作稿")
const fullRunLabel = computed(() => props.targetType === "world_adoption_package"
  ? "全面校验并准备采用"
  : props.requiresFullScope ? "全面校验并准备发布" : "全面校验")
const findingsPageCount = computed(() => Math.max(1, Math.ceil(findingsTotal.value / findingsPageSize)))
const packetProgress = computed(() => {
  const progress = run.value?.progress || {}
  const total = Number(progress.packets_planned || 0)
  const done = Number(progress.packets_completed || 0)
  if (!total) return null
  return { total, done }
})
const packetProgressPercent = computed(() => {
  if (!packetProgress.value) return 0
  return Math.min(100, Math.round((packetProgress.value.done / packetProgress.value.total) * 100))
})
const canContinue = computed(() => Boolean(
  run.value
  && !busy.value
  && (run.value.status === "failed" || (run.value.status === "completed" && (run.value.omissions || []).includes("semantic_budget_exceeded")))
))
const staleReasonLabel = computed(() => ({
  policy: "校验政策已变化",
  manifest: "校验范围内容已变化",
  dependency: "引用依赖已变化",
  target: "目标内容已变化",
})[run.value?.stale_reason] || "校验后资料已变化")
const actionOptions = ["CLOSE", "SPLIT", "KEEP-GATE", "CANDIDATE", "AUTHOR-REQUIRED"]
const operatorOptions = ["contains", "not_contains", "forbid_regex", "regex", "max_chars", "page_type_exists", "frontmatter_required", "field_equals", "numeric_tolerance"]
const gateOptions = ["structure", "ontology", "knowledge", "society", "experience", "history", "counterfactual", "narrative", "saturation"]

watch(() => props.initialRun, (value) => {
  run.value = value
  recoverPolling()
})
watch(() => props.policyStatus, (value) => {
  policy.value = value || { active: false }
})
watch(() => run.value?.id, () => {
  findingsPageNo.value = 1
  filterSeverity.value = ""
  filterAction.value = ""
  loadFindings()
})
watch(() => run.value?.status, (status) => {
  if (status === "completed" || status === "failed") loadFindings()
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

function openPolicyEditor() {
  const source = policy.value?.draft?.policy || policy.value?.policy || null
  const base = source ? JSON.parse(JSON.stringify(source)) : null
  Object.assign(policyForm, emptyPolicyForm(), base || {}, {
    rules: (base?.rules || []).map((rule) => ({ ...rule })),
    required_questions: (base?.required_questions || []).map((item) => ({ ...item })),
    policy_version: base?.policy_version || "project-v1",
  })
  policyError.value = ""
  policyEditorOpen.value = true
}

function addRule() {
  policyForm.rules.push({ rule_id: `rule-${policyForm.rules.length + 1}-${Date.now().toString(36)}`, operator: "contains", value: "", severity: "warning", message: "", page_type: null })
}

function addQuestion() {
  policyForm.required_questions.push({ question_id: `q-${policyForm.required_questions.length + 1}-${Date.now().toString(36)}`, gate: "knowledge", question: "" })
}

async function savePolicyDraft() {
  if (policySaving.value) return false
  policySaving.value = true
  policyError.value = ""
  try {
    const payload = {
      policy: {
        ...JSON.parse(JSON.stringify(policyForm)),
        rules: policyForm.rules.filter((rule) => rule.message && String(rule.value ?? "") !== ""),
        required_questions: policyForm.required_questions.filter((item) => item.question),
      },
      summary: `项目校验政策草稿：${policyForm.policy_version}`,
    }
    if (payload.policy.required_questions.length && !payload.policy.semantic_enabled) {
      policyError.value = "有必问项时必须启用语义审计。"
      return false
    }
    await api.world.saveWorldValidationPolicyDraft(props.projectId, payload)
    toast("政策工作稿已保存，发布《世界书校验策略》页后生效", "success")
    policyEditorOpen.value = false
    const status = await api.world.getWorldValidationPolicyStatus(props.projectId)
    policy.value = status
    emit("policy-updated", status)
    return true
  } catch (err) {
    policyError.value = err?.message || "无法保存政策工作稿。"
    return false
  } finally {
    policySaving.value = false
  }
}

function runStatusLabel(value) {
  if (!value) return "未运行"
  if (["queued", "running"].includes(value.status)) return "校验中"
  if (value.status === "failed") return "校验失败"
  if (value.status === "stale") return "已失效"
  return ({ pass: "已通过", warn: "有提示", block: "需修正" })[value.gate] || "已完成"
}
function historyScopeLabel(value) {
  if (value?.target_type === "semantic_gap") return "定向查漏"
  return value?.scope === "full" ? "全面校验" : "定向校验"
}
const actionLabel = (action) => ({ CLOSE: "必须修正", SPLIT: "需拆分理清", "KEEP-GATE": "请核对", CANDIDATE: "待补证据", "AUTHOR-REQUIRED": "需作者决定" })[action] || "请核对"
const dispositionLabel = (value) => ({ resolved: "已修正", acknowledged: "已知悉", deferred: "稍后再定" })[value] || value
const operatorLabel = (op) => ({ contains: "必须包含", not_contains: "不得包含", forbid_regex: "禁止匹配（禁区）", regex: "必须匹配", max_chars: "最多字符", page_type_exists: "页面类型必须存在", frontmatter_required: "前置字段必填", field_equals: "字段等于", numeric_tolerance: "数值容差" })[op] || op
const gateLabel = (gate) => ({ structure: "结构", ontology: "事实一致", knowledge: "知识层边界", society: "社会后果", experience: "日常经验", history: "历史演变", counterfactual: "反事实", narrative: "叙事影响", saturation: "饱和度" })[gate] || gate
const isReviewable = (finding) => finding.action === "AUTHOR-REQUIRED" || finding.severity === "warning"
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
    const confirmation = policy.value.semantic_enabled
      ? await confirmAiReference({
          novel_id: props.projectId,
          action: "world.validation.semantic",
          task: scope === "full" ? "全面校验当前世界书" : "校验当前世界书工作稿",
          scope: "world",
          include_pending_objects: false,
          ...(scope === "targeted" && props.targetType === "world_bible_draft"
            ? { selected_world_bible_draft_ids: [props.targetId] }
            : {}),
          budget_tokens: 12000,
        })
      : null
    const created = await api.world.createWorldValidationRun({
      novel_id: props.projectId,
      operation_id: createOperationId(),
      scope,
      trigger: "world_health",
      context_confirmation_id: confirmation?.id || undefined,
      ...(scope === "targeted" ? { target_type: props.targetType, target_id: props.targetId } : {}),
    })
    if (token !== generation) return false
    run.value = created
    emit("updated", created)
    startPolling(created)
    return true
  } catch (err) {
    if (err?.message === "已取消 AI 参考资料确认") return false
    if (token === generation) error.value = err?.message || "无法启动校验。"
    return false
  } finally {
    if (token === generation) pendingScope.value = ""
  }
}

async function startGapRun() {
  if (busy.value) return false
  if (!props.gapRoot?.id) {
    emit("gap-root-needed")
    return false
  }
  const token = ++generation
  pendingScope.value = "gap"
  error.value = ""
  stopPolling()
  try {
    const confirmation = policy.value.semantic_enabled
      ? await confirmAiReference({
          novel_id: props.projectId,
          action: "world.validation.semantic",
          task: `定向查漏：${props.gapRoot.label || "根对象"}及其声明的直接依赖`,
          scope: "world",
          include_pending_objects: false,
          ...(props.gapRoot.selected_world_bible_draft_ids?.length
            ? { selected_world_bible_draft_ids: props.gapRoot.selected_world_bible_draft_ids }
            : {}),
          budget_tokens: 12000,
        })
      : null
    const created = await api.world.createWorldValidationRun({
      novel_id: props.projectId,
      operation_id: createOperationId(),
      scope: "targeted",
      target_type: "semantic_gap",
      target_id: props.gapRoot.id,
      root_type: props.gapRoot.type,
      trigger: "world_health",
      context_confirmation_id: confirmation?.id || undefined,
    })
    if (token !== generation) return false
    run.value = created
    emit("updated", created)
    startPolling(created)
    toast("已发起定向语义查漏（根对象与一跳依赖）", "success")
    return true
  } catch (err) {
    if (err?.message === "已取消 AI 参考资料确认") return false
    if (token === generation) error.value = err?.message || "无法发起定向查漏。"
    return false
  } finally {
    if (token === generation) pendingScope.value = ""
  }
}

async function continueRun() {
  if (!canContinue.value || continuing.value || !run.value?.id) return false
  continuing.value = true
  error.value = ""
  try {
    const confirmation = policy.value.semantic_enabled
      ? await confirmAiReference({
          novel_id: props.projectId,
          action: "world.validation.semantic",
          task: "续接世界书校验（跳过已检查分片）",
          scope: "world",
          include_pending_objects: false,
          budget_tokens: 12000,
        })
      : null
    const continued = await api.world.continueWorldValidationRun(run.value.id, props.projectId, {
      context_confirmation_id: confirmation?.id || undefined,
    })
    run.value = continued
    emit("updated", continued)
    startPolling(continued)
    toast("已续接校验，已检查的分片不会重复执行", "success")
    return true
  } catch (err) {
    if (err?.message === "已取消 AI 参考资料确认") return false
    error.value = err?.message || "无法续接校验。"
    return false
  } finally {
    continuing.value = false
  }
}

async function loadFindings() {
  const runId = run.value?.id
  if (!runId) {
    pageFindings.value = []
    findingsTotal.value = 0
    dispositions.value = {}
    return
  }
  findingsLoading.value = true
  try {
    const result = await api.world.listWorldValidationFindings(runId, props.projectId, {
      page: findingsPageNo.value,
      page_size: findingsPageSize,
      ...(filterSeverity.value ? { severity: filterSeverity.value } : {}),
      ...(filterAction.value ? { action: filterAction.value } : {}),
    })
    pageFindings.value = result?.items || []
    findingsTotal.value = Number(result?.total || 0)
    dispositions.value = result?.dispositions || {}
  } catch {
    pageFindings.value = []
    findingsTotal.value = 0
  } finally {
    findingsLoading.value = false
  }
}

function resetFindingsPage() {
  findingsPageNo.value = 1
  loadFindings()
}

function turnFindingsPage(page) {
  findingsPageNo.value = Math.min(Math.max(1, page), findingsPageCount.value)
  loadFindings()
}

async function submitDisposition(finding, disposition) {
  if (!run.value?.id || reviewSubmitting.value) return false
  reviewSubmitting.value = finding.finding_id
  error.value = ""
  try {
    const updated = await api.world.createWorldValidationReviewItems(run.value.id, props.projectId, {
      items: [{ finding_id: finding.finding_id, disposition, note: "" }],
    })
    run.value = updated
    emit("updated", updated)
    await loadFindings()
    toast(`已记录复核：${dispositionLabel(disposition)}`, "success")
    return true
  } catch (err) {
    error.value = err?.message || "无法记录复核。"
    return false
  } finally {
    reviewSubmitting.value = ""
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

onMounted(() => {
  if (requestedRunId === run.value?.id) nextTick(() => {
    const target = panelRef.value?.querySelector("summary")
    target?.scrollIntoView?.({ block: "start" })
    target?.focus?.()
  })
  recoverPolling()
  loadFindings()
})
onBeforeUnmount(() => {
  generation += 1
  stopPolling()
})
</script>
