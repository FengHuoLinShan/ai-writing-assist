<template>
  <section v-if="state.available || state.feed?.items?.length || standalone || state.error" class="forecast-dock" aria-label="下一步建议" @focusin="subscription.activate()" @pointerdown="subscription.activate()">
    <header><div><span class="forecast-kicker">{{ context.page === 'writing' ? '写到这里' : '当前工作' }}</span><h3>{{ context.page === 'writing' ? '接下来，可以怎样写' : '接下来，先做什么' }}</h3></div><button class="btn btn-sm btn-ghost" type="button" :disabled="state.loading" @click="refresh">刷新资料</button></header>
    <p class="forecast-subtitle">几个有依据的方向，留给你选择。</p>
    <form @submit.prevent="evaluate">
      <label>这次要做什么 <select v-model="intent" aria-label="当前写作意图"><option value="unknown">一起想下一步</option><option value="continue">续写</option><option value="polish">只润色</option><option value="revise">修改</option><option value="review">检查事实</option><option value="design">探索设定</option></select></label>
      <label class="forecast-instruction">这次想保留什么 <span>可选</span><textarea :value="state.instruction" maxlength="4000" rows="2" placeholder="例如：不要揭露身份，保持克制" @input="forecast.setInstruction($event.target.value)" /></label>
      <div class="forecast-actions"><button class="btn btn-primary btn-sm" type="submit" :disabled="!canAnalyze || state.busy || running || dirty || isComposing">{{ state.busy ? '正在提交…' : '帮我想下一步' }}</button><button v-if="running" class="btn btn-sm" type="button" :disabled="state.busy" @click="forecast.cancel">停止</button></div>
    </form>
    <p v-if="dirty" class="forecast-note">尚有未保存文字；只查看上次保存的资料。保存后可以分析与试写。</p>
    <p v-if="running" role="status">正在核对资料与准备方向，可以继续写作或离开此页。</p>
    <p v-if="state.run && !running && state.run.status !== 'completed'" role="status">{{ runLabel }}</p>
    <button v-if="state.run?.can_resume" class="btn btn-sm" type="button" :disabled="dirty || state.busy" @click="forecast.resume">继续原分析（保留用量）</button>
    <p v-if="state.error" class="forecast-error" role="alert">{{ state.error }}</p>
    <p v-if="state.backupError" class="forecast-error" role="alert">本地备份不可用。输入和未确认的操作仍在此页，请勿刷新。</p>
    <button v-if="state.pending" class="btn btn-sm" type="button" :disabled="state.busy" @click="forecast.recover">找回上次提交</button>
    <button v-if="state.pendingFeed" class="btn btn-sm" type="button" :disabled="isComposing" @click="forecast.acceptFeed">有新的资料与结果，点击更新</button>
    <p v-if="state.stale" class="forecast-note">保存版本已变化，当前展开内容仅供对照。</p>
    <div v-if="state.feed?.items?.length" class="forecast-items">
      <article v-for="item in state.feed.items" :key="item.issue_key" class="forecast-card">
        <span class="forecast-kind">{{ kindLabel(item.kind) }}<template v-if="item.notice_status === 'snoozed'"> · 已暂缓</template><template v-if="item.notice_status === 'dismissed'"> · 已保留原方向</template></span>
        <h4>{{ item.title }}</h4><p>{{ item.why_now }}</p>
        <details @toggle="hold($event)"><summary>依据、选择与未知</summary>
          <p v-for="(statement, index) in item.statements" :key="index"><strong>{{ { observed: '原文观察', inferred: '可能解释', proposed: '创作选项' }[statement.basis] }}：</strong>{{ statement.text }}</p>
          <div v-for="direction in item.directions" :key="direction.direction_id" class="forecast-direction"><strong>{{ direction.title }}</strong><p>{{ direction.condition }}</p><p>{{ direction.proposal }}</p><ul v-if="direction.possible_effects?.length"><li v-for="effect in direction.possible_effects" :key="effect">{{ effect }}</li></ul><small v-if="direction.assumptions?.length">需要的前提：{{ direction.assumptions.join('；') }}</small><button class="btn btn-sm btn-ghost" type="button" :disabled="state.busy || state.stale" @click="forecast.decide(item, 'not_this_direction', { direction_id: direction.direction_id })">暂不走这个方向</button></div>
          <p v-if="item.unknowns.length">仍未知：{{ item.unknowns.join('；') }}</p>
          <small>{{ item.basis_label }}</small>
          <div v-for="reference in item.evidence" :key="reference.evidence_id" class="forecast-reference"><span>{{ reference.label }}</span><button v-if="reference.source_range" class="btn btn-sm btn-ghost" type="button" :disabled="dirty" @click="locate(reference)">定位原文</button></div>
        </details>
        <div class="forecast-actions"><button v-if="item.navigation" class="btn btn-sm" type="button" :disabled="state.stale" @click="forecast.openDomain(item)">在原页面处理</button><button v-for="action in item.actions.filter(action => action.kind === 'prepare_domain' || action.action_id.startsWith('writing.discuss_revision.'))" :key="action.action_id" class="btn btn-sm" type="button" :disabled="!action.available || dirty || state.busy || state.stale" :title="action.unavailable_reason || undefined" @click="forecast.prepare(item, action)">{{ action.label }}</button></div>
        <div class="forecast-decisions"><button v-if="['snoozed', 'dismissed'].includes(item.notice_status)" type="button" :disabled="state.busy" @click="forecast.decide(item, 'reopen')">重新留意</button><template v-else><button type="button" :disabled="state.busy" @click="forecast.decide(item, 'keep_observing')">继续留意</button><button type="button" :disabled="state.busy" @click="forecast.decide(item, 'as_ordinary_detail')">只是普通细节</button><button type="button" :disabled="state.busy" @click="deferral = { item, kind: 'manual_reopen', at: '' }">稍后再看</button></template></div>
        <form v-if="deferral?.item.candidate_id === item.candidate_id" @submit.prevent="snooze"><label>何时重新留意<select v-model="deferral.kind"><option value="manual_reopen">我手动重开时</option><option value="at_time">指定时间</option><option v-if="state.focus?.scene_id" value="scene_activated">下次打开当前场景时</option><option v-if="state.focus?.draft_id" value="chapter_completed">当前章稿设为正式正文时</option><option v-if="objectReference(item)" value="object_reappears">对象在后续已同步章节再次出现时</option></select></label><input v-if="deferral.kind === 'at_time'" v-model="deferral.at" type="datetime-local" aria-label="重新留意时间" required /><button type="submit" class="btn btn-sm" :disabled="state.busy">保存暂缓条件</button><button type="button" class="btn btn-sm" @click="deferral = null">取消</button></form>
      </article>
      <button v-if="state.feed.next_cursor" class="btn btn-sm" type="button" :disabled="state.loading" @click="forecast.more">查看其余事项</button>
    </div>
    <p v-else class="forecast-empty">{{ emptyLabel }}</p>
    <section v-if="state.prepared" class="forecast-preview" aria-label="所选方向的操作预览"><h4>核对这一项选择</h4><template v-if="state.preparationRun?.result?.actions?.length"><article v-for="action in state.preparationRun.result.actions" :key="action.key"><strong>{{ action.title }}</strong><p>{{ action.preview?.effect }}</p><AssistantValue :value="action.preview?.after" /></article><button v-if="!state.prepared.outcome" class="btn btn-primary btn-sm" type="button" :disabled="dirty || state.busy || state.prepared.status !== 'preview_ready'" @click="forecast.confirm">确认这一项</button></template><p v-else>正在恢复具体预览，读取成功后才能确认。</p><p v-if="state.prepared.outcome" role="status">{{ state.prepared.outcome.status === 'completed' ? '这一项已完成。' : '尚有未完成的部分，请查看原处理记录。' }}</p><p v-for="result in state.prepared.outcome?.results || []" :key="result.key">{{ result.result?.label || result.message }}</p></section>
    <button v-if="state.run?.coverage?.counts?.not_checked || state.run?.coverage?.omissions?.length" type="button" class="btn btn-sm" :disabled="state.busy || running || dirty || isComposing" @click="forecast.revisit">重新核对上次未覆盖的部分</button>
    <details class="forecast-settings"><summary>资料范围与主动提醒</summary><p>{{ state.feed?.coverage?.scope_label || '只读取当前账户已授权的保存资料。' }}</p><p v-if="state.feed?.coverage?.counts?.source_invalid">有 {{ state.feed.coverage.counts.source_invalid }} 项旧判断需要重新核对。</p><label><input v-model="state.includeDeferred" type="checkbox" @change="refresh" /> 显示已暂缓与已处置事项</label><label v-if="state.policy"><input :checked="state.policy.policy.automatic" type="checkbox" :disabled="state.busy" @change="forecast.saveAutomatic($event.target.checked)" /> 保存后主动帮我留意</label><p>与原主动检查共用每日 {{ state.policy?.policy?.shared_daily_limit || 12 }} 次后台额度；默认不联网。可以随时关闭。</p></details>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue"
import { locateForecastEvidence, getToast, useStateKey } from "../bridge/index.js"
import { subscribeForecast } from "../composables/forecastStore.js"
import AssistantValue from "./AssistantValue.vue"

const props = defineProps({ projectId: { type: String, default: null }, context: { type: Object, default: () => ({ page: "today" }) }, editor: { type: Object, default: null }, composing: Boolean, active: { type: Boolean, default: true }, standalone: Boolean })
const writingState = useStateKey("_writingForecastState")
const editorState = computed(() => props.editor || (writingState.value?.projectId === props.projectId ? writingState.value : null))
const isComposing = computed(() => props.composing || editorState.value?.composing === true)
let subscription = subscribeForecast(props.projectId)
const forecast = shallowRef(subscription.forecast)
const state = computed(() => forecast.value.state)
const intent = ref(props.context.task_hint || "unknown")
watch(() => props.context.task_hint, value => { intent.value = value || "unknown" })
const deferral = ref(null)
const objectReference = item => item.evidence.find(value => value.resource_kind === "core_entity")
async function snooze() {
  const selection = deferral.value, condition = { kind: selection.kind }
  if (condition.kind === "at_time") condition.at = new Date(selection.at).toISOString()
  else if (condition.kind === "scene_activated") condition.target_id = state.value.focus.scene_id
  else if (condition.kind === "chapter_completed") condition.target_id = state.value.focus.draft_id
  else if (condition.kind === "object_reappears") { const ref = objectReference(selection.item); condition.object_id = ref.resource_id; condition.after_event_token = ref.revision_token }
  await forecast.value.decide(selection.item, "snooze", { wake_condition: condition })
  if (!state.value.error) deferral.value = null
}
watch(() => props.projectId, () => { deferral.value = null })
const dirty = computed(() => forecast.value.dirty())
const running = computed(() => ["pending", "running"].includes(state.value.run?.status))
const canAnalyze = computed(() => !state.value.loading && !state.value.stale && state.value.available && state.value.capabilities.some(item => item.available))
const emptyLabel = computed(() => ({ ready: "这次没有其他需要提示的内容。", empty: "本轮没有需要提示的内容，可以继续写作。", not_checked: "还没有分析这一处。已有保存资料可以直接查看。", disabled: "前瞻暂未开启，普通写作与已有成果仍保留。", unavailable: "当前能力不可用，仍可继续编辑。", stale: "资料版本已变化，重新分析后会给出当前建议。" })[state.value.feed?.state] || "打开章节或资料后，可以从当前任务出发。")
const runLabel = computed(() => ({ failed: "这次分析未完成，原稿与已保存结果仍保留。", cancelled: "已停止后续分析。", budget_exceeded: "本次分析已达到额度，已有结果仍保留。" })[state.value.run?.status] || "")
const kindLabel = kind => ({ prepared_reference: "相关资料", next_step: "下一步", creative_opportunity: "创作选项", impact_preview: "影响预览", decision_prompt: "一个待定问题" })[kind] || "建议"
function hold(event) { state.value.hold = [...event.currentTarget.closest(".forecast-items").querySelectorAll("details")].some(item => item.open) }
async function evaluate() { if (await subscription.activate()) await forecast.value.evaluate() }
async function refresh() { try { await forecast.value.refresh() } catch (error) { state.value.error = error.message || "资料暂时无法刷新。" } }
async function locate(reference) { try { if (!await locateForecastEvidence(props.projectId, reference)) getToast()("请先打开对应的正文版本。", "info") } catch (error) { state.value.error = error.message } }
watch(() => [props.projectId, JSON.stringify(props.context), editorState.value?.draftId, editorState.value?.sceneId, editorState.value?.dirty, editorState.value?.saving, editorState.value?.lastSavedContent ?? editorState.value?.savedContent, isComposing.value, props.active, intent.value], (values, previous) => {
  if (previous && values[0] !== previous[0]) { subscription.release(); subscription = subscribeForecast(props.projectId); forecast.value = subscription.forecast }
  subscription.update({ context: { ...props.context, task_hint: intent.value }, editor: editorState.value, composing: isComposing.value, active: props.active, priority: props.standalone ? 2 : 1 })
}, { immediate: true })
onBeforeUnmount(() => subscription.release())
</script>

<style scoped>
.forecast-dock{padding:18px 16px;color:var(--text-primary);min-width:0;font-size:13px;line-height:1.65}.forecast-dock header{display:flex;justify-content:space-between;align-items:start;gap:8px}.forecast-kicker,.forecast-kind{font-size:11px;letter-spacing:.08em;color:var(--text-secondary)}.forecast-dock h3{font-size:17px;margin:3px 0}.forecast-dock h4{font-size:15px;line-height:1.5;margin:5px 0}.forecast-subtitle,.forecast-note,.forecast-empty{color:var(--text-secondary);margin:8px 0 14px}.forecast-instruction{display:block}.forecast-instruction span{color:var(--text-secondary);font-size:11px}.forecast-instruction textarea{width:100%;box-sizing:border-box;resize:vertical;min-height:64px;padding:9px;border:1px solid var(--border-color,var(--border));border-radius:7px;font:inherit;color:inherit;background:var(--bg-primary,var(--bg-base));margin-top:6px}.forecast-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.forecast-card{border-top:1px solid var(--border-color,var(--border));padding:16px 0}.forecast-card p{margin:7px 0;white-space:pre-wrap;overflow-wrap:anywhere}.forecast-card details{margin-top:10px}.forecast-card summary,.forecast-settings summary{cursor:pointer;min-height:32px}.forecast-direction{padding:12px;border-left:2px solid var(--accent,var(--primary));background:var(--bg-muted);margin:10px 0}.forecast-reference{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px}.forecast-decisions{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}.forecast-decisions button{border:0;background:transparent;color:var(--text-secondary);font:inherit;cursor:pointer;padding:4px 0;min-height:32px}.forecast-settings{border-top:1px solid var(--border-color,var(--border));padding-top:12px;margin-top:16px;font-size:12px;color:var(--text-secondary)}.forecast-settings label{display:flex;align-items:center;gap:8px;min-height:38px}.forecast-preview{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:12px;margin:16px 0;background:var(--bg-muted)}.forecast-error{color:var(--danger);overflow-wrap:anywhere}.forecast-dock button:focus-visible,.forecast-dock summary:focus-visible,.forecast-dock textarea:focus-visible{outline:2px solid var(--accent,var(--primary));outline-offset:3px}@media(max-width:700px){.forecast-dock button{min-height:42px}.forecast-instruction textarea{font-size:16px}}
</style>
