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
          <p v-if="link.affected_refs?.length" class="exploration-result-card__basis">受影响：{{ link.affected_refs.join("、") }}</p>
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

    <!-- 完整排演：逐轮区块（轮号标题）→ 每目标表演卡 → 素材 → 观察回执；
         整体结果不支持增量修订，不提供任何修订/编辑/锁定入口 -->
    <section v-else-if="isFullRehearsal" class="exploration-result-card__body">
      <template v-if="rehearsalRounds.length">
        <section v-for="round in rehearsalRounds" :key="`round:${round.round_number}`" class="exploration-result-card__round">
          <h4>第 {{ round.round_number }} 轮</h4>
          <div v-for="(performance, index) in round.performances || []" :key="`perf:${round.round_number}:${index}`" class="exploration-result-card__variant">
            <p class="exploration-result-card__variant-target">目标：{{ performance.target_ref }}</p>
            <blockquote class="exploration-result-card__line">{{ performance.line_or_beat }}</blockquote>
            <p v-if="performance.rationale" class="exploration-result-card__basis">依据：{{ performance.rationale }}</p>
            <p v-if="performance.basis_refs?.length" class="exploration-result-card__basis">知识来源：{{ performance.basis_refs.join("；") }}</p>
          </div>
          <template v-if="round.materials?.length">
            <p class="exploration-result-card__basis">素材：</p>
            <ul class="exploration-result-card__list" aria-label="素材">
              <li v-for="(material, index) in round.materials" :key="`material:${round.round_number}:${index}`">
                <p>{{ rehearsalMaterialLabel(material) }}：{{ material.text }}</p>
                <p v-if="material.perceiver_refs?.length" class="exploration-result-card__basis">感知：{{ material.perceiver_refs.join("、") }}</p>
              </li>
            </ul>
          </template>
          <template v-if="round.observations?.length">
            <p class="exploration-result-card__basis">观察回执：</p>
            <ul class="exploration-result-card__list" aria-label="观察回执">
              <li v-for="(observation, index) in round.observations" :key="`obs:${round.round_number}:${index}`">
                <p>{{ observation.target_ref }} 注意到：{{ observation.observed }}</p>
              </li>
            </ul>
          </template>
        </section>
      </template>
      <p v-else class="exploration-result-card__empty">这次排演没有产出轮次内容。</p>
      <p v-if="rehearsalStateNotes.length" class="exploration-result-card__basis">状态要点：{{ rehearsalStateNotes.join("；") }}</p>
    </section>

    <p v-else class="exploration-result-card__empty">暂不支持在卡片中展示这类结果，请在项目助手中查看。</p>

    <p v-if="display.unknowns?.length" class="exploration-result-card__unknown">未知：{{ display.unknowns.join("；") }}</p>
    <p v-for="warning in display.warnings || []" :key="warning" class="exploration-result-card__unknown">{{ warning }}</p>
    <p v-if="editNote" class="exploration-result-card__basis">编辑说明：{{ editNote }}</p>

    <section v-for="(followUp, index) in followUps" :key="`follow:${index}`" class="exploration-result-card__followup">
      <p><strong>补充后的新结果</strong></p>
      <p class="exploration-result-card__line">{{ compactText(followUp.payload, followUp.output_kind) }}</p>
    </section>

    <button v-if="activeTaskId" type="button" class="btn btn-sm" @click="stopTask">停止这次生成</button>
    <p v-if="backupError" role="alert">本地备份失败，编辑仅保留在本页。保存成功前请勿刷新；可先复制编辑框中的文本。</p>
    <section v-if="pausedReceipt" aria-label="恢复暂停的探索">
      <p>探索已暂停，恢复会沿用原起点、检查点、账本与时限；未完成步骤可能需要重新执行。</p>
      <button type="button" class="btn btn-sm" :disabled="busy" @click="previewResume">核对恢复预算</button>
      <template v-if="resumePreview">
        <p>已请求 {{ resumePreview.requests_started }} 次，其中 {{ resumePreview.requests_unknown }} 次结果未知。</p>
        <label>追加请求上限 <input v-model.number="resumeRequests" type="number" min="1" max="10000"></label>
        <label>追加用量上限 <input v-model.number="resumeTokens" type="number" min="1"></label>
        <label v-if="resumePreview.requests_unknown"><input v-model="resumeUnknownAck" type="checkbox">我已核对未知请求，确认继续可能重复计费</label>
        <button type="button" class="btn btn-sm" :disabled="busy || (resumePreview.requests_unknown && !resumeUnknownAck)" @click="confirmResume">确认追加预算并恢复</button>
      </template>
    </section>
    <ExplorationResultCard v-if="handoffResult" :source="handoffResult" :project-id="projectId" @refresh="emit('refresh')" />

    <div class="exploration-result-card__actions">
      <p v-if="modelFollowUpAvailable" class="exploration-result-card__hint">每个生成条目预计 3–5 次模型请求，包含知识导演与独立审查。说详细点最多追加 {{ (isFullRehearsal || sceneVariants.length || spatialAssessment ? revisionItems.length : 1) * 5 }} 次；局部修订最多追加 5 次。</p>
      <button v-if="modelFollowUpAvailable" type="button" class="btn btn-sm" :disabled="busy" @click="requestDetail">说详细点</button>
      <details v-if="modelFollowUpAvailable && revisionItems.length" class="exploration-result-card__op">
        <summary>局部修订</summary>
        <label><span>选择条目</span>
          <select v-model="revisionItemKey" :disabled="busy || savingEdit">
            <option v-for="item in revisionItems" :key="item.key" :value="item.key" :disabled="isItemLocked(item.key)">{{ item.label }}{{ isItemLocked(item.key) ? "（已锁定，先解锁）" : "" }}</option>
          </select>
        </label>
        <button v-if="lockAvailable && selectedItem && (isFullRehearsal || sceneVariants.length || spatialAssessment)" type="button" class="btn btn-sm" :disabled="busy || Boolean(lockBusyKey)" @click="toggleLock(selectedItem)">{{ lockLabel(selectedItem.key) }}</button>
        <label><span>这条要怎么改</span><textarea v-model="revisionInstruction" rows="2" maxlength="2000" :disabled="busy"></textarea></label>
        <p v-if="selectedItemLocked" class="exploration-result-card__hint">已锁定，先解锁</p>
        <button type="button" class="btn btn-sm" :disabled="busy || selectedItemLocked || !revisionItemKey || !revisionInstruction.trim()" @click="requestRevise">{{ busy ? "正在修订…" : "开始修订" }}</button>
      </details>
      <details class="exploration-result-card__op">
        <summary>保存编辑</summary>
        <p class="exploration-result-card__hint">编辑会保存为新版本，AI 原结果保持不变；本地草稿暂存，保存成功才提示已保存。</p>
        <label><span>编辑{{ revisionItemKey ? `：${selectedItem?.label || "选中条目"}` : "文本" }}</span><textarea v-model="editDraft" rows="3" maxlength="4000" :disabled="busy || savingEdit"></textarea></label>
        <div class="exploration-result-card__save-row">
          <button type="button" class="btn btn-sm" :disabled="busy || savingEdit || !editDraft.trim()" @click="startEdit">{{ editing ? "更新草稿" : "开始编辑" }}</button>
          <button type="button" class="btn btn-sm btn-primary" :disabled="busy || savingEdit || !editDraft.trim()" @click="saveEdit">{{ savingEdit ? "正在保存…" : "保存编辑" }}</button>
        </div>
      </details>
      <details v-if="projectId" class="exploration-result-card__op" @toggle="onCompareToggle">
        <summary>结果对照</summary>
        <label><span>选择另一探索结果</span>
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
          <div v-if="comparison.relation === 'parent_child' || comparison.affectedItems.length" class="exploration-result-card__compare-summary">
            <span v-if="comparison.relation === 'parent_child'" class="exploration-result-card__relation-tag">后代修订对照</span>
            <span v-if="comparison.affectedItems.length" class="exploration-result-card__impact-tag">受影响 {{ comparison.affectedItems.length }} 项</span>
          </div>
          <div v-if="changedConditions.length" class="exploration-result-card__changed">
            <h4>变更条件</h4>
            <ul class="exploration-result-card__tags"><li v-for="cond in changedConditions" :key="cond">{{ cond }}</li></ul>
          </div>
          <div v-if="comparison.affectedItems.length || comparison.affectedGranularity === 'conservative'" class="exploration-result-card__affected">
            <h4>受影响项</h4>
            <p v-if="comparison.affectedGranularity === 'conservative'" class="exploration-result-card__basis">粒度不足，仅保守披露</p>
            <ul v-else class="exploration-result-card__affected-list">
              <li v-for="item in comparison.affectedItems" :key="item.item_path" class="exploration-result-card__affected-item">
                <p class="exploration-result-card__affected-head">
                  <span class="exploration-result-card__affected-status" :class="`exploration-result-card__affected-status--${item.status}`">{{ affectedStatusLabel(item.status) }}</span>
                  <strong>{{ affectedPathLabel(item.item_path) }}</strong>
                </p>
                <div class="exploration-result-card__affected-excerpts">
                  <p>基线：{{ item.base_excerpt || "（无）" }}</p>
                  <p>对照：{{ item.derived_excerpt || "（无）" }}</p>
                </div>
              </li>
            </ul>
          </div>
          <section><h4>当前结果<span v-if="comparison.currentLockedCount" class="exploration-result-card__lock-tag">已锁定 {{ comparison.currentLockedCount }} 项</span></h4><p>{{ comparison.current }}</p></section>
          <section><h4>对比结果<span v-if="comparison.otherLockedCount" class="exploration-result-card__lock-tag">已锁定 {{ comparison.otherLockedCount }} 项</span></h4><p>{{ comparison.other }}</p></section>
        </div>
      </details>
      <!-- M4-A 跨尺度移交：按当前尺度列出其余两个目标尺度；派生起点先只读展示，
           经确认资料范围（confirmation/preview → confirm）后再启动新任务。 -->
      <details v-if="handoffAvailable" class="exploration-result-card__op">
        <summary>基于此推演</summary>
        <p class="exploration-result-card__hint">把这份结果改写成另一尺度的起点；新任务独立运行，不改动原结果。</p>
        <template v-if="!handoffDerived">
          <div class="exploration-result-card__targets" role="group" aria-label="选择移交的目标尺度">
            <button v-for="option in handoffTargetOptions" :key="option.value" type="button" class="exploration-result-card__target" :class="{ 'exploration-result-card__target--on': handoffTarget === option.value }" :aria-pressed="handoffTarget === option.value" :disabled="handoffBusy" @click="handoffTarget = option.value">{{ option.label }}</button>
          </div>
          <label v-if="handoffTarget"><span>推演焦点（可留空）</span><textarea v-model="handoffReason" rows="2" maxlength="500" :disabled="handoffBusy" placeholder="想让这次推演聚焦什么，可留空"></textarea></label>
          <button v-if="handoffTarget" type="button" class="btn btn-sm" :disabled="handoffBusy" @click="requestHandoff">{{ handoffBusy ? "正在生成移交预览…" : "生成移交预览" }}</button>
        </template>
        <div v-else class="exploration-result-card__derived">
          <h4>移交预览（只读）</h4>
          <p class="exploration-result-card__basis">起点问题：{{ handoffDerived.question }}</p>
          <p class="exploration-result-card__basis">假设 {{ handoffDerived.assumptionCount }} 条，由原结果派生。</p>
          <div v-if="handoffConfirmation" class="exploration-result-card__handoff-confirm">
            <p class="exploration-result-card__basis">资料指纹：{{ handoffConfirmation.fingerprint.slice(0, 12) }}…</p>
            <p class="exploration-result-card__basis">资料范围：选中 {{ handoffConfirmation.selectedCount }} 项，来源 {{ handoffConfirmation.sourceCount }} 条。</p>
            <p v-if="handoffConfirmation.blockers.length" class="exploration-result-card__unknown">资料缺口：{{ handoffConfirmation.blockers.join("；") }}</p>
          </div>
          <button v-if="!handoffConfirmation" type="button" class="btn btn-sm btn-primary" :disabled="handoffBusy" @click="previewHandoffConfirmation">{{ handoffBusy ? "正在确认资料范围…" : "继续：确认资料范围并开始" }}</button>
          <button v-else type="button" class="btn btn-sm btn-primary" :disabled="handoffBusy" @click="confirmAndStartHandoff">{{ handoffBusy ? "正在启动新任务…" : "确认并开始" }}</button>
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
// 结果对照（只读；沙盘支持同起点与反事实两种模式，反事实回传变更条件与
// 受影响项，同起点父子对照标记后代修订并列出受影响项，粒度不足时保守披露）。
// M3-A3：可修订条目旁提供锁定开关；锁定条目禁止局部修订，修订/编辑冲突时
// 原样展示服务端 409 中文原因。AI 结果不可变；编辑保存形成新版本。
// M3-B：完整排演结果整体落一行（服务端对 detail/revise/save-edit/lock 一律 409），
// 只读渲染逐轮表演卡/素材/观察回执，并提示以同起点新建任务调整。
// M4-A：跨尺度移交——把当前结果派生为另一尺度的临时起点，经 confirmation/
// preview → confirm → 预算预览 → start 启动独立新任务；源为作者编辑版、
// 完整排演或锁定记录时不提供入口。
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, registerAuxiliaryLeaveGuard } from "../../bridge/index.js"
import { createOperationId, pollTaskProgress, persistActiveWorkflow, recoverActiveWorkflows } from "../../../shared/workflowProgress.js"

const props = defineProps({
  source: { type: Object, required: true },
  projectId: { type: String, default: null },
})
const emit = defineEmits(["refresh"])

const SANDBOX = "story.exploration.sandbox"
const EVENT = "story.exploration.event"
const SCENE_LINE = "story.exploration.scene_line"
const AUTHOR_EDIT = "story.exploration.author_edit"
const FULL_REHEARSAL = "story.exploration.full_rehearsal"
const LOCK_SET = "story.exploration.lock_set"
const KIND_LABELS = { [SANDBOX]: "沙盘推演", [EVENT]: "事件诊断", [SCENE_LINE]: "场景对白", [AUTHOR_EDIT]: "作者编辑版", [FULL_REHEARSAL]: "完整排演" }
// 素材类别沿用后端六类；展示时译为作者语言，未知类别回退原值。
const REHEARSAL_MATERIAL_LABELS = { environment: "环境", object: "物件", crowd: "人群", mood: "氛围", pacing: "节奏", time: "时间" }
const SCALE_LABELS = { sandbox: "沙盘", event: "事件", scene_line: "场景对白" }
// 移交目标尺度按钮沿用 KIND_LABELS 的作者语言；confirmation/confirm/start 的
// action 按目标尺度固定（服务端校验 action 与 scale 匹配，事件取诊断动作）。
const HANDOFF_TARGET_SCALES = [
  { value: "sandbox", label: "沙盘推演" },
  { value: "event", label: "事件诊断" },
  { value: "scene_line", label: "场景对白" },
]
const HANDOFF_ACTION_BY_SCALE = {
  sandbox: "story.exploration.sandbox.generate",
  event: "story.exploration.event.diagnose",
  scene_line: "story.exploration.scene_line.generate",
}
const HANDOFF_SCALE_BY_KIND = { [SANDBOX]: "sandbox", [EVENT]: "event", [SCENE_LINE]: "scene_line" }
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
// M4-A 移交链状态：目标尺度与焦点 → 派生起点 → 确认指纹/范围 → 新任务。
const handoffTarget = ref("")
const handoffReason = ref("")
const handoffDerived = ref(null)
const handoffConfirmation = ref(null)
const handoffBusy = ref(false)
const handoffOperationId = ref(createOperationId())
const handoffStartRequest = ref(null)
const handoffResult = ref(null)
const activeTaskId = ref("")
const pausedReceipt = ref(props.source?.needs_author_resume ? props.source : null)
const resumePreview = ref(null)
const resumeRequests = ref(5)
const resumeTokens = ref(30000)
const resumeUnknownAck = ref(false)
let resumeOperationId = createOperationId()
const backupError = ref(false)
let activeHandoff = false
let restoringSelection = false
let poller = null

let initialView = null
try { initialView = JSON.parse(localStorage.getItem(viewKey()) || "null") } catch { /* 已保存结果从服务端恢复。 */ }
const current = ref(initialView?.current || { resultId: props.source?.result_id || "", kind: props.source?.output_kind || "", payload: props.source?.payload || {} })
revisionItemKey.value = initialView?.itemKey || ""

const kind = computed(() => current.value.kind)
const display = computed(() => {
  if (kind.value === AUTHOR_EDIT) return current.value.payload?.edited_payload || {}
  return current.value.payload || {}
})
const effectiveKind = computed(() => (kind.value === AUTHOR_EDIT ? current.value.payload?.base_output_kind || "" : kind.value))
const isSandbox = computed(() => effectiveKind.value === SANDBOX)
const isEvent = computed(() => effectiveKind.value === EVENT)
const isSceneLine = computed(() => effectiveKind.value === SCENE_LINE)
const isFullRehearsal = computed(() => effectiveKind.value === FULL_REHEARSAL)
const savedEdit = computed(() => kind.value === AUTHOR_EDIT || savedLocally.value)
const editNote = computed(() => (kind.value === AUTHOR_EDIT ? current.value.payload?.edit_note || "" : ""))
const title = computed(() => KIND_LABELS[kind.value] || "探索结果")
const scaleLabel = computed(() => SCALE_LABELS[props.source?.scale] || props.source?.scale || "探索")
const scaleClass = computed(() => props.source?.scale || "unknown")
const question = computed(() => props.source?.label || display.value.question || "")
const modelFollowUpAvailable = computed(() => kind.value !== LOCK_SET && Boolean(current.value.resultId))

// M4-A 移交入口：作者编辑版/完整排演/锁定记录不作为移交源（服务端同样拒绝）。
const handoffAvailable = computed(() => (
  Boolean(props.projectId && current.value.resultId)
  && kind.value !== AUTHOR_EDIT && kind.value !== FULL_REHEARSAL && kind.value !== LOCK_SET
))
// 目标尺度排除自身；scale 缺失时按结果类型推断，仍无法判定则列出全部可选。
const handoffTargetOptions = computed(() => {
  const own = props.source?.scale || HANDOFF_SCALE_BY_KIND[effectiveKind.value] || ""
  return HANDOFF_TARGET_SCALES.filter(option => option.value !== own)
})

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
// 完整排演（M3-B）：逐轮消费 performances/materials/observations；整体落一行，
// 不支持增量修订与锁定，仅展示。
const rehearsalRounds = computed(() => (isFullRehearsal.value && Array.isArray(display.value.rounds) ? display.value.rounds : []))
const rehearsalStateNotes = computed(() => (isFullRehearsal.value && Array.isArray(display.value.state_notes) ? display.value.state_notes : []))
function rehearsalMaterialLabel(material) { return REHEARSAL_MATERIAL_LABELS[material?.kind] || material?.kind || "素材" }

// 受影响项（M3-A）：仅 counterfactual / parent_child 对照回传；路径语法与
// 修订/锁定的 item_path 一致，逐项展示三态标签与 base/derived 摘录并排。
const AFFECTED_STATUS_LABELS = { changed: "变更", added: "新增", removed: "移除" }
function affectedStatusLabel(status) { return AFFECTED_STATUS_LABELS[status] || status }
function affectedPathLabel(itemPath) {
  const [family, index] = String(itemPath || "").split(":")
  if (family === "chain" || family === "gap" || family === "bridge") {
    const familyLabels = { chain: "影响链", gap: "缺口", bridge: "补桥" }
    return `${familyLabels[family]} ${Number(index) + 1}`
  }
  return family === "line" ? "对白" : String(itemPath || "")
}

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
    if (payload.variants) return payload.variants.map((item, index) => ({ key: `variant:${index}`, label: `人物对白 ${index + 1}`, text: item.line || "" }))
    if (payload.spatial_assessment) return [{ key: "spatial", label: "空间诊断", text: (payload.spatial_assessment.constraints || []).join("\n") }]
    return [{ key: "line", label: "这句对白", text: payload.line || "" }]
  }
  if (isFullRehearsal.value) return (payload.rounds || []).flatMap((round, r) => [
    ...(round.performances || []).map((item, index) => ({ key: `performance:${r}:${index}`, label: `第 ${r + 1} 轮表演 ${index + 1}`, text: item.line_or_beat || "" })),
    ...(round.materials || []).map((item, index) => ({ key: `material:${r}:${index}`, label: `第 ${r + 1} 轮素材 ${index + 1}`, text: item.text || "" })),
    ...(round.observations || []).map((item, index) => ({ key: `observation:${r}:${index}`, label: `第 ${r + 1} 轮观察 ${index + 1}`, text: item.observed || "" })),
  ])
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
const lockAvailable = computed(() => kind.value !== LOCK_SET && Boolean(current.value.resultId))
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

function draftKey(itemKey = revisionItemKey.value) { return `${DRAFT_PREFIX}:${props.projectId || "local"}:${current.value.resultId}:${itemKey}` }
function readDraft(itemKey = revisionItemKey.value) {
  try {
    const legacyKey = `${DRAFT_PREFIX}:${props.projectId || "local"}:${current.value.resultId}`
    const parsed = JSON.parse(localStorage.getItem(draftKey(itemKey)) || localStorage.getItem(legacyKey) || "null")
    if (parsed?.itemKey && parsed.itemKey !== itemKey) return null
    return parsed && typeof parsed.text === "string" ? parsed : null
  } catch { return null }
}
function writeDraft(itemKey = revisionItemKey.value) {
  try { localStorage.setItem(draftKey(itemKey), JSON.stringify({ text: editDraft.value, itemKey, updatedAt: new Date().toISOString() })); backupError.value = false; return true } catch { backupError.value = true; return false }
}
function clearDraft() {
  try {
    localStorage.removeItem(draftKey())
    const legacyKey = `${DRAFT_PREFIX}:${props.projectId || "local"}:${current.value.resultId}`
    const legacy = JSON.parse(localStorage.getItem(legacyKey) || "null")
    if (legacy?.itemKey === revisionItemKey.value) localStorage.removeItem(legacyKey)
  } catch { /* 已保存结果仍在服务端；未清除的备份下次可以恢复。 */ }
}

watch(revisionItemKey, (next, previous) => {
  if (restoringSelection) { restoringSelection = false; return }
  if (previous && editDraft.value && editDraft.value !== revisionItems.value.find(item => item.key === previous)?.text) {
    if (!writeDraft(previous)) { restoringSelection = true; revisionItemKey.value = previous; errorMessage.value = "草稿尚未备份，请先保存或复制，再切换条目。"; return }
  }
  const draft = readDraft(next)
  editing.value = Boolean(draft?.text)
  editDraft.value = draft?.text ?? selectedItem.value?.text ?? ""
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
  if (value !== (selectedItem.value?.text || "") && value.trim()) { editing.value = true; writeDraft() }
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
  status.value = { tone: "info", text: backupError.value ? "备份失败，草稿仅保留在本页，请先复制或保存。" : "草稿已在本机备份，保存成功前不会进入结果历史。" }
}

function editedPayload() {
  const clone = JSON.parse(JSON.stringify(display.value || {}))
  const text = editDraft.value.trim()
  const index = selectedItem.value ? Number(selectedItem.value.key.split(":")[1]) : -1
  if (isSandbox.value && selectedItem.value) clone.influence_chain[index].effect = text
  else if (isEvent.value && selectedItem.value) {
    if (selectedItem.value.key.startsWith("bridge")) clone.bridge_candidates[index].steps = text.split("\n").map(line => line.trim()).filter(Boolean)
    else clone.gaps[index].description = text
  } else if (isSceneLine.value) {
    if (selectedItem.value?.key.startsWith("variant:")) clone.variants[index].line = text
    else if (selectedItem.value?.key === "spatial") clone.spatial_assessment.constraints = text.split("\n").filter(Boolean)
    else clone.line = text
  } else if (isFullRehearsal.value && selectedItem.value) {
    const [family, round, item] = selectedItem.value.key.split(":")
    const [field, property] = { performance: ["performances", "line_or_beat"], material: ["materials", "text"], observation: ["observations", "observed"] }[family]
    clone.rounds[Number(round)][field][Number(item)][property] = text
  }
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
    const receipt = await getApi()?.story?.explorationSaveEdit(current.value.resultId, {
      novel_id: projectId,
      base_output_kind: effectiveKind.value,
      edited_payload: edited,
    })
    if (!receipt?.result_id) throw new Error("服务端没有返回已保存的新版本")
    savedLocally.value = true
    editing.value = false
    editDraft.value = ""
    clearDraft()
    current.value = { ...current.value, resultId: receipt.result_id, kind: receipt.output_kind || AUTHOR_EDIT, payload: receipt.payload || { base_output_kind: effectiveKind.value, base_result_id: current.value.resultId, edited_payload: edited } }
    saveView()
    status.value = { tone: "ok", text: "已保存编辑（形成新版本，原结果保持不变）。" }
    emit("refresh")
  } catch (error) {
    // 服务端失败：草稿保留（本页 + localStorage），明示失败原因。
    writeDraft()
    errorMessage.value = `保存未成功：${error?.message || "请稍后重试"}。${backupError.value ? "本地备份也失败，草稿仅在本页，请先复制文本再离开。" : "草稿已在本机备份，可再次保存。"}`
    status.value = { tone: "", text: "" }
  } finally { savingEdit.value = false }
}

function pickFollowUp(task) {
  const result = task?.result
  if (!result || typeof result !== "object") return null
  const wrapper = result.result && typeof result.result === "object" && result.result.output_kind ? result.result : result
  return wrapper.output_kind && wrapper.payload ? wrapper : null
}

function viewKey() { return `${DRAFT_PREFIX}:view:${props.projectId}:${props.source?.result_id || props.source?.task_id}` }
function saveView() {
  try {
    localStorage.setItem(viewKey(), JSON.stringify({ current: current.value, itemKey: revisionItemKey.value, locked: [...lockedItemPaths.value], taskId: activeTaskId.value, handoff: activeHandoff, handoffResult: handoffResult.value, paused: pausedReceipt.value, handoffStartRequest: handoffStartRequest.value, handoffDerived: handoffDerived.value, handoffConfirmation: handoffConfirmation.value, handoffTarget: handoffTarget.value, handoffReason: handoffReason.value }))
    return true
  } catch { return false }
}

async function previewResume() {
  try {
    const paused = pausedReceipt.value
    resumePreview.value = await getApi()?.story?.explorationResumePreview(paused.root_id, paused.branch_id, { novel_id: props.projectId })
    resumeUnknownAck.value = false
    resumeOperationId = createOperationId()
  } catch (error) { errorMessage.value = error?.message || "恢复预览暂不可用，请重试。" }
}

async function confirmResume() {
  if (!resumePreview.value || busy.value) return
  busy.value = true
  try {
    const preview = resumePreview.value
    const receipt = await getApi()?.story?.explorationResume(preview.root_id, preview.branch_id, {
      novel_id: props.projectId, operation_id: resumeOperationId, checkpoint_hash: preview.checkpoint_hash,
      additional_requests: resumeRequests.value, additional_tokens: resumeTokens.value,
      acknowledge_unknown_requests: resumeUnknownAck.value ? preview.requests_unknown : 0,
      allow_possible_duplicate_charge: resumeUnknownAck.value,
    })
    if (!receipt?.task_id) throw new Error("服务端没有返回恢复任务")
    pausedReceipt.value = null
    pollFollowUp(receipt.task_id, { handoff: activeHandoff })
  } catch (error) { busy.value = false; errorMessage.value = error?.message || "恢复未完成，请重试。" }
}

async function restoreLatest() {
  const history = await getApi()?.story?.explorationHistory?.({ novel_id: props.projectId, root_id: props.source?.root_id, limit: 100 })
  const row = history?.items?.find(item => (!props.source?.branch_id || item.branch_id === props.source.branch_id) && item.payload)
  if (row && !editing.value) {
    current.value = { resultId: row.result_id, kind: row.output_kind, payload: row.payload }
    revisionItemKey.value = revisionItems.value.find(item => item.key === revisionItemKey.value)?.key || revisionItems.value[0]?.key || ""
    const draft = readDraft()
    if (draft?.text) { editing.value = true; editDraft.value = draft.text }
    if (Array.isArray(row.locked_items)) lockedItemPaths.value = normalizeLockedPaths(row.locked_items)
    saveView()
  }
}

async function stopTask() {
  if (!activeTaskId.value) return
  try { const cancel = getApi()?.tasks?.cancel; if (!cancel) throw new Error("停止接口暂不可用，请稍后重试。"); await cancel(activeTaskId.value, props.projectId); status.value = { tone: "info", text: "已请求停止；正在核对任务最终状态。" } }
  catch (error) { errorMessage.value = error?.message || "停止请求未成功，请重试。" }
}

function pollFollowUp(taskId, { handoff = false } = {}) {
  poller?.stop?.()
  activeTaskId.value = taskId
  activeHandoff = handoff
  busy.value = true
  persistActiveWorkflow({ taskId, workflowType: "story_exploration", projectId: props.projectId, meta: { originResultId: props.source?.result_id || props.source?.task_id, handoff } })
  saveView()
  poller = pollTaskProgress({
    taskId,
    workflowType: "story_exploration",
    novelId: props.projectId,
    apiClient: getApi(),
    onUpdate: () => { if (!status.value.text || status.value.tone === "info") status.value = { tone: "info", text: "正在生成结果，可离开后回来查看。" } },
    onDone: (_progress, task) => {
      busy.value = false
      activeTaskId.value = ""
      if (task?.result?.needs_author_resume) {
        pausedReceipt.value = task.result
        status.value = { tone: "info", text: "探索已暂停，请核对预算或未知计费后恢复。" }
        saveView()
        return
      }
      const wrapper = pickFollowUp(task)
      if (wrapper) {
        if (handoff) {
          handoffResult.value = { ...wrapper, type: "story_exploration_result", scale: HANDOFF_SCALE_BY_KIND[wrapper.output_kind] || "scene_line", label: handoffDerived.value?.question || "移交后的探索" }
          status.value = { tone: "ok", text: "移交后的探索已完成，结果见下方。" }
          saveView()
          emit("refresh")
          return
        }
        followUps.value = [...followUps.value, { output_kind: wrapper.output_kind, payload: wrapper.payload }]
        current.value = { resultId: wrapper.result_id || current.value.resultId, kind: wrapper.output_kind, payload: wrapper.payload }
        if (Array.isArray(wrapper.locked_items)) lockedItemPaths.value = normalizeLockedPaths(wrapper.locked_items)
        revisionItemKey.value = revisionItems.value[0]?.key || ""
        revisionInstruction.value = ""
        status.value = { tone: "ok", text: "新结果已生成。" }
      } else {
        status.value = { tone: "ok", text: "新结果已生成，刷新讨论后即可查看。" }
      }
      saveView()
      void restoreLatest().catch(() => {})
      emit("refresh")
    },
    onFailed: (progress, task) => {
      busy.value = false
      activeTaskId.value = ""
      if (progress?.cancelled && task?.meta?.recovery_receipt) {
        pausedReceipt.value = task.meta.recovery_receipt
        status.value = { tone: "info", text: "生成已停止，已完成的进度仍在；可核对预算后恢复。" }
        errorMessage.value = ""
        saveView()
        return
      }
      saveView()
      status.value = { tone: "", text: "" }
      errorMessage.value = progress?.errorMessage || "这次生成没有完成；已保存的结果仍在。"
    },
  })
}

async function requestDetail() {
  const projectId = props.projectId
  if (!current.value.resultId || !projectId || busy.value || !canGenerate()) return
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
  if (!current.value.resultId || !projectId || busy.value || !item || !canGenerate()) return
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
    const history = await getApi()?.story?.explorationHistory({ novel_id: props.projectId, limit: 100 })
    const rows = []
    const collect = item => { if (item?.result_id && item.result_id !== current.value.resultId) rows.push({ result_id: item.result_id, label: item.label || SCALE_LABELS[item.scale] || item.result_id }) }
    for (const item of history?.items || []) collect(item)
    for (const root of history?.roots || []) {
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
    // 受影响项仅随 counterfactual / parent_child 回传；其余对照不引入新状态，
    // 渲染保持原样。保守披露时 affected_items 为空，仅显示粒度提示。
    const impactMode = receipt?.mode === "counterfactual" || receipt?.relation === "parent_child"
    comparison.value = {
      current: compactText(first.payload, first.output_kind),
      other: second ? compactText(second.payload, second.output_kind) : "对比结果暂不可读。",
      mode: receipt?.mode || "same_start",
      changed_conditions: Array.isArray(receipt?.changed_conditions) ? receipt.changed_conditions : [],
      relation: receipt?.relation || null,
      affectedItems: impactMode && Array.isArray(receipt?.affected_items) ? receipt.affected_items : [],
      affectedGranularity: impactMode ? receipt?.affected_items_granularity || null : null,
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

// --- M4-A 跨尺度移交链：handoff → confirmation/preview → confirm → 预算预览 → start ---
// 焦点取自移交理由输入（placeholder 即“想让这次推演聚焦什么”）；确认冻结的
// exploration_focus 与 start 请求必须一致，全链复用同一取值。

function handoffRequestBase() {
  return {
    novel_id: props.projectId,
    scale: handoffTarget.value,
    start: handoffDerived.value?.start,
    focus: handoffReason.value.trim(),
    action: HANDOFF_ACTION_BY_SCALE[handoffTarget.value],
  }
}

function blockerTexts(blockers) {
  if (!Array.isArray(blockers)) return []
  return blockers
    .map(item => (typeof item === "string" ? item : item?.reason || item?.message || ""))
    .filter(Boolean)
}

// 结果版本切换（补充/修订生成新结果）后，旧派生起点不再适用，整段移交状态重置。
watch(() => current.value.resultId, () => {
  handoffTarget.value = ""
  handoffReason.value = ""
  handoffDerived.value = null
  handoffConfirmation.value = null
  handoffOperationId.value = createOperationId()
  handoffStartRequest.value = null
})

async function requestHandoff() {
  const projectId = props.projectId
  if (!current.value.resultId || !projectId || handoffBusy.value || !handoffTarget.value) return
  handoffBusy.value = true
  errorMessage.value = ""
  try {
    const receipt = await getApi()?.story?.explorationHandoff(current.value.resultId, {
      novel_id: projectId,
      operation_id: createOperationId(),
      target_scale: handoffTarget.value,
      reason: handoffReason.value.trim(),
    })
    const start = receipt?.derived_start
    if (!start || typeof start !== "object") throw new Error("服务端没有返回派生起点")
    handoffDerived.value = {
      start,
      question: start.question || props.source?.label || "（未标注问题）",
      assumptionCount: Array.isArray(start.assumptions) ? start.assumptions.length : 0,
    }
    handoffConfirmation.value = null
    handoffOperationId.value = createOperationId()
    handoffStartRequest.value = null
    status.value = { tone: "ok", text: "移交预览已生成；确认资料范围后才会开始新任务。" }
  } catch (error) {
    // 4xx/409 服务端中文原因原样展示。
    errorMessage.value = error?.message || "移交预览暂时无法生成，请稍后重试。"
  } finally { handoffBusy.value = false }
}

async function previewHandoffConfirmation() {
  if (!handoffDerived.value || handoffBusy.value) return
  handoffBusy.value = true
  errorMessage.value = ""
  status.value = { tone: "info", text: "正在确认资料范围…" }
  try {
    const preview = await getApi()?.story?.explorationConfirmationPreview(handoffRequestBase())
    if (!preview?.context_fingerprint) throw new Error("服务端没有返回资料指纹")
    handoffConfirmation.value = {
      fingerprint: String(preview.context_fingerprint),
      selectedCount: Array.isArray(preview.selected_asset_ids) ? preview.selected_asset_ids.length : 0,
      sourceCount: Array.isArray(preview.sources) ? preview.sources.length : 0,
      blockers: blockerTexts(preview.blockers),
    }
  } catch (error) {
    status.value = { tone: "", text: "" }
    errorMessage.value = error?.message || "资料范围暂时无法确认，请稍后重试。"
  } finally { handoffBusy.value = false }
}

async function confirmAndStartHandoff() {
  const confirmation = handoffConfirmation.value
  if (!confirmation || handoffBusy.value || busy.value) return
  handoffBusy.value = true
  errorMessage.value = ""
  status.value = { tone: "info", text: "正在确认资料范围并启动新任务…" }
  try {
    if (!handoffStartRequest.value) {
      const confirmed = await getApi()?.story?.explorationConfirm({
      ...handoffRequestBase(),
      expected_context_fingerprint: confirmation.fingerprint,
    })
    if (!confirmed?.confirmation_id) throw new Error("服务端没有返回确认标识")
    // start 校验请求携带的 budget_preview_hash；确认链不回传预算，这里补一次
    // /preview 取派生起点在当前尺度/焦点下的预算指纹（确定性，无模型调用）。
    const budgetPreview = await getApi()?.story?.explorationPreview({
      novel_id: props.projectId,
      scale: handoffTarget.value,
      start: handoffDerived.value.start,
      focus: handoffReason.value.trim(),
    })
    const budgetHash = budgetPreview?.budget?.preview_hash
    if (!budgetHash) throw new Error("服务端没有返回预算预览标识")
      handoffStartRequest.value = {
      ...handoffRequestBase(),
      context_confirmation_id: confirmed.confirmation_id,
      budget_preview_hash: budgetHash,
      operation_id: handoffOperationId.value,
      time_budget_seconds: 3600,
      }
      if (!saveView()) throw new Error("任务标识无法在本机保存，请恢复浏览器存储后再开始，以便安全重试")
    }
    const receipt = await getApi()?.story?.explorationStart(handoffStartRequest.value)
    if (!receipt?.task_id) throw new Error("服务端没有返回任务标识")
    pollFollowUp(receipt.task_id, { handoff: true })
    status.value = { tone: "info", text: "已在新任务中继续，正在跟踪生成进度。" }
    emit("refresh")
  } catch (error) {
    status.value = { tone: "", text: "" }
    errorMessage.value = error?.message || "新任务暂时无法开始，请稍后重试。"
  } finally { handoffBusy.value = false }
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
  } else if (kindValue === FULL_REHEARSAL) {
    // 与后端历史摘要一致：取首轮第一张表演卡的台词/节拍作摘要。
    const firstCard = (payload.rounds || [])[0]?.performances?.[0]
    text.push(firstCard?.line_or_beat || "（完整排演）")
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

const unsafeDraft = computed(() => backupError.value && Boolean(editDraft.value.trim()) && editDraft.value !== (selectedItem.value?.text || ""))
function canGenerate() {
  if (editDraft.value.trim() && editDraft.value !== (selectedItem.value?.text || "")) {
    errorMessage.value = "请先保存当前编辑，再基于保存后的版本继续生成。"
    return false
  }
  return true
}
function canLeave() { if (!unsafeDraft.value) return true; errorMessage.value = "编辑尚未保存或备份，请先保存或复制文本。"; return false }
const removeLeaveGuard = registerAuxiliaryLeaveGuard(canLeave)
function beforeUnload(event) { if (unsafeDraft.value) { event.preventDefault(); event.returnValue = "" } }
globalThis.addEventListener?.("beforeunload", beforeUnload)
defineExpose({ canLeave })
onMounted(() => {
  try {
    const saved = initialView
    if (saved?.current && !editing.value) current.value = saved.current
    if (saved?.locked) lockedItemPaths.value = normalizeLockedPaths(saved.locked)
    handoffResult.value = saved?.handoffResult || null
    pausedReceipt.value = saved?.paused || pausedReceipt.value
    handoffStartRequest.value = saved?.handoffStartRequest || null
    handoffDerived.value = saved?.handoffDerived || null
    handoffConfirmation.value = saved?.handoffConfirmation || null
    handoffTarget.value = saved?.handoffTarget || ""
    handoffReason.value = saved?.handoffReason || ""
    const originId = props.source?.result_id || props.source?.task_id
    const workflow = recoverActiveWorkflows(props.projectId).find(item => item.workflowType === "story_exploration" && originId && item.meta?.originResultId === originId)
    const taskId = workflow?.taskId || saved?.taskId
    if (taskId) { pollFollowUp(taskId, { handoff: workflow?.meta?.handoff ?? saved?.handoff }); return }
  } catch { /* 已保存内容可以从服务端历史恢复。 */ }
  void restoreLatest().catch(() => {})
})
onBeforeUnmount(() => { saveView(); poller?.stop?.(); poller = null; removeLeaveGuard(); globalThis.removeEventListener?.("beforeunload", beforeUnload) })
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
.exploration-result-card__compare-summary{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.exploration-result-card__relation-tag,.exploration-result-card__impact-tag{padding:2px 8px;border-radius:999px;font-size:12px}
.exploration-result-card__relation-tag{background:#e6efeb;color:#36594e;font-weight:600}
.exploration-result-card__impact-tag{background:#f3e8d2;color:#8a6116}
.exploration-result-card__affected{grid-column:1/-1;min-width:0}
.exploration-result-card__affected h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__affected-list{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.exploration-result-card__affected-item{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:8px;background:var(--bg-muted);min-width:0}
.exploration-result-card__affected-head{margin:0 0 4px;display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.exploration-result-card__affected-status{padding:1px 8px;border-radius:999px;font-size:12px}
.exploration-result-card__affected-status--changed{background:#f3e8d2;color:#8a6116}
.exploration-result-card__affected-status--added{background:#e6efeb;color:#36594e}
.exploration-result-card__affected-status--removed{background:#f7e4e2;color:#9c2d29}
.exploration-result-card__affected-excerpts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.exploration-result-card__affected-excerpts p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}
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
.exploration-result-card__round{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:8px;margin:8px 0;min-width:0}
.exploration-result-card__round h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__round .exploration-result-card__variant{margin:6px 0}
.exploration-result-card__round .exploration-result-card__list{margin:4px 0}
.exploration-result-card__compare section{padding:8px;border-radius:8px;background:var(--bg-muted);min-width:0}
.exploration-result-card__compare h4{margin:0 0 6px;font-size:13px}
.exploration-result-card__compare p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font-size:13px}
.exploration-result-card__targets{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.exploration-result-card__target{padding:4px 12px;border:1px solid var(--border-color,var(--border));border-radius:999px;background:var(--bg-muted);color:inherit;font:inherit;font-size:13px;cursor:pointer}
.exploration-result-card__target--on{background:#e6efeb;border-color:#b7d2c7;color:#36594e;font-weight:600}
.exploration-result-card__target:disabled{opacity:.6;cursor:default}
.exploration-result-card__derived{margin-top:8px;display:grid;gap:2px}
.exploration-result-card__derived h4{margin:0 0 4px;font-size:13px}
.exploration-result-card__error{color:var(--danger);font-size:13px;margin:8px 0;overflow-wrap:anywhere}
.exploration-result-card button:focus-visible,.exploration-result-card select:focus-visible,.exploration-result-card textarea:focus-visible,.exploration-result-card summary:focus-visible{outline:3px solid rgba(81,127,111,.35);outline-offset:2px}
@media(max-width:700px){.exploration-result-card__actions{flex-direction:column}.exploration-result-card__op{flex-basis:auto}.exploration-result-card__compare{grid-template-columns:1fr}.exploration-result-card__affected-excerpts{grid-template-columns:1fr}}
</style>
