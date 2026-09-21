<template>
  <section class="creative-experiments" aria-label="隔离试改">
    <header><span class="creative-kicker">创作试验</span><h3>先试一试，再决定</h3><p>查清原因，比较实际改法，保留原稿作对照。</p></header>
    <p v-if="loading" role="status">正在恢复试改记录…</p>
    <p v-if="error" class="creative-error" role="alert">{{ error }}</p>
    <p v-if="backupError" class="creative-error" role="alert">本地备份不可用，输入仍在此页，请勿刷新。</p>
    <label v-if="cases.length" class="creative-label">继续已有目标<select :value="currentCase?.id || ''" :disabled="busy" @change="selectCase($event.target.value)"><option value="">新的创作目标</option><option v-for="item in cases" :key="item.id" :value="item.id">{{ item.goal }}</option></select></label>
    <form @submit.prevent="start()"><fieldset class="creative-form-fields" :disabled="busy">
      <label class="creative-label">想解决什么<textarea v-model="goal" rows="3" maxlength="8000" placeholder="例如：主角为什么会突然相信旧敌？" @input="saveDraft" /></label>
      <label class="creative-label">必须保留什么<textarea v-model="constraints" rows="2" placeholder="一行一项，例如：不提前揭露身份，不改变本章结局" @input="saveDraft" /></label>
      <label v-if="!currentCase" class="creative-label">这次怎样帮助你<select v-model="recipeId" @change="saveDraft"><option v-for="recipe in capabilities.recipes || []" :key="recipe.id" :value="recipe.id">{{ recipe.label }}</option></select></label>
      <fieldset v-if="(!currentCase || grantEditing) && recipeId !== 'import_consult'"><legend>本次参考与试改范围</legend><label v-for="resource in resources" :key="resource.kind + resource.id"><input v-model="selectedResources" type="checkbox" :value="resource.kind + ':' + resource.id" /> {{ resource.label }}</label><button type="button" class="btn btn-sm" @click="loadResources()">选择其他章节或资料</button><label>资料类型<select v-model="resourceKind"><option value="writing_draft">正文</option><option value="scene">场景安排</option><option value="world_bible_draft">世界书工作稿</option><option value="foreshadowing_plan">伏笔计划</option><option value="reveal_plan">揭示计划</option></select></label><button v-if="nextResourceOffset !== null" type="button" class="btn btn-sm" @click="loadResources(nextResourceOffset)">继续读取资料</button><p v-if="!resources.length">请从正文、场景或世界书工作稿发起；当前页面没有可试改的资源。</p></fieldset>
      <div v-if="grantEditing" class="creative-note"><p>将改用上方明确选中的资料，保留累计用量与旧回执。原资料确认不自动继承，新范围仍需逐次检查与确认。</p><button type="button" class="btn btn-sm" :disabled="busy || !selectedResources.length" @click="saveGrantSelection">确认更新本次资料</button><button type="button" class="btn btn-sm" @click="grantEditing = false">取消</button></div>
      <fieldset v-if="!currentCase && recipeId === 'import_consult'"><legend>选择原导入待决组</legend>
        <button type="button" class="btn btn-sm" :disabled="busy" @click="loadImportGroups">读取原待决列表</button>
        <label>起始章节<input v-model.number="chapterFrom" type="number" min="1" @input="saveDraft" /></label><label>结束章节<input v-model.number="chapterTo" type="number" :min="chapterFrom" :max="chapterFrom + 19" @input="saveDraft" /></label>
        <label v-for="(item, index) in importCandidates" :key="item.key"><input v-model="importKeys" type="checkbox" :value="item.key" @change="saveDraft" />{{ importLabel(item, index) }}</label>
        <p>只会诊所选原组及对应原文；采用仍回到原整理页面确认。</p>
      </fieldset>
      <fieldset v-if="!currentCase && recipeId === 'blind_reader'"><legend>阅读进度</legend><label>截止章节<input v-model.number="readingCutoff" type="number" min="1" @input="saveDraft" /></label><label v-for="item in resources.filter(item => item.kind === 'writing_draft' && selectedResources.includes(item.kind + ':' + item.id))" :key="item.id">{{ item.label }} · 在这些字数处先停下（以逗号分隔；留空则读到章末）<input v-model="readingStops[item.kind + ':' + item.id]" placeholder="例如：800，1600" @input="saveDraft" /></label><p>合计最多八个停点。每次先冻结理解与疑问，再读后面的文字。</p></fieldset>
      <details v-if="!currentCase"><summary>参考范围、连接与自定义检查</summary><label v-if="recipeId !== 'import_consult'"><input v-model="followChanges" type="checkbox" @change="saveDraft" />保存后自动跟进这个目标：沿用本次累计上限，并与项目后台检查共享日额度；采用仍需确认</label>
        <label v-if="recipeId !== 'import_consult'"><input v-model="readScope" type="checkbox" true-value="project" false-value="selected" @change="saveDraft" />允许在本作品补查，仍只试改上方所选内容</label>
        <label v-if="recipeId !== 'blind_reader'"><input v-model="allowWeb" type="checkbox" :disabled="!capabilities.web_search?.available" @change="saveDraft" />允许按需查证公开的现实资料</label><p>{{ capabilities.web_search?.disclosure }}</p>
        <label v-for="role in [{ key: 'plan', label: '规划' }, { key: 'member', label: '调查与试改' }, { key: 'check', label: '独立复核' }]" :key="role.key" class="creative-label">{{ role.label }}<select :value="modelConnections[role.key] || ''" @change="chooseConnection(role.key, $event.target.value)"><option value="">当前默认连接</option><option v-for="connection in capabilities.model_connections || []" :key="connection.provider_id" :value="connection.provider_id">{{ connection.label }}</option></select></label>
        <label class="creative-label">自定义问题（最多六项，每行一项）<textarea v-model="customQuestions" rows="2" maxlength="6000" @input="saveDraft" /></label>
        <label class="creative-label">补充检查（每行一项，保留原检查）<textarea v-model="extraChecks" rows="2" maxlength="6000" @input="saveDraft" /></label>
      </details>
      <p v-if="dirty" class="creative-note">当前编辑器有未保存输入，请保存后再开始或采用。</p>
      <div class="creative-actions"><button class="btn btn-primary" type="submit" :disabled="busy || running || dirty || !capabilities.enabled || !goal.trim() || (!currentCase && (recipeId === 'import_consult' ? !importKeys.length : !selectedResources.length))">{{ busy ? '正在提交…' : currentCase ? '按这个目标继续' : '开始调查与试改' }}</button><button v-if="running" class="btn" type="button" :disabled="busy" @click="stop">停止</button></div>
      <p v-if="!capabilities.enabled" class="creative-note">创作试验尚未开启；已有记录仍可查看。</p>
    </fieldset></form>
    <p v-if="pending" class="creative-note">上次提交结果尚未确认。<button class="btn btn-sm" type="button" :disabled="busy" @click="recover">恢复原请求</button></p>
    <section v-if="currentCase" class="creative-history"><div class="creative-actions"><strong>这一目标的进展</strong><button class="btn btn-sm btn-ghost" type="button" :disabled="loading" @click="refreshCase">刷新</button></div><select v-if="runs.length" aria-label="查看一次调查" :value="run?.id || ''" @change="openRun($event.target.value)"><option v-for="item in runs" :key="item.id" :value="item.id">{{ dateLabel(item.created_at) }} · {{ statusLabel(item.status) }}</option></select><p v-if="run" role="status">{{ statusLabel(run.status) }}<template v-if="run.stale"> · 资料或目标已变化，请重新核对。</template></p><p v-for="missing in run?.missing_deliverables || []" :key="missing">尚未完成：{{ missing }}</p><button v-if="run?.can_resume" class="btn btn-sm" type="button" :disabled="busy" @click="resume">从已有成果继续</button><details><summary>本次授权</summary><button v-if="currentCase.recipe.id !== 'import_consult'" type="button" class="btn btn-sm" :disabled="busy || running" @click="grantEditing = true">重新选择本次资料</button><button v-else type="button" class="btn btn-sm" :disabled="busy || running" @click="refreshImportGrant">重新核对原组来源</button><p v-if="currentCase.grant.follow_changes">正在自动跟进资料变化，后台默认不联网。</p><button v-if="currentCase.grant.follow_changes" class="btn btn-sm" type="button" :disabled="busy" @click="pauseFollow">关闭后续自动跟进</button><p>累计已用 {{ currentCase.requests_used }} / {{ currentCase.grant.request_limit }} 次请求，截止 {{ dateLabel(currentCase.grant.expires_at) }}。</p><button type="button" class="btn btn-sm" :disabled="busy || running" @click="renewGrant">按原范围续期一天，保留用量</button></details><p v-if="run?.question_for_author">还需要你决定：{{ run.question_for_author }}</p><p v-if="run?.coverage">已完成本次 {{ run.coverage.completed }} / {{ run.coverage.total }} 项工作；这不代表穷尽全部文学问题。</p><article v-for="artifact in visibleReports" :key="artifact.id" class="creative-report"><p>{{ artifact.result.summary }}</p><details v-if="artifact.result.claims?.length"><summary>判断依据与保留解释</summary><p v-for="(claim, index) in artifact.result.claims" :key="index"><strong>{{ claimLabel(claim.kind) }}：</strong>{{ claim.text }}<small v-if="claim.uncertainty"> {{ claim.uncertainty }}</small></p></details><details v-if="artifact.result.beliefs"><summary>此刻已知、猜测与未解问题</summary><p v-for="belief in artifact.result.beliefs.known" :key="belief.belief">此刻理解：{{ belief.belief }}<br />依据：{{ belief.excerpt }}</p><p v-for="belief in artifact.result.beliefs.guesses" :key="belief.belief">仍是猜测：{{ belief.belief }}<br />依据：{{ belief.excerpt }}</p><p v-for="question in artifact.result.beliefs.unanswered" :key="question">仍未知：{{ question }}</p><p v-for="belief in artifact.result.beliefs.newly_revealed" :key="belief.belief">此处新揭示：{{ belief.belief }}</p></details><details v-if="artifact.result.scenarios?.length"><summary>冻结的检验情境</summary><article v-for="scenario in artifact.result.scenarios" :key="scenario.key"><strong>{{ scenario.title }}</strong><p>{{ scenario.invariant }}</p><p>期望：{{ { holds: "规则在这些条件下成立", violated: "保留这个明确反例", unchanged: "与原稿一致，可能保留既有例外" }[scenario.expected] }}</p><p v-for="action in scenario.actions" :key="action">{{ action }}</p><p v-if="scenario.assumptions.length">条件：{{ scenario.assumptions.join('；') }}</p></article></details><details v-if="artifact.evidence?.length"><summary>本次实际查阅的来源</summary><article v-for="source in artifact.evidence" :key="source.key"><strong>{{ source.label }}</strong><p v-if="source.excerpt">{{ source.excerpt }}</p><a v-if="publicUrl(source.url)" :href="publicUrl(source.url)" target="_blank" rel="noopener noreferrer">查看网页原文</a></article></details><p v-if="artifact.result.omissions?.length">尚未核对：{{ artifact.result.omissions.join('；') }}</p></article></section>
    <section v-if="workspaces.length" class="creative-trials" aria-label="试改方案"><h4>实际改法与原稿对照</h4><button v-for="item in workspaces" :key="item.id" class="creative-trial-button" type="button" :aria-pressed="trial?.id === item.id" :disabled="busy" @click="openTrial(item.id)"><strong>{{ item.label }}</strong><span>{{ { open: '可继续试改', sealed: '已核对，待采用', merged: '已采用', discarded: '已保留原稿' }[item.status] || '试改记录' }}</span></button></section>
    <CreativeTrialEditor v-if="trial" ref="trialEditor" :project-id="projectId" :trial="trial" :locked="busy || running || dirty" @updated="trialUpdated" />
    <section v-if="trial" class="creative-diff" aria-label="所选试改对照"><h4>{{ trial.label }}</h4><p v-if="trial.stale" class="creative-note">参考资料或目标已变化，旧试改不能直接采用。</p><p v-else-if="!trial.changes.length">这一版尚无修改。</p><article v-for="change in trial.changes" :key="change.resource.kind + change.resource.id"><strong>{{ change.label }}</strong><div class="creative-comparison"><div><small>原稿</small><AssistantValue :value="readable(change.before)" /></div><div><small>{{ change.operation === 'delete' ? '试验中移除' : '试改' }}</small><AssistantValue :value="readable(change.after)" /></div></div></article><p v-if="trial.check">{{ { passed: '这一版检查通过', blocked: '这一版还有需修复的问题', uncertain: '目前还不能确认通过' }[trial.check.verdict] }}</p><ul v-if="trial.check?.findings?.length"><li v-for="finding in trial.check.findings" :key="finding">{{ finding }}</li></ul><p v-if="trial.check?.omissions?.length">未检查：{{ trial.check.omissions.join('；') }}</p><div class="creative-actions"><button class="btn" type="button" :disabled="busy || running || dirty || trial.stale || !trial.changes.length" @click="testTrial">检查这一版</button><button class="btn" type="button" :disabled="busy || dirty || trial.stale" @click="forkTrial">另试一种改法</button><button v-if="trial.can_seal && trial.status !== 'merged'" class="btn btn-primary" type="button" :disabled="busy || dirty" @click="prepareMerge">采用这一版…</button></div><section v-if="mergePending && mergePending.workspaceId === trial.id" class="creative-confirm"><p>将把上方 {{ trial.changes.length }} 项修改一起保存到对应工作稿。请核对差异与保留项。</p><button class="btn btn-primary" type="button" :disabled="busy || dirty" @click="confirmMerge">确认保存这些修改</button><button class="btn" type="button" :disabled="busy" @click="discardMerge">暂不采用</button></section><p v-if="mergeReceipt" role="status">所选修改已保存，历史版本与采用记录已保留。</p></section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { getApi, getForecastEditorState, notifyCreativeMerged, registerAuxiliaryLeaveGuard, useStateKey } from "../bridge/index.js"
import { createWorkflowManager } from "../shared/workflowManager.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"
import AssistantValue from "./AssistantValue.vue"
import CreativeTrialEditor from "./CreativeTrialEditor.vue"

const props = defineProps({ projectId: { type: String, default: null }, context: { type: Object, default: () => ({}) }, active: { type: Boolean, default: true } })
const capabilities = reactive({ enabled: false, recipes: [] })
const cases = ref([]), runs = ref([]), workspaces = ref([]), run = ref(null), currentCase = ref(null), trial = ref(null)
const goal = ref(""), constraints = ref(""), recipeId = ref("revision"), selectedResources = ref([])
const followChanges = ref(false)
const readScope = ref("selected"), allowWeb = ref(false), modelConnections = ref({}), customQuestions = ref(""), extraChecks = ref("")
const importCandidates = ref([]), importKeys = ref([]), chapterFrom = ref(1), chapterTo = ref(1)
const busy = ref(false), loading = ref(false), error = ref(""), backupError = ref(false), pending = ref(null), mergePending = ref(null), mergeReceipt = ref(null)
let generation = 0, disposed = false
const api = () => getApi()?.collaboration
const current = token => token === generation && !disposed
const writingState = useStateKey("_writingForecastState")
const dirty = computed(() => { const state = writingState.value; return state?.projectId === props.projectId && Boolean(state?.dirty || state?.saving) })
const hasUnsavedInput = () => { const state = getForecastEditorState(props.projectId); return Boolean(state?.dirty || state?.saving) }
const running = computed(() => ["pending", "running"].includes(run.value?.status) || runs.value.some(item => ["pending", "running"].includes(item.status)))
const visibleReports = computed(() => (run.value?.artifacts || []).filter(item => item.result?.summary))
const extraResources = ref([]), resourceKind = ref("writing_draft"), nextResourceOffset = ref(null)
const readingStops = ref({}), readingCutoff = ref(props.context.chapter_index || 1)
const resources = computed(() => {
  const values = [...extraResources.value]
  if (props.context.draft_id) values.push({ kind: "writing_draft", id: props.context.draft_id, label: "当前正文工作稿" })
  if (props.context.scene_id) values.push({ kind: "scene", id: props.context.scene_id, label: "当前场景安排" })
  if (props.context.target?.target_type === "world_bible_page_draft") values.push({ kind: "world_bible_draft", id: props.context.target.target_id, label: "当前世界书工作稿" })
  return [...new Map(values.map(item => [item.kind + ":" + item.id, item])).values()].filter(item => recipeId.value !== "blind_reader" || item.kind === "writing_draft")
})
function storageKey() { return `novel_creative_v2:${localStorage.getItem(ACCOUNT_MARKER_KEY) || 'local'}:${props.projectId}` }
function saveDraft() { try { localStorage.setItem(storageKey(), JSON.stringify({ extraResources: extraResources.value, selectedResources: selectedResources.value, readingStops: readingStops.value, readingCutoff: readingCutoff.value, goal: goal.value, constraints: constraints.value, recipeId: recipeId.value, followChanges: followChanges.value, readScope: readScope.value, allowWeb: allowWeb.value, modelConnections: modelConnections.value, customQuestions: customQuestions.value, extraChecks: extraChecks.value, importKeys: importKeys.value, chapterFrom: chapterFrom.value, chapterTo: chapterTo.value, caseId: currentCase.value?.id, pending: pending.value, mergePending: mergePending.value })); backupError.value = false } catch { backupError.value = true } }
const statusLabel = status => ({ pending: "已提交，等待处理", running: "正在查证与试改，可以离开后回来", completed: "本轮处理完成", partial: "部分完成，仍有未定项", failed: "本轮未完成，已有成果仍保留", cancelled: "已停止后续工作", budget_exceeded: "本次额度已用尽" })[status] || "尚未开始"
const claimLabel = kind => ({ source_statement: "来源所述", interpretation: "解释", hypothesis: "假设", proposal: "提案" })[kind] || "判断"
function publicUrl(value) { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null } catch { return null } }
const dateLabel = value => new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
function readable(value) { if (!value) return "此试验中不保留"; return value.content ?? value.free_text ?? Object.fromEntries(Object.entries(value).filter(([, value]) => value !== null && value !== "" && (!Array.isArray(value) || value.length))) }
const workflow = createWorkflowManager({ workflowType: "collaboration_run", label: "创作试验", view: "writing", pollNovelId: (_state, id) => id, matchRecovered: items => items.find(item => item.workflowType === "collaboration_run" && item.meta?.caseId === currentCase.value?.id), onTerminal: async (_progress, value, _task, projectId) => { if (projectId === props.projectId) { await openRun(value.meta.runId); await refreshCase() } } })
let runRequest = 0, trialRequest = 0
async function openRun(id) { const token = generation, request = ++runRequest; try { const value = await api().run(props.projectId, id); if (current(token) && request === runRequest) run.value = value } catch (err) { if (current(token)) error.value = err.message } }
async function refreshCase() {
  if (!currentCase.value || !api()) return
  const token = generation, id = currentCase.value.id
  try { const [history, trials] = await Promise.all([api().runs(props.projectId, id), api().workspaces(props.projectId, id)]); if (!current(token) || currentCase.value?.id !== id) return; runs.value = history.items; workspaces.value = trials.items; if (trial.value) await openTrial(trial.value.id); if (!run.value && history.items.length) await openRun(history.items[0].id) }
  catch (err) { if (current(token)) error.value = err.message }
}
async function selectCase(id, { restoring = false } = {}) {
  if (!restoring && !canLeave()) return
  if (!restoring && pending.value) { error.value = "上次提交结果尚未确认，请先恢复原请求再切换目标。"; return }
  if (mergePending.value?.attempted && currentCase.value?.id !== id) { error.value = "上次采用结果未确认，请先恢复原确认。"; return }
  const token = ++generation
  busy.value = false
  workflow.resetMemoryScope(); run.value = trial.value = mergeReceipt.value = mergePending.value = null
  if (!id) { currentCase.value = null; goal.value = constraints.value = ""; workspaces.value = runs.value = []; saveDraft(); return }
  loading.value = true
  try { const value = await api().getCase(props.projectId, id); if (!current(token)) return; currentCase.value = value; goal.value = value.goal; constraints.value = value.constraints.join("\n"); recipeId.value = value.recipe.id; await refreshCase(); workflow.recover(props.projectId); saveDraft() }
  catch (err) { if (current(token)) error.value = err.message }
  finally { if (current(token)) loading.value = false }
}
async function load() {
  const token = ++generation
  const projectId = props.projectId
  busy.value = false
  workflow.resetMemoryScope(); cases.value = []; currentCase.value = run.value = trial.value = null
  if (!props.projectId || !api()) return
  loading.value = true; error.value = ""
  try {
    const [available, history] = await Promise.all([api().capabilities(props.projectId), api().cases(props.projectId)])
    if (!current(token)) return
    Object.assign(capabilities, available); cases.value = history.items
    selectedResources.value = resources.value.map(value => value.kind + ':' + value.id)
    let saved = {}
    try { saved = JSON.parse(localStorage.getItem(storageKey()) || "{}"); extraResources.value = saved.extraResources || []; selectedResources.value = saved.selectedResources || selectedResources.value; readingStops.value = saved.readingStops || {}; readingCutoff.value = saved.readingCutoff || props.context.chapter_index || 1; goal.value = saved.goal || ""; constraints.value = saved.constraints || ""; recipeId.value = saved.recipeId || "revision"; followChanges.value = saved.followChanges === true; readScope.value = saved.readScope || "selected"; allowWeb.value = saved.allowWeb === true; modelConnections.value = saved.modelConnections || {}; customQuestions.value = saved.customQuestions || ""; extraChecks.value = saved.extraChecks || ""; importKeys.value = saved.importKeys || []; chapterFrom.value = saved.chapterFrom || 1; chapterTo.value = saved.chapterTo || 1; pending.value = saved.pending || null; mergePending.value = saved.mergePending || null } catch { backupError.value = true }
    if (saved.caseId) { await selectCase(saved.caseId, { restoring: true }); if (props.projectId === projectId && currentCase.value?.id === saved.caseId && !disposed) { goal.value = saved.goal || currentCase.value.goal; constraints.value = saved.constraints ?? currentCase.value.constraints.join("\n"); pending.value = saved.pending || null; mergePending.value = saved.mergePending || null; if (mergePending.value) await openTrial(mergePending.value.workspaceId); saveDraft() } }
  } catch (err) { if (current(token)) error.value = err.message || "暂时无法读取创作记录。" }
  finally { if (props.projectId === projectId && !disposed) loading.value = false }
}
async function recover() { if (!pending.value || busy.value || dirty.value) return; await start(true) }
async function start(replay = false) {
  if (busy.value || (!replay && running.value) || hasUnsavedInput() || !goal.value.trim()) return
  const token = generation, projectId = props.projectId
  busy.value = true; error.value = ""; mergeReceipt.value = null
  try {
    if (!replay || !pending.value) {
      const constraintsList = constraints.value.split("\n").map(value => value.trim()).filter(Boolean)
      if (currentCase.value) {
        if (currentCase.value.goal !== goal.value || JSON.stringify(currentCase.value.constraints) !== JSON.stringify(constraintsList)) { const value = await api().updateGoal(projectId, currentCase.value.id, { expected_version: currentCase.value.goal_version, goal: goal.value, constraints: constraintsList }); if (!current(token)) return; currentCase.value = value }
        pending.value = { caseId: currentCase.value.id, run: { operation_id: crypto.randomUUID(), expected_goal_version: currentCase.value.goal_version } }
      } else {
        const selected = recipeId.value === "import_consult" ? [] : resources.value.filter(value => selectedResources.value.includes(value.kind + ':' + value.id)).map(({ kind, id }) => ({ kind, id }))
        let importScope = null
        if (recipeId.value === "import_consult") {
          const selection = { chapter_from: chapterFrom.value, chapter_to: chapterTo.value, asset_keys: [...importKeys.value] }
          const dossier = await api().importScope(projectId, selection)
          if (!current(token)) return
          importScope = { ...selection, expected_hash: dossier.fingerprint }
        }
        const baseRecipe = capabilities.recipes.find(value => value.id === recipeId.value)
        const questions = customQuestions.value.split("\n").map(value => value.trim()).filter(Boolean)
        const checks = extraChecks.value.split("\n").map(value => value.trim()).filter(Boolean)
        const customRecipe = questions.length || checks.length ? { ...baseRecipe, questions: questions.length ? questions : baseRecipe.questions, required_checks: [...new Set([...baseRecipe.required_checks, ...checks])] } : null
        pending.value = { create: { operation_id: crypto.randomUUID(), goal: goal.value, constraints: constraintsList, recipe_id: recipeId.value, custom_recipe: customRecipe, grant: { reading_stops: recipeId.value === "blind_reader" ? Object.fromEntries(selected.map(ref => [ref.kind + ":" + ref.id, (readingStops.value[ref.kind + ":" + ref.id] || "").split(/[,，\s]+/).filter(Boolean).map(Number)])) : {}, follow_changes: recipeId.value !== "import_consult" && followChanges.value, import_scope: importScope, model_connections: modelConnections.value, read_scope: readScope.value, resources: selected, read_kinds: [...new Set(selected.map(value => value.kind))], request_limit: 60, run_request_limit: 30, expires_at: new Date(Date.now() + 86400000).toISOString(), allow_web: recipeId.value !== "blind_reader" && allowWeb.value, cutoff_chapter: recipeId.value === "blind_reader" ? readingCutoff.value : null } }, run: { operation_id: crypto.randomUUID(), expected_goal_version: 1 } }
      }
      saveDraft()
    }
    if (pending.value.create && !pending.value.caseId) { const value = await api().createCase(projectId, pending.value.create); if (!current(token)) return; currentCase.value = value; pending.value = { ...pending.value, caseId: value.id }; saveDraft() }
    const result = await api().submit(projectId, pending.value.caseId, pending.value.run)
    if (!current(token)) return
    pending.value = null; saveDraft(); const latest = await api().run(projectId, result.run_id); if (!current(token)) return; run.value = latest; if (["pending", "running"].includes(latest.status)) workflow.adopt({ task_id: result.task_id }, { runId: result.run_id, caseId: currentCase.value.id }, projectId); await refreshCase()
  } catch (err) { if (current(token)) { error.value = err.message || "提交结果未确认，可以恢复原请求。"; if ([400, 403, 404, 409, 422].includes(err.status)) { pending.value = null; saveDraft() } } }
  finally { if (current(token)) busy.value = false }
}
async function stop() { const token = generation, id = ["pending", "running"].includes(run.value?.status) ? run.value.id : runs.value.find(item => ["pending", "running"].includes(item.status))?.id; if (!id) return; try { await api().stop(props.projectId, id); if (current(token)) { await openRun(id); await refreshCase() } } catch (err) { if (current(token)) error.value = err.message } }
async function openTrial(id) { if (trial.value?.id !== id && !canLeave()) return; const token = generation, request = ++trialRequest; if (trial.value?.id !== id) trial.value = null; try { const value = await api().diff(props.projectId, id); if (current(token) && request === trialRequest) { trial.value = value;  } } catch (err) { if (current(token)) error.value = err.message } }
async function testTrial() { if (busy.value || hasUnsavedInput()) return; pending.value = { caseId: currentCase.value.id, run: { operation_id: crypto.randomUUID(), expected_goal_version: currentCase.value.goal_version, workspace_revision_id: trial.value.revision_id } }; saveDraft(); await start(true) }
async function forkTrial() { if (busy.value || hasUnsavedInput()) return; const token = generation; busy.value = true; try { const value = await api().fork(props.projectId, trial.value.id, { operation_id: crypto.randomUUID(), parent_revision_id: trial.value.revision_id, label: "另一种改法" }); if (!current(token)) return; trial.value = value; await refreshCase() } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function prepareMerge() { if (hasUnsavedInput() || busy.value || mergePending.value) return; const token = generation; busy.value = true; try { const value = await api().seal(props.projectId, trial.value.id, { revision_id: trial.value.revision_id, expected_digest: trial.value.digest }); if (!current(token)) return; trial.value = value; mergePending.value = { workspaceId: value.id, body: { operation_id: crypto.randomUUID(), revision_id: value.revision_id, expected_digest: value.digest, editor_state: "saved", confirmed: true } }; saveDraft() } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function confirmMerge() { if (hasUnsavedInput() || busy.value || !mergePending.value) return; const token = generation, value = mergePending.value; busy.value = true; value.attempted = true; saveDraft(); try { const receipt = await api().merge(props.projectId, value.workspaceId, value.body); if (!current(token)) return; mergeReceipt.value = receipt; notifyCreativeMerged(props.projectId, receipt); mergePending.value = null; saveDraft(); await refreshCase(); if (current(token)) mergeReceipt.value = receipt } catch (err) { if (current(token)) error.value = err.message || "采用结果未确认，可重试原确认。" } finally { if (current(token)) busy.value = false } }
async function trialUpdated(value) { const token = generation, projectId = props.projectId, caseId = currentCase.value?.id; if (!caseId) return; trial.value = value; const next = await api().getCase(projectId, caseId); if (!current(token) || currentCase.value?.id !== caseId) return; currentCase.value = next; await refreshCase() }
function discardMerge() { if (mergePending.value?.attempted) { error.value = "采用请求已发出，请先恢复原确认以核对结果。"; return } mergePending.value = null; saveDraft() }
async function resume() { if (busy.value || !run.value) return; busy.value = true; const token = generation; try { const value = await api().resume(props.projectId, run.value.id); if (current(token)) { workflow.adopt({ task_id: value.task_id }, { runId: value.run_id, caseId: currentCase.value.id }, props.projectId); await openRun(value.run_id) } } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function renewGrant() { if (busy.value || !currentCase.value) return; busy.value = true; const token = generation; try { const value = await api().updateGrant(props.projectId, currentCase.value.id, { expected_grant_hash: currentCase.value.grant_hash, grant: { ...currentCase.value.grant, expires_at: new Date(Date.now() + 86400000).toISOString() } }); if (current(token)) currentCase.value = value } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function pauseFollow() { const token = generation; busy.value = true; try { const latest = await api().getCase(props.projectId, currentCase.value.id); if (!current(token)) return; const value = await api().updateGrant(props.projectId, latest.id, { expected_grant_hash: latest.grant_hash, grant: { ...latest.grant, follow_changes: false, allow_background_web: false } }); if (current(token)) { currentCase.value = value; await refreshCase() } } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
function importLabel(item, index) { const label = item.fields?.name || item.fields?.alias || item.fields?.title || item.fields?.summary; return label ? `待核对：${String(label).slice(0, 160)}` : `待决资料 ${index + 1}` }
async function loadImportGroups() { const token = generation; try { const value = await getApi().imports.reviewSummary(props.projectId); if (current(token)) { importCandidates.value = value.candidates || []; importKeys.value = importKeys.value.filter(key => importCandidates.value.some(item => item.key === key)) } } catch (err) { if (current(token)) error.value = err.message } }
async function loadResources(offset = 0) { const token = generation, kind = recipeId.value === "blind_reader" ? "writing_draft" : resourceKind.value; try { const value = await api().resources(props.projectId, { kind, offset }); if (!current(token)) return; extraResources.value = [...new Map([...extraResources.value, ...value.items].map(item => [item.kind + ":" + item.id, item])).values()]; nextResourceOffset.value = value.next_offset; saveDraft() } catch (err) { if (current(token)) error.value = err.message } }
function chooseConnection(role, value) { const choices = { ...modelConnections.value }; if (value) choices[role] = value; else delete choices[role]; modelConnections.value = choices; saveDraft() }
function invalidated() { generation++; workflow.resetMemoryScope(); cases.value = runs.value = workspaces.value = []; currentCase.value = run.value = trial.value = pending.value = mergePending.value = mergeReceipt.value = null; goal.value = constraints.value = ""; capabilities.enabled = false; importCandidates.value = importKeys.value = []; modelConnections.value = {}; allowWeb.value = false; customQuestions.value = extraChecks.value = "" }
const grantEditing = ref(false)
async function saveGrantSelection() {
  if (busy.value || running.value || !currentCase.value) return
  const token = generation; busy.value = true; error.value = ""
  try {
    const chosen = resources.value.filter(item => selectedResources.value.includes(item.kind + ':' + item.id)).map(({ kind, id }) => ({ kind, id }))
    if (!chosen.length) return
    const grant = { ...currentCase.value.grant, resources: chosen, read_kinds: [...new Set(chosen.map(item => item.kind))], context_confirmation_id: null, context_confirmation_action: null, reading_stops: {}, expires_at: new Date(Date.now() + 86400000).toISOString() }
    const value = await api().updateGrant(props.projectId, currentCase.value.id, { expected_grant_hash: currentCase.value.grant_hash, grant })
    if (current(token)) { currentCase.value = value; grantEditing.value = false; await refreshCase() }
  } catch (err) { if (current(token)) error.value = err.message }
  finally { if (current(token)) busy.value = false }
}
async function refreshImportGrant() {
  const token = generation; busy.value = true; error.value = ""
  try {
    const original = currentCase.value.grant.import_scope
    const dossier = await api().importScope(props.projectId, { ...original, expected_hash: null })
    if (!current(token)) return
    const grant = { ...currentCase.value.grant, import_scope: { ...original, expected_hash: dossier.fingerprint }, expires_at: new Date(Date.now() + 86400000).toISOString() }
    const value = await api().updateGrant(props.projectId, currentCase.value.id, { expected_grant_hash: currentCase.value.grant_hash, grant })
    if (current(token)) { currentCase.value = value; await refreshCase() }
  } catch (err) { if (current(token)) error.value = err.message }
  finally { if (current(token)) busy.value = false }
}
watch(() => [props.projectId, currentCase.value?.id], () => { grantEditing.value = false })
const trialEditor = ref(null)
function canLeave() { return trialEditor.value?.canLeave?.() !== false && (!backupError.value || !(goal.value || constraints.value || pending.value) || globalThis.confirm("创作目标暂未备份，离开可能丢失输入。仍要离开吗？")) }
const unregisterGuard = registerAuxiliaryLeaveGuard(() => !backupError.value || !(goal.value || constraints.value || pending.value) || globalThis.confirm("创作目标暂未备份，离开可能丢失输入。仍要离开吗？"))
function beforeUnload(event) { if (props.active && backupError.value && (goal.value || constraints.value || pending.value)) { event.preventDefault(); event.returnValue = "" } }
defineExpose({ canLeave })
watch(selectedResources, saveDraft)
globalThis.addEventListener?.("beforeunload", beforeUnload)
globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated)
watch(() => [props.projectId, props.active], () => { if (props.active) void load() }, { immediate: true })
onBeforeUnmount(() => { disposed = true; generation++; unregisterGuard(); globalThis.removeEventListener?.("beforeunload", beforeUnload); workflow.resetMemoryScope(); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated) })
</script>

<style scoped>
.creative-experiments{font-size:13px;line-height:1.7;color:var(--text-primary)}.creative-kicker{font-size:11px;letter-spacing:.09em;color:var(--text-secondary)}.creative-experiments h3{margin:3px 0;font-size:20px}.creative-experiments header p,.creative-note{color:var(--text-secondary)}.creative-label{display:block;margin:14px 0}.creative-label textarea,.creative-label select,.creative-history select{display:block;width:100%;box-sizing:border-box;margin:6px 0;padding:9px;background:var(--bg-primary,var(--bg-base));color:inherit;border:1px solid var(--border-color,var(--border));border-radius:6px;font:inherit;resize:vertical}.creative-experiments .creative-form-fields{border:0;padding:0}.creative-experiments fieldset{border:1px solid var(--border-color,var(--border));border-radius:6px;padding:10px}.creative-experiments fieldset label{display:block;padding:5px 0}.creative-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:14px 0}.creative-error{color:var(--danger);overflow-wrap:anywhere}.creative-history,.creative-trials,.creative-diff{margin-top:24px;border-top:1px solid var(--border-color,var(--border));padding-top:14px}.creative-report{padding:10px 0;border-bottom:1px solid var(--border-color,var(--border));white-space:pre-wrap}.creative-trial-button{display:flex;flex-direction:column;gap:4px;width:100%;text-align:left;padding:12px;margin:8px 0;background:var(--bg-muted);border:1px solid var(--border-color,var(--border));border-radius:7px;color:inherit;font:inherit;cursor:pointer}.creative-trial-button[aria-pressed=true]{border-color:var(--accent,var(--primary))}.creative-trial-button span{color:var(--text-secondary);font-size:12px}.creative-comparison{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr));margin:10px 0 18px}.creative-comparison>div{padding:10px;background:var(--bg-muted);overflow-wrap:anywhere;min-width:0}.creative-comparison small{display:block;color:var(--text-secondary);margin-bottom:8px}.creative-confirm{border-left:3px solid var(--accent,var(--primary));padding:12px;background:var(--bg-muted)}.creative-experiments :is(button,textarea,select):focus-visible{outline:2px solid var(--accent,var(--primary));outline-offset:3px}@media(max-width:700px){.creative-comparison{grid-template-columns:1fr}.creative-label textarea{font-size:16px}.creative-experiments button{min-height:42px}}
</style>
