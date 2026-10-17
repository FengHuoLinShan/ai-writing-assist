<template>
  <article class="exploration-result-card" :class="`exploration-result-card--${scaleClass}`" aria-label="探索结果">
    <header class="exploration-result-card__header">
      <strong>{{ title }}</strong>
      <span class="exploration-result-card__scale">{{ scaleLabel }}</span>
      <span v-if="savedEdit" class="exploration-result-card__badge">已保存编辑</span>
    </header>
    <p v-if="question" class="exploration-result-card__question">{{ question }}</p>

    <!-- 沙盘：影响链 + 成立条件 + 未知 -->
    <section v-if="isSandbox" class="exploration-result-card__body">
      <ol class="exploration-result-card__chain">
        <li v-for="(link, index) in sandboxLinks" :key="index">
          <p><strong>{{ link.condition || "未写明条件" }}</strong> → {{ link.effect }}</p>
          <p v-if="link.mechanism" class="exploration-result-card__basis">机理：{{ link.mechanism }}</p>
          <p v-if="link.affected?.length" class="exploration-result-card__basis">受影响：{{ link.affected.join("、") }}</p>
          <p v-if="link.holds_when" class="exploration-result-card__basis">成立条件：{{ link.holds_when }}</p>
          <p v-if="link.unknown" class="exploration-result-card__unknown">未知：{{ link.unknown }}</p>
          <button v-if="lockAvailable && revisableItem(`chain:${index}`)" type="button" class="exploration-result-card__lock" :class="{ 'exploration-result-card__lock--on': isItemLocked(`chain:${index}`) }" :aria-pressed="isItemLocked(`chain:${index}`)" :disabled="lockBusyKey === `chain:${index}`" @click="toggleLock(revisableItem(`chain:${index}`))">{{ lockLabel(`chain:${index}`) }}</button>
        </li>
      </ol>
      <p v-if="display.preconditions?.length" class="exploration-result-card__basis">前提条件：{{ display.preconditions.join("；") }}</p>
    </section>

    <!-- 事件：诊断缺口；补桥显示候选路径；导向显示行动—响应—后果链；无解列出缺项 -->
    <section v-else-if="isEvent" class="exploration-result-card__body">
      <p class="exploration-result-card__mode">{{ eventModeLabel }}</p>
      <ul v-if="eventGaps.length" class="exploration-result-card__list">
        <li v-for="(gap, index) in eventGaps" :key="`gap:${index}`">
          <p>{{ gap.description }}</p>
          <p v-if="gap.why_needed" class="exploration-result-card__basis">为什么需要：{{ gap.why_needed }}</p>
          <p v-if="gap.possible_fix_hint" class="exploration-result-card__basis">可能的补法：{{ gap.possible_fix_hint }}</p>
          <button v-if="lockAvailable && revisableItem(`gap:${index}`)" type="button" class="exploration-result-card__lock" :class="{ 'exploration-result-card__lock--on': isItemLocked(`gap:${index}`) }" :aria-pressed="isItemLocked(`gap:${index}`)" :disabled="lockBusyKey === `gap:${index}`" @click="toggleLock(revisableItem(`gap:${index}`))">{{ lockLabel(`gap:${index}`) }}</button>
        </li>
      </ul>
      <ul v-if="bridgePaths.length" class="exploration-result-card__list">
        <li v-for="(path, index) in bridgePaths" :key="`bridge:${index}`">
          <ol class="exploration-result-card__chain"><li v-for="(step, stepIndex) in path.steps || []" :key="stepIndex">{{ step }}</li></ol>
          <p v-if="path.required_conditions?.length" class="exploration-result-card__basis">所需条件：{{ path.required_conditions.join("；") }}</p>
          <p v-if="path.cost_or_risk" class="exploration-result-card__basis">代价或风险：{{ path.cost_or_risk }}</p>
          <p v-if="path.holds != null" class="exploration-result-card__basis">{{ path.holds ? "在不靠巧合的条件下成立" : "尚不能保证成立" }}</p>
          <button v-if="lockAvailable && revisableItem(`bridge:${index}`)" type="button" class="exploration-result-card__lock" :class="{ 'exploration-result-card__lock--on': isItemLocked(`bridge:${index}`) }" :aria-pressed="isItemLocked(`bridge:${index}`)" :disabled="lockBusyKey === `bridge:${index}`" @click="toggleLock(revisableItem(`bridge:${index}`))">{{ lockLabel(`bridge:${index}`) }}</button>
        </li>
      </ul>
      <!-- 导向路径：目标 + 规则约束 + 行动—条件—响应—后果—代价，每步一个块 -->
      <div v-if="goalPath" class="exploration-result-card__goal">
        <p class="exploration-result-card__goal-target">目标：{{ goalPath.goal }}</p>
        <ul v-if="goalConstraints.length" class="exploration-result-card__tags" aria-label="规则约束">
          <li v-for="(constraint, index) in goalConstraints" :key="`rule:${index}`">{{ constraint }}</li>
        </ul>
        <ol class="exploration-result-card__steps">
          <li v-for="(step, index) in goalPath.steps || []" :key="`step:${index}`" class="exploration-result-card__step">
            <p><strong>行动：{{ step.action }}</strong></p>
            <p v-if="step.condition" class="exploration-result-card__basis">成立条件：{{ step.condition }}</p>
            <p v-if="step.response" class="exploration-result-card__basis">对方响应：{{ step.response }}</p>
            <p v-if="step.consequence" class="exploration-result-card__basis">后果：{{ step.consequence }}</p>
            <p v-if="step.cost_or_risk" class="exploration-result-card__basis">代价或风险：{{ step.cost_or_risk }}</p>
          </li>
        </ol>
        <p v-if="goalUnsolvable" class="exploration-result-card__unknown">无法成立：{{ goalUnsolvable.reason }}<template v-if="goalMissing.length">；缺项：{{ goalMissing.join("；") }}</template></p>
      </div>
      <!-- 信息边界：逐主体列知道/不知道与缺失接触路径 -->
      <div v-if="infoBoundary.length" class="exploration-result-card__boundary">
        <h4>信息边界</h4>
        <ul class="exploration-result-card__boundary-list">
          <li v-for="(row, index) in infoBoundary" :key="`boundary:${index}`">
            <p class="exploration-result-card__subject">
              <strong>{{ row.subject_description || row.subject_ref || "未标注主体" }}</strong>
              <span v-if="row.missing_contact_path" class="exploration-result-card__missing-tag">缺接触路径</span>
            </p>
            <p v-if="row.knows?.length" class="exploration-result-card__basis">知道：{{ row.knows.join("；") }}</p>
            <p v-if="row.not_known?.length" class="exploration-result-card__basis">不知道：{{ row.not_known.join("；") }}</p>
          </li>
        </ul>
      </div>
      <p v-if="display.unsolvable" class="exploration-result-card__unknown">无法成立：{{ display.unsolvable.reason }}<template v-if="missingItems.length">；缺项：{{ missingItems.join("；") }}</template></p>
      <p v-if="display.original_excerpt" class="exploration-result-card__basis">原案：{{ display.original_excerpt }}</p>
    </section>

    <!-- 场景对白：单目标一句对白 + 依据 + withheld；多目标逐目标一块；空间诊断独立结论区 -->
    <section v-else-if="isSceneLine" class="exploration-result-card__body">
      <template v-if="sceneVariants.length">
        <div v-for="(variant, index) in sceneVariants" :key="`variant:${index}`" class="exploration-result-card__variant">
          <p class="exploration-result-card__variant-target">目标：{{ variantTargetLabel(variant) }}</p>
          <blockquote class="exploration-result-card__line">{{ variant.line }}</blockquote>
          <p v-if="variant.action" class="exploration-result-card__basis">动作：{{ variant.action }}</p>
          <p v-if="variant.rationale" class="exploration-result-card__basis">依据：{{ variant.rationale }}</p>
          <p v-if="variant.knowledge_basis?.length" class="exploration-result-card__basis">知识来源：{{ variant.knowledge_basis.join("；") }}</p>
          <p v-if="variant.withheld?.length" class="exploration-result-card__basis">没有说出口：{{ variant.withheld.join("；") }}</p>
        </div>
      </template>
      <template v-else>
        <blockquote v-if="display.line" class="exploration-result-card__line">{{ display.line }}</blockquote>
        <button v-if="display.line && lockAvailable && revisableItem('line')" type="button" class="exploration-result-card__lock" :class="{ 'exploration-result-card__lock--on': isItemLocked('line') }" :aria-pressed="isItemLocked('line')" :disabled="lockBusyKey === 'line'" @click="toggleLock(revisableItem('line'))">{{ lockLabel('line') }}</button>
        <p v-if="!display.line && !spatialAssessment" class="exploration-result-card__empty">这条结果没有给出对白内容。</p>
        <p v-if="display.action" class="exploration-result-card__basis">动作：{{ display.action }}</p>
        <p v-if="display.rationale" class="exploration-result-card__basis">依据：{{ display.rationale }}</p>
        <p v-if="display.knowledge_basis?.length" class="exploration-result-card__basis">知识来源：{{ display.knowledge_basis.join("；") }}</p>
        <p v-if="display.withheld?.length" class="exploration-result-card__basis">没有说出口：{{ display.withheld.join("；") }}</p>
      </template>
      <div v-if="spatialAssessment" class="exploration-result-card__spatial">
        <h4>空间诊断</h4>
        <p class="exploration-result-card__basis">结论：{{ spatialVerdictLabel(spatialAssessment) }}</p>
        <template v-if="spatialConstraints.length">
          <p class="exploration-result-card__basis">约束：</p>
          <ul class="exploration-result-card__list">
            <li v-for="(constraint, index) in spatialConstraints" :key="`spatial-constraint:${index}`">{{ constraint }}</li>
          </ul>
        </template>
        <p v-if="spatialUnknowns.length" class="exploration-result-card__unknown">未知：{{ spatialUnknowns.join("；") }}</p>
      </div>
    </section>

    <p v-else class="exploration-result-card__empty">暂不支持在卡片中展示这类结果，请在项目助手中查看。</p>

    <p v-if="display.unknowns?.length" class="exploration-result-card__unknown">未知：{{ display.unknowns.join("；") }}</p>
    <p v-for="warning in display.warnings || []" :key="warning" class="exploration-result-card__unknown">{{ warning }}</p>
    <p v-if="editNote" class="exploration-result-card__basis">编辑说明：{{ editNote }}</p>

    <section v-for="(followUp, index) in followUps" :key="`follow:${index}`" class="exploration-result-card__followup">
      <p><strong>补充后的新结果</strong></p>
      <p class="exploration-result-card__line">{{ compactText(followUp.payload, followUp.output_kind) }}</p>
    </section>

    <div class="exploration-result-card__actions">
      <button v-if="modelFollowUpAvailable" type="button" class="btn btn-sm" :disabled="busy" @click="requestDetail">说详细点</button>
      <details v-if="modelFollowUpAvailable && revisionItems.length" class="exploration-result-card__op">
        <summary>局部修订</summary>
        <label><span>选择条目</span>
          <select v-model="revisionItemKey" :disabled="busy">
            <option v-for="item in revisionItems" :key="item.key" :value="item.key" :disabled="isItemLocked(item.key)">{{ item.label }}{{ isItemLocked(item.key) ? "（已锁定，先解锁）" : "" }}</option>
          </select>
        </label>
        <label><span>这条要怎么改</span><textarea v-model="revisionInstruction" rows="2" maxlength="2000" :disabled="busy"></textarea></label>
        <p v-if="selectedItemLocked" class="exploration-result-card__hint">已锁定，先解锁</p>
        <button type="button" class="btn btn-sm" :disabled="busy || selectedItemLocked || !revisionItemKey || !revisionInstruction.trim()" @click="requestRevise">{{ busy ? "正在修订…" : "开始修订" }}</button>
      </details>
      <details class="exploration-result-card__op">
        <summary>保存编辑</summary>
        <p class="exploration-result-card__hint">编辑会保存为新版本，AI 原结果保持不变；本地草稿暂存，保存成功才提示已保存。</p>
        <label><span>编辑{{ revisionItemKey ? `：${selectedItem?.label || "选中条目"}` : "文本" }}</span><textarea v-model="editDraft" rows="3" maxlength="4000"></textarea></label>
        <div class="exploration-result-card__save-row">
          <button type="button" class="btn btn-sm" :disabled="savingEdit || !editDraft.trim()" @click="startEdit">{{ editing ? "更新草稿" : "开始编辑" }}</button>
          <button type="button" class="btn btn-sm btn-primary" :disabled="savingEdit || !editDraft.trim()" @click="saveEdit">{{ savingEdit ? "正在保存…" : "保存编辑" }}</button>
        </div>
      </details>
      <details v-if="projectId" class="exploration-result-card__op" @toggle="onCompareToggle">
        <summary>结果对照</summary>
        <label><span>选择同一 root 下的另一结果</span>
          <select v-model="compareTargetId" :disabled="comparing">
            <option value="">选择结果</option>
            <option v-for="item in compareCandidates" :key="item.result_id" :value="item.result_id">{{ item.label }}</option>
          </select>
        </label>
        <fieldset v-if="sandboxCompareAvailable" class="exploration-result-card__modes">
          <legend>对照方式</legend>
          <label><input v-model="compareMode" type="radio" value="same_start" :disabled="comparing" />同起点</label>
          <label><input v-model="compareMode" type="radio" value="counterfactual" :disabled="comparing" />反事实对照</label>
        </fieldset>
        <button type="button" class="btn btn-sm" :disabled="comparing || !compareTargetId" @click="requestCompare">{{ comparing ? "正在比较…" : "比较" }}</button>
        <div v-if="comparison" class="exploration-result-card__compare">
          <div v-if="changedConditions.length" class="exploration-result-card__changed">
            <h4>变更条件</h4>
            <ul class="exploration-result-card__tags"><li v-for="cond in changedConditions" :key="cond">{{ cond }}</li></ul>
          </div>
          <section><h4>当前结果<span v-if="comparison.currentLockedCount" class="exploration-result-card__lock-tag">已锁定 {{ comparison.currentLockedCount }} 项</span></h4><p>{{ comparison.current }}</p></section>
          <section><h4>对比结果<span v-if="comparison.otherLockedCount" class="exploration-result-card__lock-tag">已锁定 {{ comparison.otherLockedCount }} 项</span></h4><p>{{ comparison.other }}</p></section>
        </div>
      </details>
    </div>

    <p v-if="status.text" role="status" aria-live="polite" class="exploration-result-card__status">{{ status.text }}</p>
    <p v-if="errorMessage" role="alert" class="exploration-result-card__error">{{ errorMessage }}</p>
  </article>
</template>

<script setup>
// 探索结果卡（第一批）：按 output_kind 三态渲染紧凑结果，并提供
// 说详细点 / 局部修订（模型追加，走 202 任务轮询）与保存编辑（零模型调用）、
// 结果对照（只读；沙盘支持同起点与反事实两种模式，反事实回传变更条件）。
// M3-A3：可修订条目旁提供锁定开关；锁定条目禁止局部修订，修订/编辑冲突时
// 原样展示服务端 409 中文原因。AI 结果不可变；编辑保存形成新版本。
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"
import { createOperationId, pollTaskProgress } from "../../../shared/workflowProgress.js"

const props = defineProps({
  source: { type: Object, required: true },
  projectId: { type: String, default: null },
})
const emit = defineEmits(["refresh"])

const SANDBOX = "story.exploration.sandbox"
const EVENT = "story.exploration.event"
const SCENE_LINE = "story.exploration.scene_line"
const AUTHOR_EDIT = "story.exploration.author_edit"
const KIND_LABELS = { [SANDBOX]: "沙盘推演", [EVENT]: "事件诊断", [SCENE_LINE]: "场景对白", [AUTHOR_EDIT]: "作者编辑版" }
const SCALE_LABELS = { sandbox: "沙盘", event: "事件", scene_line: "场景对白" }
const DRAFT_PREFIX = "novel_exploration_edit_v1"

const busy = ref(false)
const savingEdit = ref(false)
const editing = ref(false)
const editDraft = ref("")
const revisionItemKey = ref("")
const revisionInstruction = ref("")
const followUps = ref([])
const status = ref({ tone: "", text: "" })
const errorMessage = ref("")
const savedLocally = ref(false)
const compareOpen = ref(false)
const compareTargetId = ref("")
const compareCandidates = ref([])
const comparing = ref(false)
const comparison = ref(null)
const compareMode = ref("same_start")
let poller = null

const current = ref({ resultId: props.source?.result_id || "", kind: props.source?.output_kind || "", payload: props.source?.payload || {} })

const kind = computed(() => current.value.kind)
const display = computed(() => {
  if (kind.value === AUTHOR_EDIT) return current.value.payload?.edited_payload || {}
  return current.value.payload || {}
})
const effectiveKind = computed(() => (kind.value === AUTHOR_EDIT ? current.value.payload?.base_output_kind || "" : kind.value))
const isSandbox = computed(() => effectiveKind.value === SANDBOX)
const isEvent = computed(() => effectiveKind.value === EVENT)
const isSceneLine = computed(() => effectiveKind.value === SCENE_LINE)
const savedEdit = computed(() => kind.value === AUTHOR_EDIT || savedLocally.value)
const editNote = computed(() => (kind.value === AUTHOR_EDIT ? current.value.payload?.edit_note || "" : ""))
const title = computed(() => KIND_LABELS[kind.value] || "探索结果")
const scaleLabel = computed(() => SCALE_LABELS[props.source?.scale] || props.source?.scale || "探索")
const scaleClass = computed(() => props.source?.scale || "unknown")
const question = computed(() => props.source?.label || display.value.question || "")
const modelFollowUpAvailable = computed(() => kind.value !== AUTHOR_EDIT && Boolean(current.value.resultId))

const sandboxLinks = computed(() => (isSandbox.value ? display.value.influence_chain || [] : []))

// 反事实对照入口仅对沙盘结果开放（后端 same_start/counterfactual 也只在
// sandbox 分支上提供条件对照）；切回同起点不保留上一轮的变更条件标签。
const sandboxCompareAvailable = computed(() => props.source?.scale === "sandbox")
const changedConditions = computed(() => (
  comparison.value?.mode === "counterfactual" && Array.isArray(comparison.value?.changed_conditions)
    ? comparison.value.changed_conditions
    : []
))
// 事件三态互斥：diagnose 缺口 / bridge 候选 / goal 导向路径，各自只消费自己的字段。
const eventModeLabel = computed(() => (
  display.value.mode === "bridge" ? "补桥候选路径" : display.value.mode === "goal" ? "导向路径" : "诊断缺口"
))
const eventGaps = computed(() => (isEvent.value && display.value.mode === "diagnose" ? display.value.gaps || [] : []))
const bridgePaths = computed(() => (isEvent.value && display.value.mode === "bridge" ? display.value.bridge_candidates || [] : []))
const goalPath = computed(() => (isEvent.value && display.value.mode === "goal" ? display.value.goal_path || null : null))
const goalConstraints = computed(() => (Array.isArray(goalPath.value?.rule_constraints) ? goalPath.value.rule_constraints : []))
const goalUnsolvable = computed(() => goalPath.value?.unsolvable || null)
const goalMissing = computed(() => (Array.isArray(goalUnsolvable.value?.missing) ? goalUnsolvable.value.missing : []))
const infoBoundary = computed(() => (isEvent.value && Array.isArray(display.value.info_boundary) ? display.value.info_boundary : []))
const missingItems = computed(() => (Array.isArray(display.value.unsolvable?.missing) ? display.value.unsolvable.missing : []))
// 场景三态互斥：多目标 variants 逐目标一块；空间诊断独立结论；单目标走原有对白布局。
const sceneVariants = computed(() => (isSceneLine.value && Array.isArray(display.value.variants) ? display.value.variants : []))
const spatialAssessment = computed(() => (
  isSceneLine.value && display.value.spatial_assessment && typeof display.value.spatial_assessment === "object"
    ? display.value.spatial_assessment
    : null
))
const spatialConstraints = computed(() => (Array.isArray(spatialAssessment.value?.constraints) ? spatialAssessment.value.constraints : []))
const spatialUnknowns = computed(() => (Array.isArray(spatialAssessment.value?.unknowns) ? spatialAssessment.value.unknowns : []))

// 目标优先展示 label 类字段；payload 只有 ref 时直接显示 ref。
function variantTargetLabel(variant) {
  return variant?.target_label || variant?.target_ref || "未标注目标"
}
// supported 三态：true 支持 / false 不支持 / 缺失或 null 无法判定。
function spatialVerdictLabel(assessment) {
  const supported = assessment?.supported
  return supported === true ? "支持" : supported === false ? "不支持" : "无法判定"
}

// 修订定位约定：item_path 是 `chain:0`/`gap:1`/`bridge:2`/`line` 形式的条目路径，
// item_text 是当前展示文本；服务端以 item_text 与父结果比对防漂移，实现差异会在
// revise 请求上显式失败，不静默错改。
const revisionItems = computed(() => {
  const payload = display.value
  if (isSandbox.value) {
    return (payload.influence_chain || []).map((item, index) => ({
      key: `chain:${index}`,
      label: item.condition || item.effect || `影响链 ${index + 1}`,
      text: item.effect || "",
    }))
  }
  if (isEvent.value) {
    const bridge = payload.mode === "bridge"
    return (bridge ? payload.bridge_candidates : payload.gaps || []).map((item, index) => ({
      key: `${bridge ? "bridge" : "gap"}:${index}`,
      label: bridge ? (item.steps || []).join("；") || `补桥路径 ${index + 1}` : item.description || `缺口 ${index + 1}`,
      text: bridge ? (item.steps || []).join("\n") : item.description || "",
    }))
  }
  if (isSceneLine.value) {
    return [{ key: "line", label: "这句对白", text: payload.line || "" }]
  }
  return []
})
const selectedItem = computed(() => revisionItems.value.find(item => item.key === revisionItemKey.value) || null)

// 锁定集合：初始来自 source.locked_items（域引用可能携带，元素为 item_path，
// 兼容对象形态），随后以 lock 接口返回的最新 locked_items 为准。
// 锁定条目禁止局部修订；编辑冲突由服务端 409 兜底并原样展示原因。
function normalizeLockedPaths(items) {
  if (!Array.isArray(items)) return new Set()
  return new Set(items.map(item => (typeof item === "string" ? item : item?.item_path)).filter(Boolean))
}
const lockedItemPaths = ref(normalizeLockedPaths(props.source?.locked_items))
const lockBusyKey = ref("")
const lockAvailable = computed(() => kind.value !== AUTHOR_EDIT && Boolean(current.value.resultId))
const selectedItemLocked = computed(() => Boolean(selectedItem.value && lockedItemPaths.value.has(selectedItem.value.key)))

function revisableItem(key) { return revisionItems.value.find(item => item.key === key) || null }
function isItemLocked(key) { return lockedItemPaths.value.has(key) }
function lockLabel(key) { return isItemLocked(key) ? "🔒 已锁定" : "🔒 锁定" }

async function toggleLock(item) {
  const projectId = props.projectId
  if (!item || !lockAvailable.value || lockBusyKey.value) return
  const lock = !isItemLocked(item.key)
  lockBusyKey.value = item.key
  errorMessage.value = ""
  try {
    const receipt = await getApi()?.story?.explorationLock(current.value.resultId, {
      novel_id: projectId,
      operation_id: createOperationId(),
      lock,
      item_path: item.key,
      item_text: item.text,
    })
    // 服务端返回全量 locked_items 时以其为准；缺失时按本次操作本地推演。
    const serverItems = receipt?.payload?.locked_items
    if (Array.isArray(serverItems)) lockedItemPaths.value = normalizeLockedPaths(serverItems)
    else {
      const next = new Set(lockedItemPaths.value)
      if (lock) next.add(item.key)
      else next.delete(item.key)
      lockedItemPaths.value = next
    }
    status.value = { tone: "ok", text: lock ? "已锁定该条目；修订前需先解锁。" : "已解锁该条目，可以继续修订。" }
  } catch (error) {
    // 409（item_text 漂移、并发锁定等）原样展示服务端中文原因。
    errorMessage.value = error?.message || "锁定状态没有更新，请稍后重试。"
  } finally { lockBusyKey.value = "" }
}

function draftKey() { return `${DRAFT_PREFIX}:${props.projectId || "local"}:${current.value.resultId}` }
function readDraft() {
  try {
    const parsed = JSON.parse(localStorage.getItem(draftKey()) || "null")
    return parsed && typeof parsed.text === "string" ? parsed : null
  } catch { return null }
}
function writeDraft() {
  try { localStorage.setItem(draftKey(), JSON.stringify({ text: editDraft.value, itemKey: revisionItemKey.value, updatedAt: new Date().toISOString() })) } catch { /* 存储不可用时草稿只留在本页 */ }
}
function clearDraft() {
  try { localStorage.removeItem(draftKey()) } catch { /* ignore */ }
}

watch(revisionItemKey, () => {
  if (!editing.value) editDraft.value = selectedItem.value?.text || ""
})

// 条目选择默认落到第一项；结果切换（如补充后的新版本）时重新对齐。
watch(revisionItems, items => {
  if (!items.some(item => item.key === revisionItemKey.value)) revisionItemKey.value = items[0]?.key || ""
}, { immediate: true })

// 切换对照方式后，上一轮比较视图（含变更条件标签）立即失效，避免与新请求混淆。
watch(compareMode, () => { comparison.value = null })

// 未保存的编辑草稿逐次暂存 localStorage；服务端保存成功后才清除。
watch(editDraft, value => {
  if (!current.value.resultId) return
  if (value.trim()) writeDraft()
  else clearDraft()
})

// 刷新/离开后回到同一结果时恢复未保存的草稿。
const restoredDraft = readDraft()
if (restoredDraft?.text) {
  editing.value = true
  if (revisionItems.value.some(item => item.key === restoredDraft.itemKey)) revisionItemKey.value = restoredDraft.itemKey
  editDraft.value = restoredDraft.text
}

function startEdit() {
  editing.value = true
  if (!editDraft.value.trim()) editDraft.value = selectedItem.value?.text || display.value.line || ""
  writeDraft()
  status.value = { tone: "info", text: "草稿已暂存在本页，保存成功前不会进入结果历史。" }
}

function editedPayload() {
  const clone = JSON.parse(JSON.stringify(display.value || {}))
  const text = editDraft.value.trim()
  const index = selectedItem.value ? Number(selectedItem.value.key.split(":")[1]) : -1
  if (isSandbox.value && selectedItem.value) clone.influence_chain[index].effect = text
  else if (isEvent.value && selectedItem.value) {
    if (selectedItem.value.key.startsWith("bridge")) clone.bridge_candidates[index].steps = text.split("\n").map(line => line.trim()).filter(Boolean)
    else clone.gaps[index].description = text
  } else if (isSceneLine.value) clone.line = text
  else return null
  return clone
}

async function saveEdit() {
  const edited = editedPayload()
  const projectId = props.projectId
  if (!current.value.resultId || !projectId) { errorMessage.value = "缺少作品或结果标识，暂时无法保存编辑。"; return }
  if (!edited) { errorMessage.value = "这类结果暂不支持在卡片中编辑，请在项目助手中处理。"; return }
  savingEdit.value = true
  errorMessage.value = ""
  status.value = { tone: "info", text: "正在保存编辑…" }
  try {
    await getApi()?.story?.explorationSaveEdit(current.value.resultId, {
      novel_id: projectId,
      base_output_kind: effectiveKind.value,
      edited_payload: edited,
    })
    savedLocally.value = true
    editing.value = false
    editDraft.value = ""
    clearDraft()
    current.value = { ...current.value, kind: AUTHOR_EDIT, payload: { base_output_kind: effectiveKind.value, base_result_id: current.value.resultId, edited_payload: edited } }
    status.value = { tone: "ok", text: "已保存编辑（形成新版本，原结果保持不变）。" }
    emit("refresh")
  } catch (error) {
    // 服务端失败：草稿保留（本页 + localStorage），明示失败原因。
    errorMessage.value = `保存未成功：${error?.message || "请稍后重试"}。草稿已保留，可直接再次保存。`
    status.value = { tone: "", text: "" }
  } finally { savingEdit.value = false }
}

function pickFollowUp(task) {
  const result = task?.result
  if (!result || typeof result !== "object") return null
  const wrapper = result.result && typeof result.result === "object" && result.result.output_kind ? result.result : result
  return wrapper.output_kind && wrapper.payload ? wrapper : null
}

function pollFollowUp(taskId) {
  poller?.stop?.()
  poller = pollTaskProgress({
    taskId,
    workflowType: "story_exploration",
    novelId: props.projectId,
    apiClient: getApi(),
    receiptStorage: null,
    onUpdate: () => { if (!status.value.text || status.value.tone === "info") status.value = { tone: "info", text: "正在生成结果，可离开后回来查看。" } },
    onDone: (_progress, task) => {
      busy.value = false
      const wrapper = pickFollowUp(task)
      if (wrapper) {
        followUps.value = [...followUps.value, { output_kind: wrapper.output_kind, payload: wrapper.payload }]
        current.value = { resultId: wrapper.result_id || current.value.resultId, kind: wrapper.output_kind, payload: wrapper.payload }
        // 新结果是独立版本，不继承父结果的锁定集合。
        lockedItemPaths.value = new Set()
        revisionItemKey.value = ""
        revisionInstruction.value = ""
        status.value = { tone: "ok", text: "新结果已生成。" }
      } else {
        status.value = { tone: "ok", text: "新结果已生成，刷新讨论后即可查看。" }
      }
      emit("refresh")
    },
    onFailed: progress => {
      busy.value = false
      status.value = { tone: "", text: "" }
      errorMessage.value = progress?.errorMessage || "这次生成没有完成；已保存的结果仍在。"
    },
  })
}

async function requestDetail() {
  const projectId = props.projectId
  if (!current.value.resultId || !projectId || busy.value) return
  busy.value = true
  errorMessage.value = ""
  status.value = { tone: "info", text: "已提交“说详细点”，等待生成…" }
  try {
    const receipt = await getApi()?.story?.explorationDetail(current.value.resultId, { novel_id: projectId, operation_id: createOperationId() })
    if (!receipt?.task_id) throw new Error("服务端没有返回任务标识")
    pollFollowUp(receipt.task_id)
  } catch (error) {
    busy.value = false
    status.value = { tone: "", text: "" }
    errorMessage.value = error?.message || "暂时无法追加生成，请稍后重试。"
  }
}

async function requestRevise() {
  const projectId = props.projectId
  const item = selectedItem.value
  if (!current.value.resultId || !projectId || busy.value || !item) return
  busy.value = true
  errorMessage.value = ""
  status.value = { tone: "info", text: "已提交局部修订，等待生成…" }
  try {
    const receipt = await getApi()?.story?.explorationRevise(current.value.resultId, {
      novel_id: projectId,
      operation_id: createOperationId(),
      revision_of: current.value.resultId,
      item_path: item.key,
      item_text: item.text,
      instruction: revisionInstruction.value.trim(),
    })
    if (!receipt?.task_id) throw new Error("服务端没有返回任务标识")
    pollFollowUp(receipt.task_id)
  } catch (error) {
    busy.value = false
    status.value = { tone: "", text: "" }
    errorMessage.value = error?.message || "暂时无法修订，请稍后重试。"
  }
}

async function onCompareToggle(event) {
  compareOpen.value = event.target?.open === true
  if (!compareOpen.value || compareCandidates.value.length || !props.projectId) return
  try {
    const history = await getApi()?.story?.explorationHistory({ novel_id: props.projectId, root_id: props.source?.root_id })
    const rows = []
    const collect = item => { if (item?.result_id && item.result_id !== current.value.resultId) rows.push({ result_id: item.result_id, label: item.label || SCALE_LABELS[item.scale] || item.result_id }) }
    for (const item of history?.items || []) collect(item)
    for (const root of history?.roots || []) {
      if (props.source?.root_id && root?.id && root.id !== props.source.root_id) continue
      for (const branch of root?.branches || []) for (const item of branch?.results || []) collect(item)
    }
    compareCandidates.value = rows
  } catch (error) {
    errorMessage.value = error?.message || "探索历史暂时无法读取，不能比较。"
  }
}

async function requestCompare() {
  const owner = props.projectId
  if (!owner || !compareTargetId.value || comparing.value) return
  comparing.value = true
  errorMessage.value = ""
  try {
    const receipt = await getApi()?.story?.explorationCompare({
      novel_id: owner,
      first_result_id: current.value.resultId,
      second_result_id: compareTargetId.value,
      mode: compareMode.value,
    })
    const first = receipt?.first?.payload ? receipt.first : { output_kind: kind.value, payload: display.value }
    const second = receipt?.second || null
    comparison.value = {
      current: compactText(first.payload, first.output_kind),
      other: second ? compactText(second.payload, second.output_kind) : "对比结果暂不可读。",
      mode: receipt?.mode || "same_start",
      changed_conditions: Array.isArray(receipt?.changed_conditions) ? receipt.changed_conditions : [],
      // 比较响应带两侧 locked_items（item_path 数组）；列头展示锁定数标签。
      currentLockedCount: Array.isArray(first.locked_items) ? first.locked_items.length : 0,
      otherLockedCount: Array.isArray(second?.locked_items) ? second.locked_items.length : 0,
    }
  } catch (error) {
    // 409 等失败原样展示服务端中文原因；仅兜底文案按模式区分。
    errorMessage.value = error?.message || (compareMode.value === "counterfactual"
      ? "比较没有完成；反事实对照要求两行互为衍生或共享同一基线。"
      : "比较没有完成；两行结果必须来自同一起点。")
  } finally { comparing.value = false }
}

function compactText(payload, kindValue = effectiveKind.value) {
  const text = []
  if (!payload || typeof payload !== "object") return "（无内容）"
  if (kindValue === SANDBOX) {
    for (const link of payload.influence_chain || []) text.push(`${link.condition || "未写明条件"} → ${link.effect || ""}`)
    if (payload.preconditions?.length) text.push(`前提条件：${payload.preconditions.join("；")}`)
  } else if (kindValue === EVENT) {
    if (payload.mode === "bridge") for (const path of payload.bridge_candidates || []) text.push((path.steps || []).join(" → "))
    else if (payload.mode === "goal") {
      const goal = payload.goal_path
      if (goal) {
        text.push(`目标：${goal.goal || ""}`)
        for (const step of goal.steps || []) text.push(`${step.action || ""}（条件：${step.condition || ""}）→ ${step.consequence || ""}`)
        if (goal.unsolvable) text.push(`无法成立：${goal.unsolvable.reason || ""}`)
      }
    } else for (const gap of payload.gaps || []) text.push(gap.description || "")
    for (const row of payload.info_boundary || []) {
      const subject = row.subject_description || row.subject_ref || "未标注主体"
      const knows = (row.knows || []).join("、") || "未声明"
      const notKnown = (row.not_known || []).join("、") || "未声明"
      text.push(`${subject}：知道 ${knows}；不知道 ${notKnown}${row.missing_contact_path ? "；缺接触路径" : ""}`)
    }
    if (payload.unsolvable) text.push(`无法成立：${payload.unsolvable.reason || ""}`)
  } else if (kindValue === SCENE_LINE) {
    if (Array.isArray(payload.variants) && payload.variants.length) text.push(payload.variants[0]?.line || "")
    else if (payload.spatial_assessment && typeof payload.spatial_assessment === "object") {
      const constraint = Array.isArray(payload.spatial_assessment.constraints) ? payload.spatial_assessment.constraints[0] || "" : ""
      text.push(`空间诊断：${spatialVerdictLabel(payload.spatial_assessment)}${constraint ? `；约束：${constraint}` : ""}`)
    } else text.push(payload.line || "")
  } else text.push(JSON.stringify(payload))
  if (payload.unknowns?.length) text.push(`未知：${payload.unknowns.join("；")}`)
  return text.filter(Boolean).join("\n") || "（无内容）"
}

onBeforeUnmount(() => { poller?.stop?.(); poller = null })
</script>

<style>
.exploration-result-card{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:12px;margin:12px 0;min-width:0}
.exploration-result-card__header{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.exploration-result-card__scale,.exploration-result-card__badge{padding:2px 8px;border-radius:999px;background:var(--bg-muted);font-size:12px}
.exploration-result-card__badge{background:#e6efeb;color:#36594e}
.exploration-result-card__question,.exploration-result-card__status{color:var(--text-secondary);font-size:13px;margin:8px 0;overflow-wrap:anywhere}
.exploration-result-card__chain,.exploration-result-card__list{padding-left:20px;margin:8px 0;display:grid;gap:8px}
.exploration-result-card__basis{color:var(--text-secondary);font-size:13px;margin:4px 0;overflow-wrap:anywhere}
.exploration-result-card__unknown{color:#8a6116;font-size:13px;margin:4px 0;overflow-wrap:anywhere}
.exploration-result-card__line{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0;padding:8px 10px;border-left:3px solid var(--border-color,var(--border));background:var(--bg-muted);border-radius:6px}
.exploration-result-card__empty{color:var(--text-secondary)}
.exploration-result-card__followup{border-top:1px dashed var(--border-color,var(--border));padding-top:8px;margin-top:8px}
.exploration-result-card__actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.exploration-result-card__actions .btn{min-height:40px}
.exploration-result-card__op{flex:1 1 180px;min-width:0;border:1px solid var(--border-color,var(--border));border-radius:8px;padding:8px}
.exploration-result-card__op summary{cursor:pointer;min-height:32px;line-height:32px;font-weight:600}
.exploration-result-card__op label{display:block;font-size:12px;margin:8px 0}
.exploration-result-card__op select,.exploration-result-card__op textarea{box-sizing:border-box;width:100%;min-height:40px;padding:6px;background:var(--bg-muted);color:inherit;border:1px solid var(--border-color,var(--border));border-radius:6px;font:inherit}
.exploration-result-card__op textarea{resize:vertical}
.exploration-result-card__hint{font-size:12px;color:var(--text-secondary);margin:4px 0}
.exploration-result-card__save-row{display:flex;flex-wrap:wrap;gap:8px}
.exploration-result-card__modes{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:8px 0;padding:0;border:0}
.exploration-result-card__modes legend{padding:0;font-size:12px;color:var(--text-secondary)}
.exploration-result-card__modes label{display:inline-flex;align-items:center;gap:4px;margin:0;font-size:13px;cursor:pointer}
.exploration-result-card__compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
.exploration-result-card__changed{grid-column:1/-1;min-width:0}
.exploration-result-card__changed h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__tags{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.exploration-result-card__tags li{padding:2px 8px;border-radius:999px;background:#e6efeb;color:#36594e;font-size:12px;overflow-wrap:anywhere}
.exploration-result-card__goal{margin:8px 0;display:grid;gap:6px}
.exploration-result-card__goal-target{font-weight:600;margin:0;overflow-wrap:anywhere}
.exploration-result-card__steps{list-style:none;counter-reset:goal-step;padding:0;margin:8px 0;display:grid;gap:8px}
.exploration-result-card__step{counter-increment:goal-step;border:1px solid var(--border-color,var(--border));border-radius:8px;padding:8px;background:var(--bg-muted);min-width:0}
.exploration-result-card__step>p:first-child{margin:0 0 4px}
.exploration-result-card__step>p:first-child::before{content:counter(goal-step) ". ";color:var(--text-secondary)}
.exploration-result-card__boundary{border:1px dashed var(--border-color,var(--border));border-radius:8px;padding:8px;margin:8px 0;min-width:0}
.exploration-result-card__boundary h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__boundary-list{padding-left:20px;margin:0;display:grid;gap:8px}
.exploration-result-card__subject{margin:0;display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.exploration-result-card__missing-tag{padding:1px 8px;border-radius:999px;background:#f3e8d2;color:#8a6116;font-size:12px}
.exploration-result-card__lock{align-self:flex-start;margin-top:4px;padding:2px 10px;border:1px solid var(--border-color,var(--border));border-radius:999px;background:var(--bg-muted);color:inherit;font:inherit;font-size:12px;cursor:pointer}
.exploration-result-card__lock--on{background:#f3e8d2;border-color:#d8c19a;color:#8a6116}
.exploration-result-card__lock:disabled{opacity:.6;cursor:default}
.exploration-result-card__lock-tag{margin-left:8px;padding:1px 8px;border-radius:999px;background:#f3e8d2;color:#8a6116;font-size:12px;font-weight:400}
.exploration-result-card__variant{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:8px;margin:8px 0;min-width:0}
.exploration-result-card__variant-target{font-weight:600;margin:0 0 4px;overflow-wrap:anywhere}
.exploration-result-card__variant .exploration-result-card__line{margin:4px 0}
.exploration-result-card__spatial{border:1px dashed var(--border-color,var(--border));border-radius:8px;padding:8px;margin:8px 0;min-width:0}
.exploration-result-card__spatial h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__spatial .exploration-result-card__list{margin:4px 0}
.exploration-result-card__compare section{padding:8px;border-radius:8px;background:var(--bg-muted);min-width:0}
.exploration-result-card__compare h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__compare p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font-size:13px}
.exploration-result-card__error{color:var(--danger);font-size:13px;margin:8px 0;overflow-wrap:anywhere}
.exploration-result-card button:focus-visible,.exploration-result-card select:focus-visible,.exploration-result-card textarea:focus-visible,.exploration-result-card summary:focus-visible{outline:3px solid rgba(81,127,111,.35);outline-offset:2px}
@media(max-width:700px){.exploration-result-card__actions{flex-direction:column}.exploration-result-card__op{flex-basis:auto}.exploration-result-card__compare{grid-template-columns:1fr}}
</style>
