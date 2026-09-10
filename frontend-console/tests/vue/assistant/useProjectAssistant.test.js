import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"
import { setBridgeOverrides } from "../../../vue/bridge/index.js"
import { invalidateAccountBrowserState } from "../../../shared/accountStorage.js"
import { createProjectAssistant } from "../../../vue/composables/useProjectAssistant.js"

const mocks = vi.hoisted(() => ({ configs: [], adopt: vi.fn(), prepare: vi.fn() }))
vi.mock("../../../vue/shared/workflowManager.js", () => ({ createWorkflowManager: config => {
  mocks.configs.push(config)
  return { adopt: mocks.adopt, prepare: mocks.prepare, recover: vi.fn(), stop: vi.fn(), resetMemoryScope: vi.fn() }
} }))
let controller
let state
let api
function pending() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function run(body) { return { id: body.operation_id, task_id: body.operation_id, status: "pending", result: {}, usage: {} } }

beforeEach(() => {
  localStorage.clear()
  mocks.configs.length = 0
  vi.clearAllMocks()
  state = { currentProjectId: "p1" }
  api = {
    capabilities: vi.fn(async () => ({ enabled: true })),
    sessions: vi.fn(async projectId => ({ items: [{ id: `${projectId}-s`, title: "讨论" }], total: 1 })),
    session: vi.fn(async (_projectId, id) => ({ session: { id, title: "讨论" }, messages: [], message_total: 0, latest_run: null })),
    createSession: vi.fn(async projectId => ({ id: `${projectId}-new`, title: "新讨论" })),
    submit: vi.fn(async (_id, body) => run(body)),
    run: vi.fn(async (_id, id) => ({ id, task_id: id, status: "pending", result: {} })),
    messages: vi.fn(),
  }
  setBridgeOverrides({ api: { assistant: api }, state })
  controller = createProjectAssistant()
})
afterEach(() => { controller.dispose(); setBridgeOverrides({ api: undefined, state: undefined, writingFingerprint: undefined }); localStorage.clear() })

describe("project assistant durable interaction", () => {
  it("keeps the first composition scope and explicit web choice when creating its session", async () => {
    api.sessions.mockResolvedValue({ items: [], total: 0 })
    api.capabilities.mockResolvedValue({ enabled: true, web_search: { available: true } })
    await controller.load("p1")
    controller.state.context = { page: "writing", chapter_index: 3, excluded_targets: ["world_entity:hidden"], scope: "current" }
    controller.setInput("核对 IANA")
    controller.setAllowWeb(true)
    await controller.send({ page: "world" })
    expect(api.submit).toHaveBeenCalledWith("p1-new", expect.objectContaining({
      message: "核对 IANA", allow_web: true, web_backend: "searxng-v1",
      context: { page: "writing", chapter_index: 3, excluded_targets: ["world_entity:hidden"], scope: "current" },
    }))
  })
  it("reopens an older partial receipt and preserves unsent input across reload", async () => {
    const latest = { id: "latest", status: "completed", result: {} }
    const old = { id: "old", status: "completed", result: { batch: { id: "old-batch", status: "partial", selected: ["edit"] } } }
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [{ id: "message", role: "assistant", assistant_run_id: "old", content: "原方案" }], message_total: 1, latest_run: latest })
    api.run.mockResolvedValue(old)
    await controller.load("p1")
    controller.setInput("尚未提交的想法")
    await controller.openRun("old")
    expect(controller.state.run.result.batch.id).toBe("old-batch")
    expect(controller.state.selected).toEqual(["edit"])
    controller.dispose()
    controller = createProjectAssistant()
    await controller.load("p1")
    expect(controller.state.run.id).toBe("old")
    expect(controller.state.input).toBe("尚未提交的想法")
    expect(controller.state.messages[0].assistant_run_id).toBe("old")
  })

  it("does not let a late historical receipt replace another session", async () => {
    await controller.load("p1")
    const response = pending()
    api.run.mockImplementation(() => response.promise)
    const opening = controller.openRun("old")
    await controller.selectSession("different")
    response.resolve({ id: "old", status: "completed", result: {} })
    await opening
    expect(controller.state.run).toBeNull()
    expect(controller.state.sessionId).toBe("different")
  })
  it("retains the reference scope after sending and restores it on another device", async () => {
    const scope = { page: "writing", chapter_index: 3, scope: "current", excluded_targets: ["world_entity:hidden"] }
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [], message_total: 0, latest_run: null, last_context: scope, last_allow_web: false })
    await controller.load("p1")
    expect(controller.state.context).toEqual(scope)
    controller.setInput("继续检查")
    await controller.send({ page: "world", scope: "project" })
    expect(api.submit.mock.calls[0][1].context).toEqual(scope)
    expect(api.submit.mock.calls[0][1].allow_web).toBe(false)
    expect(controller.state.context).toEqual(scope)
    await controller.load("p1")
    expect(controller.state.context).toEqual(scope)
    expect(controller.state.input).toBe("")
    expect(controller.state.allowWeb).toBe(false)
  })
  it("refuses a stale editor replacement before submitting approval", async () => {
    await controller.load("p1")
    api.decide = vi.fn()
    controller.state.run = { id: "run", result: { batch: { id: "batch", fingerprint: "hash", status: "pending" }, actions: [{ key: "edit", capability: "writing.revise", arguments: { draft_id: "draft", source_hash: "original" } }] } }
    setBridgeOverrides({ writingFingerprint: async () => "new-unsaved-input" })
    await controller.decide(["edit"])
    expect(api.decide).not.toHaveBeenCalled()
    expect(controller.state.error).toContain("编辑器已有新输入")
  })

  it("reuses a persisted retry receipt when an approval response was lost", async () => {
    await controller.load("p1")
    const result = { batch: { id: "batch", fingerprint: "hash", status: "partial", selected: ["todo"] }, actions: [{ key: "todo", capability: "project.add_task" }] }
    controller.state.run = { id: "run", result }
    api.decide = vi.fn().mockRejectedValueOnce(new Error("response lost")).mockResolvedValue({ status: "completed", results: [] })
    api.run.mockResolvedValue({ id: "run", result: { ...result, batch: { ...result.batch, status: "completed" } } })
    await controller.decide(["todo"], true)
    const receipt = api.decide.mock.calls[0][1].retry_operation_id
    expect(receipt).toBeTruthy()
    controller.dispose()
    controller = createProjectAssistant()
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [], message_total: 0, latest_run: { id: "run", result } })
    await controller.load("p1")
    await controller.decide(["todo"], true)
    expect(api.decide.mock.calls[1][1].retry_operation_id).toBe(receipt)
  })

  it("keeps the initial message and context while creating the first discussion", async () => {
    api.sessions.mockResolvedValue({ items: [], total: 0 })
    await controller.load("p1")
    controller.setInput("核对这一章")
    await controller.send({ page: "writing", chapter_index: 2 })
    expect(api.submit).toHaveBeenCalledWith("p1-new", expect.objectContaining({ message: "核对这一章", context: { page: "writing", chapter_index: 2 } }))
    expect(controller.state.input).toBe("")
    expect(controller.state.run.status).toBe("pending")
  })

  it("does not let a late submission overwrite another project's draft", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("旧作品的问题")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    state.currentProjectId = "p2"
    await controller.load("p2")
    controller.setInput("新作品的未提交内容")
    response.resolve(run(body))
    await sending
    expect(controller.state.input).toBe("新作品的未提交内容")
    expect(controller.state.run).toBeNull()
    expect(mocks.adopt).toHaveBeenLastCalledWith(expect.objectContaining({ id: body.operation_id }), expect.anything(), "p1")
  })

  it("keeps edits entered while acknowledgement is pending", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("第一条")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    controller.setInput("下一条还未发送")
    response.resolve(run(body))
    await sending
    expect(controller.state.input).toBe("下一条还未发送")
  })

  it("recovers an unknown submission without sending a changed message under its ID", async () => {
    api.submit.mockRejectedValueOnce(new Error("网络中断"))
    await controller.load("p1")
    controller.setInput("原请求")
    await controller.send({ page: "today" })
    const body = api.submit.mock.calls[0][1]
    controller.setInput("新的请求")
    await controller.send({ page: "world" })
    expect(api.submit).toHaveBeenCalledTimes(1)
    await controller.recoverSubmission()
    expect(api.run).toHaveBeenCalledWith("p1", body.operation_id)
    expect(api.submit).toHaveBeenCalledTimes(1)
    expect(controller.state.input).toBe("新的请求")
    expect(controller.state.pendingSubmission).toBe(false)
  })

  it("does not resurrect a previous account's backup after a late response", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("私有讨论")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    invalidateAccountBrowserState()
    response.resolve(run(body))
    await sending
    expect(controller.state.messages).toEqual([])
    expect(controller.state.input).toBe("")
    expect(Object.keys(localStorage).filter(key => key.startsWith("novel_assistant"))).toEqual([])
    expect(mocks.adopt).not.toHaveBeenCalled()
  })

  it("loads older discussion pages without dropping recent messages", async () => {
    const rows = Array.from({ length: 120 }, (_, index) => ({ id: `m${index}`, role: "author", content: String(index), created_at: String(index).padStart(3, "0") }))
    api.session.mockResolvedValue({ session: { id: "p1-s", title: "讨论" }, messages: rows.slice(80), message_total: 120, latest_run: null })
    api.messages.mockImplementation(async (_project, _session, { skip, limit }) => ({ items: rows.slice(skip, skip + limit), total: 120 }))
    await controller.load("p1")
    await controller.moreMessages()
    expect(api.messages).toHaveBeenCalledWith("p1", "p1-s", { skip: 50, limit: 30 })
    expect(controller.state.messages).toHaveLength(70)
    expect(controller.state.messages.at(-1).id).toBe("m119")
  })
})
