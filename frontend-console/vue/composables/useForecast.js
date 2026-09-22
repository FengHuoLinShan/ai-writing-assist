import { reactive } from "vue"
import { locateAssistantSource, openAssistantDestination } from "../shared/assistantNavigation.js"
import { getApi, getRouter, getForecastEditorState, getCurrentWritingFingerprint } from "../bridge/index.js"
import { createWorkflowManager } from "../shared/workflowManager.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"

const active = run => ["pending", "running"].includes(run?.status)
const targetKinds = { world_entity: "core_entity", outline_scene: "scene", world_bible_page_draft: "world_bible_draft" }

export function createForecast({ editor = () => null, composing = () => false } = {}) {
  const state = reactive({ projectId: null, focus: null, available: false, capabilities: [], feed: null, pendingFeed: null, policy: null, run: null, error: "", loading: false, busy: false, hold: false, stale: false, instruction: "", prepared: null, preparationRun: null, pending: null, pendingPrepare: null, includeDeferred: false, backupError: false })
  let generation = 0, focusSeq = 0, disposed = false
  const clientContextId = crypto.randomUUID()
  const api = () => getApi()?.forecasts
  const owned = token => !disposed && token === generation
  const storageKey = () => `novel_forecast_v1:${localStorage.getItem(ACCOUNT_MARKER_KEY) || "local"}:${state.projectId}`
  const dirty = () => Boolean((editor() || getForecastEditorState(state.projectId))?.dirty || (editor() || getForecastEditorState(state.projectId))?.saving)
  function save() {
    try { localStorage.setItem(storageKey(), JSON.stringify({ instruction: state.instruction, pending: state.pending, prepared: state.prepared, pendingPrepare: state.pendingPrepare })); state.backupError = false }
    catch { state.backupError = true }
  }
  function setInstruction(value) { state.instruction = value; save() }
  async function focusFrom(context) {
    // A05（2026-09-22 审查）：选区快照不可拆分——origin draft_id、指纹、
    // 偏移与选中文本须同源。先记下选区捕获时的原稿，跨稿一律失效。
    const selectionOriginDraftId = context.draft_id || null
    const result = { client_context_id: clientContextId, focus_seq: ++focusSeq, page: context.page || "today", task_hint: context.task_hint || "unknown", draft_id: context.draft_id || null, scene_id: context.scene_id || null, context_confirmation_id: context.context_confirmation_id || null, context_confirmation_action: context.context_confirmation_action || null, editor_state: dirty() ? "dirty" : context.draft_id ? "saved" : "not_applicable", explicit_instruction: state.instruction }
    if (context.target?.target_id) result.target = { resource_kind: targetKinds[context.target.target_type] || context.target.target_type, resource_id: context.target.target_id }
    const writing = editor() || getForecastEditorState(state.projectId)
    if (context.page === "writing" && writing && !context.context_confirmation_id) {
      result.draft_id = writing.draftId || context.draft_id || null
      result.scene_id = writing.sceneId ?? context.scene_id ?? null
      result.editor_state = dirty() ? "dirty" : result.draft_id ? "saved" : "not_applicable"
    }
    const saved = writing?.lastSavedContent ?? writing?.savedContent
    if (result.draft_id && typeof saved === "string") result.expected_source_hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(saved))), value => value.toString(16).padStart(2, "0")).join("")
    // R00：写作页干净状态下带选区范围（码点偏移 + 已存内容指纹），让
    // 前瞻实际分析选中段落；契约要求 selected_range 必须伴随 draft+hash。
    // F2（PR160-162 审查）：草稿/内容变化后旧偏移不得重绑到新指纹。携带前
    // 先在当前已存正文的原偏移处重验选区文本，验不上即令选区失效（不带
    // 范围）。A05：仅文本相等不够——选区只对捕获它的原稿有效，跨稿
    // （即使新稿同位置同文字）直接失效，不带范围。
    if (
      selectionOriginDraftId
      && result.draft_id === selectionOriginDraftId
      && result.draft_id
      && result.expected_source_hash
      && result.editor_state === "saved"
      && Number.isInteger(context.selection_start)
      && Number.isInteger(context.selection_end)
      && context.selection_end > context.selection_start
      && typeof context.selection === "string"
      && context.selection
      && context.selection_end <= Array.from(saved).length
      && Array.from(saved).slice(context.selection_start, context.selection_end).join("") === context.selection
    ) {
      result.selected_range = { start_offset: context.selection_start, end_offset: context.selection_end }
    }
    return result
  }
  function acceptFeed() { if (!composing() && state.pendingFeed) { state.feed = state.pendingFeed; state.pendingFeed = null; state.stale = false } }
  async function refresh(token = generation) {
    // 未保存/保存中不拉 feed：保存落库会让在途焦点的 draft 校验失效（SOURCE_STALE），
    // 且此期间建议入口本就禁用；保存完成后的焦点重建会带来干净刷新。
    if (!state.projectId || !state.focus || !api() || composing() || dirty()) return
    const focus = { ...state.focus, editor_state: dirty() ? "dirty" : state.focus.draft_id ? "saved" : "not_applicable" }
    const feed = await api().feed(state.projectId, { context: focus, include_deferred: state.includeDeferred })
    if (!owned(token) || feed.client_context_id !== state.focus.client_context_id || feed.focus_seq !== state.focus.focus_seq) return
    if ((state.hold || composing()) && state.feed) { state.pendingFeed = feed; state.stale = state.feed.context_hash !== feed.context_hash }
    else { state.feed = feed; state.pendingFeed = null; state.stale = false }
  }
  const workflow = createWorkflowManager({
    workflowType: "assistant_forecast", label: "下一步建议", view: "writing", pollNovelId: (_state, projectId) => projectId,
    matchRecovered: values => values.find(value => value.workflowType === "assistant_forecast"),
    onTerminal: async (_progress, value, _task, projectId) => {
      const token = generation
      try {
        const run = await api().run(projectId, value.meta.runId)
        if (owned(token) && projectId === state.projectId) { state.run = run; await refresh(token) }
      } catch (error) { if (owned(token)) state.error = error.message || "结果暂时无法读取。" }
    },
  })
  async function configure(projectId, context) {
    const token = ++generation
    const switched = projectId !== state.projectId
    workflow.resetMemoryScope()
    state.projectId = projectId
    state.error = ""
    state.busy = false
    state.loading = true
    if (switched) {
      state.feed = state.pendingFeed = state.run = state.prepared = state.preparationRun = null
      state.instruction = ""
      state.pending = null
      try { const saved = JSON.parse(localStorage.getItem(storageKey()) || "{}"); state.instruction = saved.instruction || ""; state.pending = saved.pending || null; state.prepared = saved.prepared || null; state.pendingPrepare = saved.pendingPrepare || null } catch { state.backupError = true }
    }
    if (!projectId || !api()) { state.available = false; state.loading = false; return }
    try {
      const focus = await focusFrom(context)
      if (!owned(token)) return
      state.focus = focus
      const [capabilities, policy] = await Promise.all([api().capabilities(projectId), api().policy(projectId)])
      if (!owned(token)) return
      state.capabilities = capabilities.items
      state.available = capabilities.items.some(item => item.available)
      state.policy = policy
      if (!dirty() && api().activity) await api().activity(projectId, focus)
      if (!owned(token)) return
      await refresh(token)
      if (state.prepared) { const run = await getApi().assistant.run(projectId, state.prepared.run_id); if (owned(token)) state.preparationRun = run }
      workflow.recover(projectId)
    } catch (error) { if (owned(token)) state.error = error.message || "前瞻暂时不可用，仍可继续写作。" }
    finally { if (owned(token)) state.loading = false }
  }
  async function completeSubmission(submission, projectId, token) {
    const run = submission.run || await api().run(projectId, submission.run_id)
    if (!owned(token)) return
    state.run = run; state.pending = null; save()
    if (active(run)) workflow.adopt(run, { runId: run.run_id }, projectId)
    else await refresh(token)
  }
  async function evaluate({ priorRunId = null } = {}) {
    if (state.busy || active(state.run) || dirty() || composing() || !state.focus) return
    const token = generation, projectId = state.projectId
    state.busy = true; state.error = ""
    try {
      if (!state.pending) {
        state.focus = { ...state.focus, focus_seq: ++focusSeq, explicit_instruction: state.instruction, editor_state: state.focus.draft_id ? "saved" : "not_applicable" }
        state.pending = { operation_id: crypto.randomUUID(), context: { ...state.focus, prior_forecast_run_id: priorRunId }, horizon: { unit: ["writing", "scene"].includes(state.focus.page) ? "scene" : "decision" } }
        save()
      }
      const submission = await api().evaluate(projectId, state.pending)
      await completeSubmission(submission, projectId, token)
    } catch (error) { if (owned(token)) state.error = error.message || "提交结果尚未确认，可恢复原请求。" }
    finally { if (owned(token)) state.busy = false }
  }
  async function revisit() { if (state.run?.run_id) await evaluate({ priorRunId: state.run.run_id }) }
  async function recover() {
    if (!state.pending || state.busy) return
    const token = generation, projectId = state.projectId
    state.busy = true
    try { await completeSubmission(await api().operation(projectId, state.pending.operation_id), projectId, token) }
    catch (error) { if (owned(token)) state.error = error.message || "尚未查到记录，可重试同一请求。" }
    finally { if (owned(token)) state.busy = false }
  }
  async function decide(item, action, extra = {}) {
    if (state.busy) return
    const token = generation
    state.busy = true; state.error = ""
    try {
      await api().decide(state.projectId, item.candidate_id, { expected_notice_version: item.notice_version, expected_assessment_hash: item.assessment_hash, action, ...extra })
      if (owned(token)) { state.hold = false; await refresh(token) }
    } catch (error) { if (owned(token)) { state.error = error.message || "处置未保存，请重试。"; await refresh(token).catch(() => {}) } }
    finally { if (owned(token)) state.busy = false }
  }
  async function prepare(item, action) {
    if (state.busy || dirty() || state.stale) return
    const token = generation, projectId = state.projectId
    state.busy = true; state.error = ""
    try {
      if (!state.pendingPrepare || state.pendingPrepare.candidateId !== item.candidate_id || state.pendingPrepare.body.action_id !== action.action_id) {
        state.pendingPrepare = { candidateId: item.candidate_id, body: { operation_id: crypto.randomUUID(), expected_assessment_hash: item.assessment_hash, action_id: action.action_id, context: { ...state.focus, editor_state: state.focus.draft_id ? "saved" : "not_applicable" } } }
        save()
      }
      const receipt = await api().prepare(projectId, item.candidate_id, state.pendingPrepare.body)
      if (!owned(token)) return
      state.prepared = { ...receipt, sourceHash: receipt.source_hash || item.evidence.find(value => value.resource_kind === "writing_draft")?.source_hash || state.focus.expected_source_hash, draftId: receipt.draft_id || state.focus.draft_id }
      state.pendingPrepare = null
      save()
      const preparedRun = await getApi().assistant.run(projectId, receipt.run_id)
      if (owned(token)) state.preparationRun = preparedRun
    } catch (error) { if (owned(token)) state.error = error.message || "预览未准备好，原稿保持不变。" }
    finally { if (owned(token)) state.busy = false }
  }
  async function confirm() {
    if (state.busy || dirty() || !state.prepared || !state.preparationRun?.result?.actions?.length) return
    const token = generation, projectId = state.projectId, prepared = state.prepared
    state.busy = true; state.error = ""
    try {
      if (prepared.draftId) {
        const hash = await getCurrentWritingFingerprint(projectId, prepared.draftId)
        if (hash && hash !== prepared.sourceHash) throw new Error("编辑器已有新的输入，请先保存后重新准备。")
      }
      const result = await getApi().assistant.decide(prepared.batch_id, { novel_id: projectId, fingerprint: prepared.batch_fingerprint, selected: ["selected"], confirmed: true })
      if (owned(token)) { state.prepared = { ...prepared, outcome: result }; save() }
    } catch (error) { if (owned(token)) state.error = error.message || "执行结果尚未确认，可以重试原确认。" }
    finally { if (owned(token)) state.busy = false }
  }
  async function cancel() {
    const token = generation
    try { const run = await api().cancel(state.projectId, state.run.run_id); if (owned(token)) state.run = run }
    catch (error) { if (owned(token)) state.error = error.message }
  }
  async function saveAutomatic(automatic) {
    if (!state.policy || state.busy) return
    const token = generation
    state.busy = true; state.error = ""
    try { const policy = await api().savePolicy(state.projectId, { expected_generation: state.policy.generation, policy: { ...state.policy.policy, enabled: true, automatic } }); if (owned(token)) { state.policy = policy; await refresh(token) } }
    catch (error) { if (owned(token)) state.error = error.message || "设置未保存。" }
    finally { if (owned(token)) state.busy = false }
  }
  async function resume() {
    if (!state.run?.can_resume || state.busy || dirty()) return
    const token = generation
    state.busy = true
    try { const value = await api().resume(state.projectId, state.run.run_id); if (owned(token)) { state.run = value; workflow.adopt(value, { runId: value.run_id }, state.projectId) } }
    catch (error) { if (owned(token)) state.error = error.message }
    finally { if (owned(token)) state.busy = false }
  }
  async function more() {
    if (!state.feed?.next_cursor || state.loading) return
    const token = generation
    state.loading = true
    try {
      const value = await api().feed(state.projectId, { context: state.focus, cursor: state.feed.next_cursor, max_items: 10, include_deferred: state.includeDeferred })
      if (owned(token) && value.focus_seq === state.focus.focus_seq) state.feed = { ...value, items: Array.from(new Map([...state.feed.items, ...value.items].map(item => [item.candidate_id, item])).values()) }
    } catch (error) { if (owned(token)) state.error = error.message }
    finally { if (owned(token)) state.loading = false }
  }
  function openDomain(item) {
    if (state.stale || !item.navigation) return
    const target = item.navigation
    if (target.reference) return locateAssistantSource(target.reference)
    if (target.page === "writing") return openAssistantDestination("writing", target)
    if (target.page === "scene" && target.scene_id) return locateAssistantSource({ type: "scene", id: target.scene_id })
    if (target.page === "imports") return target.task_id ? locateAssistantSource({ type: "import_workflow", task_id: target.task_id }) : openAssistantDestination("world_review")
    if (target.page === "map") return target.node_id ? locateAssistantSource({ type: "map_atlas_node", id: target.node_id }) : openAssistantDestination("map")
    if (target.page === "world") {
      if (target.target_id && state.focus?.target?.resource_id === target.target_id) return locateAssistantSource({ type: state.focus.target.resource_kind, id: target.target_id })
      return openAssistantDestination("world_review")
    }
    if (target.page === "rag") return openAssistantDestination("references")
    if (target.page === "settings" || target.page === "account") return openAssistantDestination("model_settings")
    if (target.page === "today" || target.page === "project") return getRouter().navigate("writing", null, true, new URLSearchParams({ home: "1" }))
    if (target.page === "assistant") return getRouter().navigate("writing", null, true, new URLSearchParams({ panel: "assistant", ...(target.run_id ? { run_id: target.run_id } : {}), ...(target.tab ? { tab: target.tab } : {}) }))
  }
  function invalidated() { generation++; workflow.resetMemoryScope(); state.feed = state.pendingFeed = state.prepared = state.preparationRun = state.run = null; state.instruction = ""; state.pending = state.pendingPrepare = null; state.available = false }
  globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated)
  function dispose() { disposed = true; generation++; workflow.resetMemoryScope(); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated) }
  return { state, configure, refresh, evaluate, recover, decide, prepare, confirm, cancel, saveAutomatic, acceptFeed, setInstruction, more, openDomain, resume, revisit, dispose, dirty }
}
