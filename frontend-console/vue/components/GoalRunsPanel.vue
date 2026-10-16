<template>
  <section class="goal-runs" aria-label="目标运行">
    <header class="goal-runs-header">
      <div>
        <h2>目标运行</h2>
        <p>把一件事拆成可检查的步骤；每次修改都由你决定。</p>
      </div>
      <button type="button" class="goal-runs-refresh" :disabled="loading || busy" @click="refresh">刷新</button>
    </header>

    <p v-if="loading" class="goal-runs-status" role="status">正在读取目标与预算…</p>
    <div v-if="error" class="goal-runs-error" role="alert">
      <p>{{ error }}</p>
      <button v-if="pendingStart" type="button" class="goal-runs-button" :disabled="busy" @click="submitStart(pendingStart)">恢复上次提交</button>
      <button v-else type="button" class="goal-runs-button" :disabled="busy || loading" @click="refresh">重新读取</button>
    </div>

    <nav v-if="recent.length > 1" class="goal-runs-history" aria-label="最近目标">
      <h3>最近目标</h3>
      <button
        v-for="item in recent"
        :key="item.run_id"
        type="button"
        :aria-current="goal?.run_id === item.run_id ? 'true' : undefined"
        :disabled="busy"
        @click="openGoal(item.run_id)"
      >
        <span>{{ item.goal || item.title || '目标运行' }}</span>
        <small>{{ item.status_label || statusLabel(item) }}</small>
      </button>
    </nav>

    <form v-if="!goal || !isActive(goal)" class="goal-runs-start" @submit.prevent="startGoal">
      <label for="goal-run-prompt">你想完成什么？</label>
      <textarea
        id="goal-run-prompt"
        v-model="goalText"
        rows="4"
        maxlength="6000"
        placeholder="例如：检查人物设定里相互矛盾的年龄，并列出需要我确认的修改。"
        :disabled="busy || Boolean(pendingStart)"
      />
      <fieldset class="goal-runs-budget">
        <legend>本目标预算</legend>
        <label>模型请求数
          <input v-model.number="startBudget.requests" type="number" min="2" :max="budgetLimits.requests_max || 100" :disabled="busy || Boolean(pendingStart)" />
        </label>
        <label>可能产生费用的请求数
          <input v-model.number="startBudget.possible_charge_requests" type="number" min="2" :max="budgetLimits.possible_charge_requests_max || 100" :disabled="busy || Boolean(pendingStart)" />
        </label>
        <label>模型令牌上限
          <input v-model.number="startBudget.tokens" type="number" min="512" :max="budgetLimits.tokens_max || 500000" step="1" :disabled="busy || Boolean(pendingStart)" />
        </label>
        <label>最长运行时间（分钟）
          <input v-model.number="startBudget.time_limit_minutes" type="number" min="1" :max="Math.floor((budgetLimits.time_limit_seconds_max || 7200) / 60)" :disabled="busy || Boolean(pendingStart)" />
        </label>
      </fieldset>
      <label class="goal-runs-consent">
        <input v-model="budgetAcknowledged" type="checkbox" :disabled="busy || Boolean(pendingStart)" />
        <span>我确认上面的额度。生成计划通常需要两次模型请求（选操作、编计划），并计入本目标预算；生成步骤另计。</span>
      </label>
      <button class="goal-runs-button goal-runs-button--primary" type="submit" :disabled="busy || loading || !goalText.trim() || !budgetAcknowledged">
        {{ busy ? '正在准备计划…' : pendingStart ? '恢复上次提交' : '生成并审阅计划' }}
      </button>
      <p v-if="capabilities.max_steps" class="goal-runs-help">最多 {{ capabilities.max_steps }} 步。可恢复的修改默认逐步确认；影响采用或正式内容的决定始终逐步确认。</p>
      <details v-if="capabilities.unavailable_operations?.length" class="goal-runs-help">
        <summary>{{ capabilities.unavailable_operations.length }} 项操作暂不能纳入目标计划</summary>
        <ul>
          <li v-for="item in capabilities.unavailable_operations" :key="item.operation_id">{{ item.label }}：{{ item.reason }}</li>
        </ul>
      </details>
    </form>

    <section v-if="goal" class="goal-runs-current" aria-label="当前目标">
      <header class="goal-runs-current-header">
        <div>
          <span class="goal-runs-eyebrow">{{ statusLabel(goal) }}</span>
          <h3>{{ goal.title || goal.goal || '目标运行' }}</h3>
          <p v-if="goal.summary">{{ goal.summary }}</p>
        </div>
        <span class="goal-runs-progress">{{ goal.progress?.completed || 0 }} / {{ goal.progress?.total || 0 }}</span>
      </header>

      <p v-if="goal.stop_reason" class="goal-runs-stop" role="status">
        <strong>{{ goal.stop_reason_label || '当前停点' }}</strong>
        <span>{{ goal.stop_reason }}</span>
      </p>

      <section v-if="goal.steps?.length" class="goal-runs-steps" aria-label="目标步骤">
        <h3>步骤与依赖</h3>
        <ol>
          <li v-for="step in goal.steps" :key="step.step_id">
            <div class="goal-runs-step-row">
              <strong>{{ step.label }}</strong>
              <span class="goal-runs-step-status">{{ step.status_label }}</span>
            </div>
            <p v-if="step.intent">{{ step.intent }}</p>
            <p v-if="step.dependency_labels?.length" class="goal-runs-dependencies">先完成：{{ step.dependency_labels.join('、') }}</p>
            <p v-if="step.preview_summary" class="goal-runs-preview">{{ step.preview_summary }}</p>
            <dl v-if="step.diff?.length" class="goal-runs-diff">
              <div v-for="change in step.diff" :key="change.field">
                <dt>{{ change.field }}</dt>
                <dd><span>{{ change.before }}</span><span aria-hidden="true">→</span><strong>{{ change.after }}</strong></dd>
              </div>
            </dl>
            <button v-if="step.can_confirm" type="button" class="goal-runs-button" :disabled="busy" @click="approveStep(step, true)">确认并执行这一步</button>
            <button v-if="step.can_confirm" type="button" class="goal-runs-link" :disabled="busy" @click="approveStep(step, false)">暂不采用这一步</button>
            <div v-if="step.can_reconcile" class="goal-runs-reconciliation">
              <p>先读取这一步保存的领域回执。系统不会重放操作；提交决定时会再次核对原任务与回执。没有明确证据时仍会阻断，已用额度也不会重置或返还。</p>
              <div v-if="receiptPreviewFor(step)" class="goal-runs-receipt" aria-live="polite">
                <strong>{{ receiptStatusLabel(receiptPreviewFor(step).status) }}</strong>
                <p>{{ receiptPreviewFor(step).summary }}</p>
                <ul v-if="receiptPreviewFor(step).details?.length">
                  <li v-for="(detail, index) in receiptPreviewFor(step).details" :key="index">{{ detail }}</li>
                </ul>
                <button
                  v-if="receiptPreviewFor(step).destination"
                  type="button"
                  class="goal-runs-link"
                  :disabled="busy"
                  @click="locateReceipt(receiptPreviewFor(step).destination)"
                >打开对应工作台</button>
              </div>
              <p v-if="receiptStateFor(step)?.error" class="goal-runs-error" role="status">{{ receiptStateFor(step).error }}</p>
              <button
                v-if="!receiptPreviewFor(step) || !['verified_applied', 'verified_not_applied'].includes(receiptPreviewFor(step).status)"
                type="button"
                class="goal-runs-button"
                :disabled="busy || receiptStateFor(step)?.loading"
                @click="readReceipt(step)"
              >{{ receiptStateFor(step)?.loading ? '正在读取原回执…' : receiptPreviewFor(step) ? '重新读取原回执' : receiptStateFor(step)?.error ? '重试读取原回执' : '读取原回执' }}</button>
              <button
                v-if="receiptPreviewFor(step)?.available_decisions?.includes('applied')"
                type="button"
                class="goal-runs-button"
                :disabled="busy"
                @click="reconcileStep(step, 'applied')"
              >确认：原操作已完成</button>
              <button
                v-if="receiptPreviewFor(step)?.available_decisions?.includes('not_applied')"
                type="button"
                class="goal-runs-link"
                :disabled="busy"
                @click="reconcileStep(step, 'not_applied')"
              >确认：原操作未应用</button>
              <button type="button" class="goal-runs-link" :disabled="busy" @click="reconcileStep(step, 'still_unknown')">仍无法确认</button>
            </div>
          </li>
        </ol>
      </section>

      <form v-if="canEditPlan" class="goal-runs-plan" @submit.prevent="approvePlan">
        <h3>{{ goal.phase === 'scope_expanded' ? '核对变更后的计划' : '审阅计划' }}</h3>
        <p>步骤顺序、依赖和每项预览都来自当前项目；你可以删改后再确认。</p>
        <p v-if="hasUnsupportedParameters" class="goal-runs-error" role="alert">有些目录选项还不能在此确认；请删掉相关步骤或到原工作台处理。</p>
        <label class="goal-runs-field">计划标题
          <input v-model="planDraft.title" maxlength="180" :disabled="busy" />
        </label>
        <label class="goal-runs-field">计划说明
          <textarea v-model="planDraft.summary" rows="2" maxlength="1600" :disabled="busy" />
        </label>
        <GoalPlanStep
          v-for="(planStep, index) in planDraft.steps"
          :key="planStep.step_id"
          :step-view="stepViewFor(planStep)"
          :plan-step="planStep"
          :index="index"
          :previous-steps="previousViews(index)"
          :disabled="busy"
          @update="updatePlanValue"
          @remove="removePlanStep"
          @remove-parameter="removePlanParameter"
        />
        <p v-if="!planDraft.steps.length" class="goal-runs-error" role="alert">计划至少保留一步。删除后请重新规划，或开始另一目标。</p>
        <fieldset class="goal-runs-budget">
          <legend>确认预算</legend>
          <label>模型请求数
            <input v-model.number="planBudget.requests" type="number" min="2" :max="budgetLimits.requests_max || 100" :disabled="busy" />
          </label>
          <label>可能产生费用的请求数
            <input v-model.number="planBudget.possible_charge_requests" type="number" min="2" :max="budgetLimits.possible_charge_requests_max || 100" :disabled="busy" />
          </label>
          <label>模型令牌上限
            <input v-model.number="planBudget.tokens" type="number" min="512" :max="budgetLimits.tokens_max || 500000" step="1" :disabled="busy" />
          </label>
          <label>最长运行时间（分钟）
            <input v-model.number="planBudget.time_limit_minutes" type="number" min="1" :max="approvalTimeLimitMinutes" :disabled="busy" />
          </label>
        </fieldset>
        <label class="goal-runs-consent goal-runs-consent--r2">
          <input v-model="autoR2" type="checkbox" :disabled="busy" />
          <span>允许本目标自动执行有明确恢复入口的修改；其他修改仍会停下来逐步确认。</span>
        </label>
        <button class="goal-runs-button goal-runs-button--primary" type="submit" :disabled="busy || !planCanSubmit">
          {{ busy ? '正在重新核对…' : '确认计划并开始' }}
        </button>
      </form>

      <section v-if="goal.replan_changes?.length" class="goal-runs-change-review" aria-label="计划范围变更">
        <h3>范围变更</h3>
        <ul><li v-for="change in goal.replan_changes" :key="change.reason">{{ change.label }}</li></ul>
      </section>

      <section v-if="goal.changes?.length" class="goal-runs-change-list" aria-label="可恢复的修改">
        <h3>修改清单</h3>
        <ul>
          <li v-for="change in goal.changes" :key="`${change.label}-${change.state}`">
            <strong>{{ change.label }}</strong>
            <span>{{ change.state_label }}</span>
            <p>{{ change.summary }}</p>
          </li>
        </ul>
        <button v-if="goal.can_restore" type="button" class="goal-runs-button" :disabled="busy" @click="restoreChanges">恢复可恢复的修改</button>
        <p v-if="goal.can_restore" class="goal-runs-help">恢复会按领域版本核对；若你后来编辑了资料，系统会停下且不会覆盖。</p>
      </section>

      <section v-if="goal.can_resume" class="goal-runs-resume">
        <h3>继续目标</h3>
        <p>已用预算不会清零。未知计费回执必须先核对，时限不能延长。</p>
        <fieldset class="goal-runs-budget">
          <legend>新的总额度</legend>
          <label>模型请求数
            <input v-model.number="resumeBudget.requests" type="number" :min="goal.budget?.used?.requests || 2" :max="budgetLimits.requests_max || 100" :disabled="busy" />
          </label>
          <label>可能产生费用的请求数
            <input v-model.number="resumeBudget.possible_charge_requests" type="number" :min="Math.max(2, goal.budget?.used?.requests || 0)" :max="budgetLimits.possible_charge_requests_max || 100" :disabled="busy" />
          </label>
          <label>模型令牌上限
            <input v-model.number="resumeBudget.tokens" type="number" :min="goal.budget?.used?.tokens || 512" :max="budgetLimits.tokens_max || 500000" step="1" :disabled="busy" />
          </label>
          <label>最长运行时间（分钟）
            <input v-model.number="resumeBudget.time_limit_minutes" type="number" min="1" :max="Math.floor((goal.budget?.initial_limits?.time_limit_seconds || 7200) / 60)" :disabled="busy" />
          </label>
        </fieldset>
        <button type="button" class="goal-runs-button goal-runs-button--primary" :disabled="busy" @click="resumeGoal">按新总额度继续</button>
      </section>

      <form v-if="goal.can_replan" class="goal-runs-replan" @submit.prevent="replanGoal">
        <label class="goal-runs-field">重新规划的原因
          <textarea v-model="replanReason" rows="2" maxlength="1200" placeholder="说明你希望调整的剩余事项" :disabled="busy" />
        </label>
        <button type="submit" class="goal-runs-button" :disabled="busy || !replanReason.trim()">重新规划剩余步骤</button>
      </form>

      <section v-if="goal.can_pause || goal.can_advance || goal.can_cancel" class="goal-runs-actions">
        <button v-if="goal.can_pause" type="button" class="goal-runs-button" :disabled="busy" @click="pauseGoal">暂停并保存进度</button>
        <button v-if="goal.can_advance" type="button" class="goal-runs-button goal-runs-button--primary" :disabled="busy" @click="advanceGoal">继续已保存步骤</button>
        <button v-if="goal.can_cancel" type="button" class="goal-runs-link goal-runs-link--danger" :disabled="busy" @click="cancelGoal">取消后续步骤</button>
        <p v-if="goal.can_cancel" class="goal-runs-help">取消不会撤销已完成修改；修改清单仍可查看和恢复。</p>
      </section>

      <details v-if="goal.diagnostics?.planning_error" class="goal-runs-diagnostics">
        <summary>查看诊断信息</summary>
        <p>计划暂未生成。错误类别：{{ diagnosticLabel(goal.diagnostics.planning_error) }}</p>
      </details>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../bridge/index.js"
import { locateAssistantSource } from "../shared/assistantNavigation.js"
import GoalPlanStep from "./GoalPlanStep.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  sourceSessionId: { type: String, default: null },
  active: { type: Boolean, default: false },
})
const emit = defineEmits(["availability"])

const capabilities = ref({})
const recent = ref([])
const goal = ref(null)
const planDraft = ref(null)
const goalText = ref("")
const startBudget = ref(defaultBudget())
const planBudget = ref(defaultBudget())
const resumeBudget = ref(defaultBudget())
const budgetAcknowledged = ref(false)
const autoR2 = ref(false)
const replanReason = ref("")
const loading = ref(false)
const busy = ref(false)
const error = ref("")
const receiptStates = ref({})
const pendingStart = ref(null)
const draftGoalRunId = ref(null)
const requestGeneration = ref(0)
const drafts = new Map()
let disposed = false

const budgetLimits = computed(() => capabilities.value.budget_limits || {})
const canEditPlan = computed(() => Boolean(
  goal.value?.can_approve_plan && planDraft.value,
))
const hasUnsupportedParameters = computed(() => Boolean(
  planDraft.value?.steps?.some(step => hasLockedFields(stepViewFor(step).fields)),
))
const planCanSubmit = computed(() => Boolean(
  planDraft.value?.steps?.length
  && !hasUnsupportedParameters.value
  && planDraft.value.steps.every(step => step.operation_id !== "project.update_task"
    || Object.keys(step.parameters?.changes || {}).length > 0),
))
const approvalTimeLimitMinutes = computed(() => Math.min(
  Math.floor((budgetLimits.value.time_limit_seconds_max || 7200) / 60),
  Math.floor((goal.value?.budget?.initial_limits?.time_limit_seconds || 7200) / 60),
))

function defaultBudget() {
  return {
    requests: 8,
    possible_charge_requests: 8,
    tokens: 12000,
    time_limit_minutes: 20,
  }
}

function hasLockedFields(fields = []) {
  return fields.some(field => Boolean(
    field.locked_reason || hasLockedFields(field.children || []),
  ))
}

function api() {
  return getApi()?.assistant || null
}

function owned(token) {
  return !disposed
    && token.generation === requestGeneration.value
    && token.projectId === props.projectId
}

function snapshot() {
  return { projectId: props.projectId, generation: requestGeneration.value }
}

function receiptStateKey(step) {
  return `${goal.value?.run_id || ""}:${step.step_id}:${goal.value?.revision || ""}`
}

function receiptStateFor(step) {
  return receiptStates.value[receiptStateKey(step)] || null
}

function receiptPreviewFor(step) {
  return receiptStateFor(step)?.preview || null
}

function receiptStatusLabel(status) {
  return ({
    verified_applied: "原领域回执已核实为已完成",
    verified_not_applied: "原领域回执已核实为未应用",
    incomplete: "原领域结果尚不完整",
    stale: "原领域结果已过期",
    unverified: "原领域结果仍无法确认",
  })[status] || "原领域结果仍无法确认"
}

async function readReceipt(step) {
  const token = snapshot()
  const runId = goal.value?.run_id
  const expectedRevision = goal.value?.revision
  const stateKey = receiptStateKey(step)
  if (!runId || !Number.isInteger(expectedRevision) || !owned(token) || !api()) return
  receiptStates.value = { ...receiptStates.value, [stateKey]: { loading: true } }
  try {
    const preview = await api().goalStepReceiptPreview(
      token.projectId,
      runId,
      step.step_id,
      expectedRevision,
    )
    if (!owned(token) || goal.value?.run_id !== runId || goal.value?.revision !== expectedRevision) return
    receiptStates.value = { ...receiptStates.value, [stateKey]: { preview } }
  } catch {
    if (!owned(token) || goal.value?.run_id !== runId || goal.value?.revision !== expectedRevision) return
    receiptStates.value = {
      ...receiptStates.value,
      [stateKey]: { error: "暂时无法读取原回执；结果仍保持未知，可重试或继续保持阻断。" },
    }
  }
}

function locateReceipt(destination) {
  if (!destination) return false
  const source = destination.kind === "writing_candidate"
    ? { type: destination.kind, id: destination.candidate_id, chapter_index: destination.chapter_index }
    : destination.kind === "smart_dedup_scan"
      ? { type: destination.kind, task_id: destination.task_id }
      : destination.kind === "scene_story_assets"
        ? { type: destination.kind, scene_id: destination.scene_id }
        : null
  return source ? locateAssistantSource(source) : false
}

function saveDraft(projectId = props.projectId) {
  if (!projectId) return
  drafts.set(projectId, {
    goalText: goalText.value,
    startBudget: { ...startBudget.value },
    planBudget: { ...planBudget.value },
    resumeBudget: { ...resumeBudget.value },
    budgetAcknowledged: budgetAcknowledged.value,
    autoR2: autoR2.value,
    replanReason: replanReason.value,
    planDraft: clone(planDraft.value),
    pendingStart: clone(pendingStart.value),
    goalRunId: draftGoalRunId.value,
  })
}

function restoreDraft(projectId) {
  const draft = drafts.get(projectId)
  goalText.value = draft?.goalText || ""
  startBudget.value = { ...defaultBudget(), ...(draft?.startBudget || {}) }
  planBudget.value = { ...defaultBudget(), ...(draft?.planBudget || {}) }
  resumeBudget.value = { ...defaultBudget(), ...(draft?.resumeBudget || {}) }
  budgetAcknowledged.value = draft?.budgetAcknowledged === true
  autoR2.value = draft?.autoR2 === true
  replanReason.value = draft?.replanReason || ""
  planDraft.value = clone(draft?.planDraft)
  pendingStart.value = clone(draft?.pendingStart)
  draftGoalRunId.value = draft?.goalRunId || null
}

function clone(value) {
  return value == null ? null : JSON.parse(JSON.stringify(value))
}

function budgetPayload(value) {
  return {
    requests: Number(value.requests),
    possible_charge_requests: Number(value.possible_charge_requests),
    tokens: Number(value.tokens),
    time_limit_seconds: Number(value.time_limit_minutes) * 60,
  }
}

function budgetView(value) {
  return {
    requests: Number(value?.requests || 0),
    possible_charge_requests: Number(value?.possible_charge_requests || 0),
    tokens: Number(value?.tokens || 0),
    time_limit_minutes: Math.ceil(Number(value?.time_limit_seconds || 0) / 60),
  }
}

function statusLabel(value) {
  const statuses = {
    pending: "等待处理",
    running: "正在执行",
    waiting_approval: "等待你确认",
    completed: "已完成",
    failed: "未完成",
    cancelled: "已取消",
    budget_exceeded: "预算停点",
  }
  return statuses[value?.status] || "已保存"
}

function isActive(value) {
  return ["pending", "running", "waiting_approval"].includes(value?.status)
}

function setGoal(value, { preservePlan = false } = {}) {
  goal.value = value
  const sameRun = value?.run_id && value.run_id === draftGoalRunId.value
  if (!preservePlan || !sameRun || !planDraft.value) {
    planDraft.value = clone(value?.plan)
    planBudget.value = budgetView(value?.budget?.limits)
    autoR2.value = value?.auto_r2 === true
  }
  draftGoalRunId.value = value?.run_id || null
  if (value?.budget?.limits) resumeBudget.value = budgetView(value.budget.limits)
  if (!preservePlan) replanReason.value = ""
  saveDraft()
}

async function load(projectId) {
  requestGeneration.value += 1
  const token = snapshot()
  goal.value = null
  recent.value = []
  capabilities.value = {}
  error.value = ""
  busy.value = false
  loading.value = false
  restoreDraft(projectId)
  emit("availability", false)
  if (!projectId || !api()) return
  loading.value = true
  try {
    const result = await api().goalCapabilities(projectId)
    if (!owned(token)) return
    capabilities.value = result || {}
    emit("availability", result?.enabled === true)
    if (!result?.enabled) return
    const items = await api().recentGoals(projectId)
    if (!owned(token)) return
    recent.value = Array.isArray(items) ? items : []
    const selected = recent.value.find(isActive) || recent.value[0] || null
    if (selected) {
      goal.value = selected
      if (draftGoalRunId.value !== selected.run_id || !planDraft.value) {
        planDraft.value = clone(selected.plan)
        planBudget.value = budgetView(selected.budget?.limits)
        autoR2.value = selected.auto_r2 === true
      }
      draftGoalRunId.value = selected.run_id
      if (selected.budget?.limits) resumeBudget.value = budgetView(selected.budget.limits)
    }
  } catch (cause) {
    if (owned(token)) error.value = readableError(cause)
  } finally {
    if (owned(token)) loading.value = false
  }
}

async function refresh({ preservePlan = true } = {}) {
  const token = snapshot()
  if (!token.projectId || !api()) return
  receiptStates.value = {}
  loading.value = true
  error.value = ""
  try {
    const items = await api().recentGoals(token.projectId)
    if (!owned(token)) return
    recent.value = Array.isArray(items) ? items : []
    const activeGoal = recent.value.find(isActive)
    const selected = activeGoal || recent.value.find(item => item.run_id === goal.value?.run_id) || recent.value[0] || null
    if (selected) {
      setGoal(selected, { preservePlan })
    } else {
      goal.value = null
    }
  } catch (cause) {
    if (owned(token)) error.value = readableError(cause)
  } finally {
    if (owned(token)) loading.value = false
  }
}

function readableError(cause) {
  if (Number(cause?.status) === 409) {
    return "目标状态已更新。服务器进度已刷新；未提交的目标和计划草稿仍保留。"
  }
  return cause?.message || "目标暂时无法读取，请重试。"
}

async function startGoal() {
  if (pendingStart.value) return submitStart(pendingStart.value)
  if (!goalText.value.trim() || !budgetAcknowledged.value || busy.value) return
  const payload = {
    novel_id: props.projectId,
    request_id: globalThis.crypto.randomUUID(),
    goal: goalText.value.trim(),
    budget: budgetPayload(startBudget.value),
    ...(props.sourceSessionId ? { source_session_id: props.sourceSessionId } : {}),
  }
  pendingStart.value = payload
  saveDraft()
  return submitStart(payload)
}

async function submitStart(payload) {
  const token = snapshot()
  if (!owned(token) || busy.value || !api()) return
  busy.value = true
  error.value = ""
  try {
    const result = await api().startGoal(payload)
    if (!owned(token)) return
    pendingStart.value = null
    goalText.value = ""
    budgetAcknowledged.value = false
    recent.value = [result, ...recent.value.filter(item => item.run_id !== result.run_id)]
    setGoal(result)
  } catch (cause) {
    if (!owned(token)) return
    const message = readableError(cause)
    if (Number(cause?.status) === 409) {
      await refresh({ preservePlan: true })
      if (owned(token)) error.value = message
    } else {
      error.value = message
    }
  } finally {
    if (owned(token)) {
      busy.value = false
      saveDraft()
    }
  }
}

async function openGoal(runId) {
  const token = snapshot()
  if (!owned(token) || busy.value || !api()) return
  busy.value = true
  error.value = ""
  try {
    const result = await api().goal(token.projectId, runId)
    if (!owned(token)) return
    setGoal(result)
  } catch (cause) {
    if (owned(token)) error.value = readableError(cause)
  } finally {
    if (owned(token)) busy.value = false
  }
}

function stepViewFor(planStep) {
  return goal.value?.steps?.find(item => item.step_id === planStep.step_id) || {
    step_id: planStep.step_id,
    label: "步骤",
    description: "目录说明暂不可用",
    risk: "R4",
    risk_label: "需确认",
    fields: [],
    target_count: 0,
    depends_on_count: planStep.depends_on?.length || 0,
  }
}

function previousViews(index) {
  return (planDraft.value?.steps || [])
    .filter((_step, stepIndex) => stepIndex !== index)
    .map(step => stepViewFor(step))
}

function updatePlanValue({ stepId, path, value }) {
  if (!planDraft.value) return
  const step = planDraft.value.steps.find(item => item.step_id === stepId)
  if (!step) return
  let target = step
  for (const key of path.slice(0, -1)) {
    if (!target[key] || typeof target[key] !== "object") target[key] = {}
    target = target[key]
  }
  target[path.at(-1)] = value
  saveDraft()
}

function removePlanParameter({ stepId, path }) {
  const step = planDraft.value?.steps.find(item => item.step_id === stepId)
  if (!step) return
  let target = step
  for (const key of path.slice(0, -1)) target = target?.[key]
  if (target && path.length) delete target[path.at(-1)]
  saveDraft()
}

function removePlanStep(stepId) {
  if (!planDraft.value) return
  const removed = new Set([stepId])
  let changed = true
  while (changed) {
    changed = false
    for (const step of planDraft.value.steps) {
      if (removed.has(step.step_id)) continue
      if ((step.depends_on || []).some(id => removed.has(id))) {
        removed.add(step.step_id)
        changed = true
      }
    }
  }
  planDraft.value.steps = planDraft.value.steps.filter(step => !removed.has(step.step_id))
  saveDraft()
}

function operationPlan() {
  return {
    ...planDraft.value,
    steps: planDraft.value.steps.map(step => ({
      ...step,
      depends_on: [...(step.depends_on || [])],
      targets: [...(step.targets || [])],
      parameters: clone(step.parameters || {}),
    })),
  }
}

async function runAction(method, payload, { preservePlan = false } = {}) {
  const token = snapshot()
  const runId = goal.value?.run_id
  if (!runId || !owned(token) || busy.value || !api()) return
  busy.value = true
  error.value = ""
  try {
    const result = await method(token.projectId, runId, payload)
    if (!owned(token)) return
    setGoal(result, { preservePlan })
    recent.value = [result, ...recent.value.filter(item => item.run_id !== result.run_id)]
  } catch (cause) {
    if (!owned(token)) return
    const message = readableError(cause)
    if (Number(cause?.status) === 409) {
      await refresh({ preservePlan: true })
      if (owned(token)) error.value = message
    } else {
      error.value = message
    }
  } finally {
    if (owned(token)) {
      busy.value = false
      saveDraft()
    }
  }
}

function approvePlan() {
  if (!goal.value || !planDraft.value) return
  return runAction(api().approveGoal, {
    expected_revision: goal.value.revision,
    plan: operationPlan(),
    budget: budgetPayload(planBudget.value),
    auto_r2: autoR2.value === true,
  })
}

function approveStep(step, approve) {
  if (!goal.value) return
  const body = {
    expected_revision: goal.value.revision,
    step_id: step.step_id,
    approve,
  }
  return runAction((projectId, id, payload) => api().approveGoalStep(projectId, id, step.step_id, payload), body)
}

function reconcileStep(step, decision) {
  if (!goal.value) return
  if (decision !== "still_unknown" && !receiptPreviewFor(step)?.available_decisions?.includes(decision)) return
  return runAction((projectId, id, payload) => api().reconcileGoalStep(projectId, id, step.step_id, payload), {
    expected_revision: goal.value.revision,
    decision,
  }, { preservePlan: true })
}

function advanceGoal() {
  return runAction(api().advanceGoal, { expected_revision: goal.value?.revision })
}

function pauseGoal() {
  return runAction(api().pauseGoal, { expected_revision: goal.value?.revision }, { preservePlan: true })
}

function resumeGoal() {
  return runAction(api().resumeGoal, {
    expected_revision: goal.value?.revision,
    budget: budgetPayload(resumeBudget.value),
  })
}

function cancelGoal() {
  return runAction(api().cancelGoal, { expected_revision: goal.value?.revision }, { preservePlan: true })
}

function replanGoal() {
  return runAction(api().replanGoal, {
    expected_revision: goal.value?.revision,
    reason: replanReason.value.trim(),
  })
}

function restoreChanges() {
  return runAction(api().restoreGoal, { expected_revision: goal.value?.revision }, { preservePlan: true })
}

function diagnosticLabel(code) {
  const labels = {
    ValidationError: "计划格式或参数未通过校验",
    ConflictError: "目录或项目状态发生变化",
    AIRunBudgetExceededError: "达到预算边界",
    interrupted: "请求被中断",
  }
  return labels[code] || "请求未完成"
}

watch(() => props.projectId, (value, previous) => {
  if (previous) saveDraft(previous)
  void load(value)
}, { immediate: true })
watch(() => props.active, value => { if (value && capabilities.value.enabled) void refresh() })
watch(
  [goalText, startBudget, planBudget, resumeBudget, budgetAcknowledged, autoR2, replanReason],
  () => saveDraft(),
  { deep: true },
)
onBeforeUnmount(() => { disposed = true; requestGeneration.value += 1; saveDraft() })
</script>

<style scoped>
.goal-runs{height:100%;min-height:0;overflow-y:auto;padding:16px 18px 24px;overscroll-behavior:contain;color:var(--text-primary);background:var(--bg-primary,var(--bg-base))}
.goal-runs-header,.goal-runs-current-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.goal-runs-header h2,.goal-runs-current-header h3{margin:0;font-size:18px;line-height:1.35}
.goal-runs-header p,.goal-runs-current-header p{margin:5px 0 0;color:var(--text-secondary);font-size:13px;line-height:1.5}
.goal-runs-refresh,.goal-runs-button,.goal-runs-link{min-height:40px;padding:8px 12px;border:1px solid var(--border-color,var(--border));border-radius:8px;background:var(--bg-muted);color:inherit;font:inherit;cursor:pointer}
.goal-runs-button--primary{border-color:var(--accent,#5967d8);background:var(--accent,#5967d8);color:white;font-weight:600}
.goal-runs-button:disabled,.goal-runs-refresh:disabled,.goal-runs-link:disabled{opacity:.55;cursor:not-allowed}
.goal-runs-link{border:0;background:transparent;text-decoration:underline}.goal-runs-link--danger{color:var(--danger,#b42318)}
.goal-runs-status,.goal-runs-help{color:var(--text-secondary);font-size:12px;line-height:1.55}
.goal-runs-error{padding:10px 12px;border:1px solid color-mix(in srgb,var(--danger,#b42318) 35%,var(--border));border-radius:8px;color:var(--danger,#b42318);line-height:1.5;overflow-wrap:anywhere}
.goal-runs-error p{margin:0 0 8px}
.goal-runs-history{display:grid;gap:6px;margin:14px 0;padding:12px;border:1px solid var(--border-color,var(--border));border-radius:10px}
.goal-runs-history h3{margin:0;font-size:13px}.goal-runs-history button{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}
.goal-runs-history button[aria-current=true]{font-weight:700}.goal-runs-history small{flex:0 0 auto;color:var(--text-secondary)}
.goal-runs-start,.goal-runs-plan,.goal-runs-resume,.goal-runs-replan{display:grid;gap:14px;margin:16px 0;padding:16px;border:1px solid var(--border-color,var(--border));border-radius:12px;background:var(--bg-muted)}
.goal-runs-start>label:first-child,.goal-runs-field{display:grid;gap:6px;font-size:14px;font-weight:600}
.goal-runs-start textarea,.goal-runs-field input,.goal-runs-field textarea,.goal-runs-budget input{box-sizing:border-box;width:100%;min-width:0;min-height:40px;padding:9px 10px;border:1px solid var(--border-color,var(--border));border-radius:8px;background:var(--bg-primary,var(--bg-base));color:inherit;font:inherit;line-height:1.5}
.goal-runs-start textarea,.goal-runs-field textarea{resize:vertical}
.goal-runs-budget{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:12px;border:1px solid var(--border-color,var(--border));border-radius:10px}
.goal-runs-budget legend{padding:0 5px;font-size:13px;font-weight:700}
.goal-runs-budget label{display:grid;gap:5px;min-width:0;color:var(--text-secondary);font-size:12px}
.goal-runs-consent{display:flex;align-items:flex-start;gap:9px;font-size:12px;line-height:1.55}.goal-runs-consent input{flex:0 0 18px;width:18px;height:18px;margin:0}
.goal-runs-current{display:grid;gap:16px;margin-top:18px}
.goal-runs-current-header{padding-bottom:12px;border-bottom:1px solid var(--border-color,var(--border))}
.goal-runs-eyebrow{display:block;margin-bottom:5px;color:var(--text-secondary);font-size:12px}
.goal-runs-progress{flex:0 0 auto;padding:5px 9px;border-radius:999px;background:var(--bg-muted);font-size:12px;font-weight:700}
.goal-runs-stop{display:grid;gap:5px;margin:0;padding:12px;border-left:3px solid var(--warning,#b7791f);border-radius:0 8px 8px 0;background:var(--bg-muted);line-height:1.5}
.goal-runs-stop strong{font-size:13px}.goal-runs-stop span{font-size:13px}
.goal-runs-steps,.goal-runs-change-review,.goal-runs-change-list{display:grid;gap:10px}.goal-runs-steps h3,.goal-runs-change-review h3,.goal-runs-change-list h3,.goal-runs-resume h3{margin:0;font-size:15px}
.goal-runs-steps ol,.goal-runs-change-list ul,.goal-runs-change-review ul{display:grid;gap:10px;margin:0;padding-left:22px}
.goal-runs-steps li,.goal-runs-change-list li{padding-left:2px;line-height:1.5}
.goal-runs-step-row{display:flex;justify-content:space-between;gap:8px;align-items:baseline}.goal-runs-step-row strong{overflow-wrap:anywhere}.goal-runs-step-status{flex:0 0 auto;color:var(--text-secondary);font-size:12px}
.goal-runs-steps li p{margin:5px 0;color:var(--text-secondary);font-size:13px;overflow-wrap:anywhere}
.goal-runs-steps li .goal-runs-preview{color:var(--text-primary)}
.goal-runs-reconciliation{display:grid;justify-items:start;gap:7px;margin-top:8px;padding:10px;border:1px solid var(--border-color,var(--border));border-radius:9px;background:var(--bg-muted)}
.goal-runs-reconciliation>p{margin:0!important;color:var(--text-secondary)}
.goal-runs-receipt{display:grid;gap:5px;width:100%;padding:9px;border-radius:7px;background:var(--bg-primary,var(--bg-base));line-height:1.5;overflow-wrap:anywhere}
.goal-runs-receipt>p{margin:0!important;color:var(--text-primary)!important}
.goal-runs-receipt ul{display:grid;gap:4px;margin:0;padding-left:20px;color:var(--text-secondary);font-size:13px}
.goal-runs-receipt li{padding:0!important}
.goal-runs-dependencies{font-size:12px!important}
.goal-runs-diff{display:grid;gap:7px;margin:8px 0}.goal-runs-diff div{display:grid;gap:3px}.goal-runs-diff dt{color:var(--text-secondary);font-size:12px}.goal-runs-diff dd{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:7px;margin:0;font-size:12px;overflow-wrap:anywhere}.goal-runs-diff strong{font-weight:700}
.goal-runs-plan>h3,.goal-runs-plan>p{margin:0}.goal-runs-plan>p{color:var(--text-secondary);font-size:13px;line-height:1.5}
.goal-runs-change-list li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 8px}.goal-runs-change-list li strong{overflow-wrap:anywhere}.goal-runs-change-list li span{color:var(--text-secondary);font-size:12px}.goal-runs-change-list li p{grid-column:1/-1;margin:0;color:var(--text-secondary);font-size:12px}
.goal-runs-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.goal-runs-actions .goal-runs-help{flex-basis:100%;margin:0}
.goal-runs-diagnostics{font-size:12px;color:var(--text-secondary)}.goal-runs-diagnostics summary{cursor:pointer;min-height:36px;line-height:36px}
@media(max-width:520px){.goal-runs{padding:12px 12px max(20px,env(safe-area-inset-bottom))}.goal-runs-budget{grid-template-columns:minmax(0,1fr)}.goal-runs-start,.goal-runs-plan,.goal-runs-resume,.goal-runs-replan{padding:12px}.goal-runs-header p{max-width:23rem}.goal-runs-current-header{gap:8px}.goal-runs-history button{align-items:flex-start}.goal-runs-diff dd{grid-template-columns:minmax(0,1fr);gap:2px}.goal-runs-diff dd span:nth-child(2){display:none}}
</style>
