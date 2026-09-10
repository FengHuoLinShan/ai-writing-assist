import { reactive } from "vue"
import { getApi, getAppState, getCurrentWritingFingerprint, notifyProjectAssistantChanged } from "../bridge/index.js"
import { createWorkflowManager } from "../shared/workflowManager.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"
import { clearActiveWorkflow } from "../../shared/workflowProgress.js"

const active = status => ["pending", "running"].includes(status)

export function createProjectAssistant() {
  const state = reactive({ projectId: null, sessionId: null, sessions: [], total: 0, sessionOffset: 0, messages: [], messageTotal: 0, input: "", run: null, loading: false, busy: false, enabled: false, error: "", backupError: false, pendingSubmission: false, selected: [], context: null, allowWeb: false, destinations: [], webUnavailableReason: "", modelUnavailableReason: "" })
  const drafts = new Map()
  let generation = 0
  let accountGeneration = 0
  const api = () => getApi()?.assistant
  const scope = () => ({ projectId: state.projectId, sessionId: state.sessionId, generation, accountGeneration })
  const current = token => token.generation === generation && token.accountGeneration === accountGeneration && token.projectId === state.projectId && token.sessionId === state.sessionId
  function key(projectId) {
    let account = "local"
    try { account = localStorage.getItem(ACCOUNT_MARKER_KEY) || account } catch { /* in-memory fallback */ }
    return `novel_assistant_v1:${account}:${projectId}`
  }
  function record(projectId) {
    if (!drafts.has(projectId)) {
      let saved = {}
      try { saved = JSON.parse(localStorage.getItem(key(projectId)) || "{}") } catch { /* corrupt or unavailable backup */ }
      drafts.set(projectId, { sessionId: typeof saved.sessionId === "string" ? saved.sessionId : null, drafts: saved.drafts && typeof saved.drafts === "object" ? saved.drafts : {}, pending: saved.pending && typeof saved.pending === "object" ? saved.pending : {}, decisions: saved.decisions && typeof saved.decisions === "object" ? saved.decisions : {}, viewedRuns: saved.viewedRuns && typeof saved.viewedRuns === "object" ? saved.viewedRuns : {} })
    }
    return drafts.get(projectId)
  }
  function save(projectId = state.projectId, expectedAccount = accountGeneration) {
    if (!projectId || expectedAccount !== accountGeneration) return false
    try { localStorage.setItem(key(projectId), JSON.stringify(record(projectId))); state.backupError = false; return true }
    catch { state.backupError = true; return false }
  }
  function setInput(value) {
    state.input = value
    if (!state.projectId) return
    record(state.projectId).drafts[state.sessionId || "new"] = { text: value, context: state.context, allowWeb: state.allowWeb, webBackend: "searxng-v1" }
    save()
  }
  function setAllowWeb(value) { state.allowWeb = Boolean(value); setInput(state.input) }
  function setRun(run) {
    state.run = run
    state.selected = run?.result?.batch?.selected ?? run?.result?.actions?.map(item => item.key) ?? []
  }
  function mergeMessages(items) {
    const confirmed = new Set(items.filter(item => item.role === "author").map(item => item.task_id))
    const previous = state.messages.filter(item => !item.optimistic || !confirmed.has(item.task_id))
    state.messages = Array.from(new Map([...previous, ...items].map(item => [item.id, item])).values())
      .sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) || String(a.id).localeCompare(String(b.id)))
    notifyProjectAssistantChanged(state.projectId, state.sessionId)
  }
  async function refreshRun(runId, token = scope()) {
    const run = await api().run(token.projectId, runId)
    if (current(token)) { setRun(run); record(token.projectId).viewedRuns[token.sessionId] = run.id; save() }
    return run
  }
  async function openRun(runId) {
    if (state.busy || state.loading || active(state.run?.status)) return
    generation += 1
    workflow.resetMemoryScope()
    const token = scope()
    state.busy = true
    try { await refreshRun(runId, token); if (current(token)) state.error = "" }
    catch (error) { if (current(token)) state.error = error.message || "原处理结果暂时无法读取。" }
    finally { if (current(token)) state.busy = false }
  }
  const workflow = createWorkflowManager({
    workflowType: "assistant_turn", label: "项目助手", view: "today", prepare: true,
    pollNovelId: (_state, projectId) => projectId,
    matchRecovered: items => items.find(item => item.workflowType === "assistant_turn" && item.meta?.sessionId === state.sessionId),
    onTerminal: async (_progress, value, _task, projectId) => {
      if (projectId !== state.projectId || value.meta?.sessionId !== state.sessionId) return
      const token = scope()
      try {
        await refreshRun(value.meta.runId, token)
        const detail = await api().session(projectId, token.sessionId)
        if (current(token)) { mergeMessages(detail.messages); state.messageTotal = detail.message_total }
      } catch (error) { if (current(token)) state.error = error.message || "结果暂时无法读取，请重试。" }
    },
  })
  async function selectSession(sessionId) {
    if (state.projectId) setInput(state.input)
    generation += 1
    workflow.resetMemoryScope()
    state.sessionId = sessionId
    state.run = null
    state.error = ""
    state.messages = []
    state.messageTotal = 0
    const saved = record(state.projectId)
    state.pendingSubmission = Boolean(saved.pending[sessionId])
    saved.sessionId = sessionId
    const draft = saved.drafts[sessionId || "new"] || {}
    state.input = typeof draft.text === "string" ? draft.text : ""
    state.context = draft.context || null
    state.allowWeb = draft.webBackend === "searxng-v1" && draft.allowWeb === true
    save()
    if (!sessionId) return
    state.loading = true
    const token = scope()
    try {
      const detail = await api().session(token.projectId, sessionId)
      if (!current(token)) return
      state.messages = detail.messages
      if (!state.context && detail.last_context) state.context = detail.last_context
      if (draft.webBackend !== "searxng-v1") state.allowWeb = detail.last_web_backend === "searxng-v1" && detail.last_allow_web === true
      state.messageTotal = detail.message_total
      if (!state.sessions.some(item => item.id === sessionId)) state.sessions.unshift(detail.session)
      setRun(detail.latest_run)
      if (active(detail.latest_run?.status)) workflow.adopt(detail.latest_run, { sessionId, runId: detail.latest_run.id }, token.projectId)
      else {
        const receipt = saved.viewedRuns[sessionId]
        if (receipt && receipt !== detail.latest_run?.id) await refreshRun(receipt, token)
        if (current(token)) workflow.recover(token.projectId)
      }
    } catch (error) { if (current(token)) state.error = error.message || "讨论暂时无法读取。" }
    finally { if (current(token)) state.loading = false }
  }
  async function load(projectId) {
    if (state.projectId) setInput(state.input)
    generation += 1
    workflow.resetMemoryScope()
    Object.assign(state, { projectId, sessionId: null, sessions: [], messages: [], input: "", run: null, enabled: false, error: "", loading: false, busy: false, context: null, pendingSubmission: false, selected: [] })
    if (!projectId || !api()) return
    const owner = generation
    try {
      const capabilities = await api().capabilities(projectId)
      if (owner !== generation) return
      state.enabled = capabilities.enabled
      state.modelUnavailableReason = capabilities.model?.available === false ? capabilities.model.reason : ""
      state.destinations = capabilities.destinations || []
      state.webUnavailableReason = capabilities.web_search?.available ? "" : capabilities.web_search?.reason || "公开资料搜索尚未配置"
      if (!state.enabled) return
      const list = await api().sessions(projectId)
      if (owner !== generation) return
      state.sessions = list.items
      state.total = list.total
      state.sessionOffset = list.items.length
      await selectSession(record(projectId).sessionId || list.items[0]?.id || null)
    } catch (error) { if (owner === generation) state.error = error.message || "助手暂时无法连接。" }
  }
  async function newSession() {
    if (state.busy || !state.projectId) return
    const token = scope()
    state.busy = true
    try {
      const session = await api().createSession(token.projectId)
      if (!current(token)) return
      state.sessions.unshift(session)
      state.total += 1
      await selectSession(session.id)
    } catch (error) { if (current(token)) state.error = error.message || "创建讨论失败。" }
    finally { if (token.projectId === state.projectId && token.accountGeneration === accountGeneration) state.busy = false }
  }
  async function send(context) {
    if (!state.input.trim() || state.busy || active(state.run?.status)) return
    const originalInput = state.input
    const originalContext = JSON.parse(JSON.stringify(state.context || context || {}))
    const originalAllowWeb = state.allowWeb
    const creatingSession = !state.sessionId
    const originalProject = state.projectId
    const originalAccount = accountGeneration
    if (!state.sessionId) await newSession()
    if (!state.sessionId || originalProject !== state.projectId || originalAccount !== accountGeneration) return
    if (creatingSession) {
      state.context = originalContext
      state.allowWeb = originalAllowWeb
      setInput(originalInput)
    }
    if (!state.input) setInput(originalInput)
    const token = scope()
    const saved = record(token.projectId)
    const previous = saved.pending[token.sessionId]
    if (previous && previous.message !== state.input) { state.error = "上一条提交尚未确认，请先恢复原请求；当前输入已保留。"; return }
    const payload = previous || { novel_id: token.projectId, operation_id: crypto.randomUUID(), message: state.input, context: state.context || context, allow_web: state.allowWeb, web_backend: state.allowWeb ? "searxng-v1" : null }
    saved.pending[token.sessionId] = payload
    state.pendingSubmission = true
    save(token.projectId)
    workflow.prepare(payload.operation_id, { sessionId: token.sessionId, runId: payload.operation_id }, token.projectId)
    state.busy = true
    state.error = ""
    try {
      const run = await api().submit(token.sessionId, payload)
      if (token.accountGeneration !== accountGeneration) return
      delete saved.pending[token.sessionId]
      if (saved.drafts[token.sessionId]?.text === payload.message) saved.drafts[token.sessionId] = { text: "", context: payload.context, allowWeb: payload.allow_web, webBackend: payload.web_backend }
      save(token.projectId, token.accountGeneration)
      if (current(token)) {
        if (state.input === payload.message) { state.input = ""; state.context = payload.context }
        setRun(run)
        saved.viewedRuns[token.sessionId] = run.id
        save(token.projectId)
        state.pendingSubmission = false
        state.messages.push({ id: `local:${payload.operation_id}`, task_id: payload.operation_id, optimistic: true, created_at: new Date().toISOString(), role: "author", content: payload.message })
      }
      workflow.adopt(run, { sessionId: token.sessionId, runId: run.id }, token.projectId)
    } catch (error) {
      if (token.accountGeneration === accountGeneration && Number(error.status) >= 400 && Number(error.status) < 500) {
        delete saved.pending[token.sessionId]
        clearActiveWorkflow(payload.operation_id)
        save(token.projectId, token.accountGeneration)
        if (current(token)) state.pendingSubmission = false
      }
      if (current(token)) state.error = error.message || "提交结果尚未确认，重试会使用同一请求。"
    }
    finally { if (current(token)) state.busy = false }
  }
  async function recoverSubmission() {
    const token = scope()
    const saved = record(token.projectId)
    const pending = saved.pending[token.sessionId]
    if (!pending || state.busy) return
    state.busy = true
    try {
      let run
      try { run = await api().run(token.projectId, pending.operation_id) }
      catch (error) {
        if (Number(error.status) !== 404 || token.accountGeneration !== accountGeneration) throw error
        run = await api().submit(token.sessionId, pending)
      }
      if (token.accountGeneration !== accountGeneration) return
      delete saved.pending[token.sessionId]
      if (saved.drafts[token.sessionId]?.text === pending.message) saved.drafts[token.sessionId] = { text: "", context: pending.context, allowWeb: pending.allow_web, webBackend: pending.web_backend }
      save(token.projectId, token.accountGeneration)
      if (current(token)) { if (state.input === pending.message) { state.input = ""; state.context = pending.context } setRun(run); state.pendingSubmission = false; state.error = "" }
      workflow.adopt(run, { sessionId: token.sessionId, runId: run.id }, token.projectId)
    } catch (error) { if (current(token)) state.error = error.message || "暂时无法恢复提交。" }
    finally { if (current(token)) state.busy = false }
  }
  async function stop() {
    if (!state.run || state.busy) return
    const token = scope()
    try { const run = await api().stop(token.projectId, state.run.id); if (current(token)) setRun(run) }
    catch (error) { if (current(token)) state.error = error.message || "停止请求未确认，请重试。" }
  }
  async function resume(renewBudget) {
    if (!state.run || state.busy) return
    const token = scope()
    state.busy = true
    try {
      const payload = { novel_id: token.projectId, renew_budget: renewBudget, ...(renewBudget ? { operation_id: crypto.randomUUID() } : {}) }
      const run = await api().resume(state.run.id, payload)
      if (current(token)) { setRun(run); state.error = ""; workflow.adopt(run, { sessionId: token.sessionId, runId: run.id }, token.projectId) }
    } catch (error) { if (current(token)) state.error = error.message || "续查未成功，请重试。" }
    finally { if (current(token)) state.busy = false }
  }
  async function decide(selected = state.selected, retry = false) {
    const batch = state.run?.result?.batch
    if (!batch || state.busy) return
    const token = scope()
    const runId = state.run.id
    const actions = state.run.result.actions || []
    const saved = record(token.projectId)
    state.busy = true
    try {
      if (saved.decisions[batch.id] && JSON.stringify([...saved.decisions[batch.id].selected].sort()) !== JSON.stringify([...selected].sort())) throw new Error("上次确认尚未收到回执，请先恢复原选择并刷新结果。")
      for (const action of actions.filter(item => selected.includes(item.key))) {
        if (batch.results?.some(item => item.key === action.key && item.status === "completed")) continue
        const baseline = action.capability === "writing.revise" ? action.arguments
          : ["writing.adopt_candidate", "writing.restore_version"].includes(action.capability) ? action.preview?.working_base : null
        if (!baseline?.draft_id) continue
        const actual = await getCurrentWritingFingerprint(token.projectId, baseline.draft_id)
        if (!current(token)) return
        if (actual && actual !== baseline.source_hash) throw new Error("编辑器已有新输入，尚未采用旧方案。请保存正文后重新检查。")
      }
      const payload = saved.decisions[batch.id] || { novel_id: token.projectId, fingerprint: batch.fingerprint, selected: [...selected], confirmed: true, ...(retry ? { retry_operation_id: crypto.randomUUID() } : {}) }
      saved.decisions[batch.id] = payload
      save(token.projectId, token.accountGeneration)
      const result = await api().decide(batch.id, payload)
      if (token.accountGeneration !== accountGeneration) return
      delete saved.decisions[batch.id]
      save(token.projectId, token.accountGeneration)
      if (current(token)) state.run.result.batch = { ...batch, ...result, selected: payload.selected }
      await refreshRun(runId, token)
    } catch (error) { if (current(token)) state.error = error.message || "尚未确认保存，请核对后重试。" }
    finally { if (current(token)) state.busy = false }
  }
  async function recheckBatch() {
    const batch = state.run?.result?.batch
    if (batch?.status !== "partial" || state.busy) return
    const token = scope(), saved = record(token.projectId), key = `recheck:${batch.id}`
    const payload = saved.decisions[key] || { novel_id: token.projectId, operation_id: crypto.randomUUID() }
    saved.decisions[key] = payload
    save()
    state.busy = true
    try {
      const run = await api().recheck(batch.id, payload)
      if (token.accountGeneration !== accountGeneration) return
      delete saved.decisions[key]
      saved.viewedRuns[token.sessionId] = run.id
      save(token.projectId, token.accountGeneration)
      if (current(token)) {
        setRun(run); state.error = ""
        workflow.adopt(run, { sessionId: token.sessionId, runId: run.id }, token.projectId)
      }
    } catch (error) { if (current(token)) state.error = error.message || "重新检查尚未确认，重试将沿用本次请求。" }
    finally { if (current(token)) state.busy = false }
  }
  async function moreMessages() {
    if (!state.sessionId || state.loading) return
    const token = scope()
    state.loading = true
    try {
      const olderEnd = Math.max(0, state.messageTotal - state.messages.filter(item => !item.optimistic).length)
      const skip = Math.max(0, olderEnd - 30)
      const result = await api().messages(token.projectId, token.sessionId, { skip, limit: Math.max(1, olderEnd - skip) })
      if (current(token)) { mergeMessages(result.items); state.messageTotal = result.total }
    } catch (error) { if (current(token)) state.error = error.message || "历史暂时无法读取。" }
    finally { if (current(token)) state.loading = false }
  }
  async function moreSessions() {
    if (!state.projectId || state.loading) return
    const token = scope()
    state.loading = true
    try {
      const result = await api().sessions(token.projectId, { skip: state.sessionOffset, limit: 20 })
      if (current(token)) { state.sessionOffset += result.items.length; state.total = result.total; state.sessions = Array.from(new Map([...state.sessions, ...result.items].map(item => [item.id, item])).values()) }
    } catch (error) { if (current(token)) state.error = error.message || "讨论列表暂时无法读取。" }
    finally { if (current(token)) state.loading = false }
  }
  function invalidate() { accountGeneration += 1; generation += 1; drafts.clear(); workflow.resetMemoryScope(); Object.assign(state, { projectId: null, sessionId: null, sessions: [], input: "", messages: [], run: null, enabled: false, context: null, error: "", pendingSubmission: false, backupError: false, busy: false, loading: false, selected: [] }) }
  function beforeUnload(event) { if (state.projectId && state.backupError && (state.input || Object.values(record(state.projectId).pending).length || Object.values(record(state.projectId).decisions).length)) { event.preventDefault(); event.returnValue = "" } }
  globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidate)
  globalThis.addEventListener?.("beforeunload", beforeUnload)
  return { state, load, selectSession, newSession, setInput, setAllowWeb, send, stop, resume, decide, moreMessages, moreSessions, recoverSubmission, refreshRun, openRun, recheckBatch, workflow,
    dispose() { if (getAppState()?.currentProjectId === state.projectId) setInput(state.input); generation += 1; workflow.stop(); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidate); globalThis.removeEventListener?.("beforeunload", beforeUnload) },
  }
}
