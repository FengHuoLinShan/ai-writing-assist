/**
 * useRagWorkflow 测试 — 重建/重试/恢复/预热（对应原 ragView.test.js 的
 * 轮询恢复与重试用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope, reactive } from "vue"
import { useRagWorkflow } from "../../../vue/views/rag/useRagWorkflow.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import {
  ragSearchSession,
  resetRagSearchSession,
  scopeRagSessionToProject,
} from "../../../vue/views/rag/ragSearchSession.js"

function makeStatusFields(overrides = {}) {
  return reactive({
    totalChunks: 10,
    embeddingFailedCount: 0,
    retryableEmbeddingCount: 0,
    statusWarnings: [],
    statusDegraded: false,
    ...overrides,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  scopeRagSessionToProject(null)
  resetRagSearchSession()
  ragSearchSession.rebuildProgress = null
  ragSearchSession.rebuildInfo = null
  localStorage.clear()
  setBridgeOverrides({ state: { currentProjectId: "p1" } })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("rebuildIndex", () => {
  it("提交任务后持久化工作流并开始轮询", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t1" }))
    globalThis.api.tasks.get = vi.fn(async () => ({
      task_id: "t1",
      task_type: "rag_reindex_novel",
      status: "running",
      progress: 40,
    }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    await workflow.rebuildIndex({ contentMode: "working", start: "1", end: "3" })

    expect(globalThis.api.rag.rebuild).toHaveBeenCalledWith(
      expect.objectContaining({ novel_id: "p1", content_mode: "working", start_chapter: 1, end_chapter: 3 }),
    )
    expect(ragSearchSession.rebuildProgress?.taskId).toBe("t1")
    await vi.waitFor(() => {
      expect(globalThis.api.tasks.get).toHaveBeenCalledWith("t1", "p1")
    })
    expect(globalThis.toast).toHaveBeenCalledWith("索引重建任务已提交", "success")
    const persisted = JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]")
    expect(persisted.some((w) => w.taskId === "t1" && w.workflowType === "rag_reindex_novel")).toBe(true)
    scope.stop()
  })

  it("章节区间不完整时拒绝提交，避免静默退化为全量重建", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t1" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    expect(await workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "3" })).toBe(false)
    expect(globalThis.api.rag.rebuild).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith("请同时填写起始章节和结束章节", "warning")
    scope.stop()
  })

  it("章节区间反向时拒绝提交，避免静默退化为全量重建", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t1" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    expect(await workflow.rebuildIndex({ contentMode: "working", start: "62", end: "61" })).toBe(false)
    expect(globalThis.api.rag.rebuild).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith("结束章节不能小于起始章节", "warning")
    scope.stop()
  })

  it("章节区间不是正整数时拒绝提交", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t1" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    expect(await workflow.rebuildIndex({ contentMode: "working", start: "0", end: "1.5" })).toBe(false)
    expect(globalThis.api.rag.rebuild).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith("章节范围必须是大于等于 1 的整数", "warning")
    scope.stop()
  })

  it("无可索引内容时提示 info", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ total: 0 }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    await workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "" })
    expect(ragSearchSession.rebuildInfo).toBe("暂无可索引工作稿")
    expect(globalThis.toast).toHaveBeenCalledWith("暂无可索引工作稿", "info")
    scope.stop()
  })

  it("项目切换后忽略旧轮询的晚到状态", async () => {
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({ state })
    scopeRagSessionToProject("p-old")
    let resolveTask
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t-old" }))
    globalThis.api.tasks.get = vi.fn(() => new Promise((resolve) => { resolveTask = resolve }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    await workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "" })
    await vi.waitFor(() => expect(globalThis.api.tasks.get).toHaveBeenCalledWith("t-old", "p-old"))

    state.currentProjectId = "p-new"
    scopeRagSessionToProject("p-new")
    resolveTask({
      task_id: "t-old",
      task_type: "rag_reindex_novel",
      status: "running",
      progress: 60,
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(ragSearchSession.ownerProjectId).toBe("p-new")
    expect(ragSearchSession.rebuildProgress).toBeNull()
    scope.stop()
  })

  it("同步双击只提交一个重建任务并在响应后释放锁", async () => {
    let resolveRebuild
    globalThis.api.rag.rebuild = vi.fn(() => new Promise((resolve) => { resolveRebuild = resolve }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    const first = workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "" })
    const second = workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "" })
    await expect(second).resolves.toBe(false)
    expect(globalThis.api.rag.rebuild).toHaveBeenCalledTimes(1)
    expect(workflow.maintenanceSubmitting.value).toBe(true)

    resolveRebuild({ task_id: "t-double" })
    await expect(first).resolves.toBe(true)
    expect(workflow.maintenanceSubmitting.value).toBe(false)
    scope.stop()
  })

  it("提交异常后释放重建锁以允许重试", async () => {
    globalThis.api.rag.rebuild = vi.fn()
      .mockRejectedValueOnce(new Error("网络失败"))
      .mockResolvedValueOnce({ total: 0 })
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    await expect(workflow.rebuildIndex({})).resolves.toBe(false)
    expect(workflow.maintenanceSubmitting.value).toBe(false)
    await expect(workflow.rebuildIndex({})).resolves.toBe(true)
    expect(globalThis.api.rag.rebuild).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it("scope 销毁后忽略晚到提交响应，不复活会话、轮询或提示", async () => {
    let resolveRebuild
    globalThis.api.rag.rebuild = vi.fn(() => new Promise((resolve) => { resolveRebuild = resolve }))
    globalThis.api.tasks.get = vi.fn()
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    const pending = workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "" })
    expect(globalThis.api.rag.rebuild.mock.calls[0]).toHaveLength(1)
    expect(workflow.maintenanceSubmitting.value).toBe(true)
    globalThis.toast.mockClear()
    scope.stop()
    resolveRebuild({ task_id: "t-after-dispose" })

    await expect(pending).resolves.toBe(true)
    expect(workflow.maintenanceSubmitting.value).toBe(false)
    expect(ragSearchSession.rebuildProgress).toBeNull()
    expect(globalThis.api.tasks.get).not.toHaveBeenCalled()
    expect(globalThis.toast).not.toHaveBeenCalled()
  })
})

describe("retryEmbeddings", () => {
  it("无可重试向量时不发请求", async () => {
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    await workflow.retryEmbeddings()
    expect(globalThis.toast).toHaveBeenCalledWith("暂无可重试的失败向量", "info")
    expect(globalThis.api.rag.retryEmbeddings).not.toHaveBeenCalled()
    scope.stop()
  })

  it("有可重试向量时提交 rag_retry_embeddings 任务", async () => {
    globalThis.api.rag.retryEmbeddings = vi.fn(async () => ({ task_id: "t9" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({
      statusFields: makeStatusFields({ retryableEmbeddingCount: 4 }),
    }))
    await workflow.retryEmbeddings()
    expect(globalThis.api.rag.retryEmbeddings).toHaveBeenCalledWith(
      expect.objectContaining({ novel_id: "p1", statuses: ["failed", "pending_vectorization"] }),
    )
    expect(ragSearchSession.rebuildProgress?.workflowType).toBe("rag_retry_embeddings")
    scope.stop()
  })

  it("同步双击只提交一个向量重试任务", async () => {
    let resolveRetry
    globalThis.api.rag.retryEmbeddings = vi.fn(() => new Promise((resolve) => { resolveRetry = resolve }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({
      statusFields: makeStatusFields({ retryableEmbeddingCount: 4 }),
    }))

    const first = workflow.retryEmbeddings()
    const second = workflow.retryEmbeddings()
    await expect(second).resolves.toBe(false)
    expect(globalThis.api.rag.retryEmbeddings).toHaveBeenCalledTimes(1)
    resolveRetry({ task_id: "t-retry-double" })
    await expect(first).resolves.toBe(true)
    expect(workflow.maintenanceSubmitting.value).toBe(false)
    scope.stop()
  })
})

describe("retryFailedTask", () => {
  it("重试失败任务并恢复轮询", async () => {
    ragSearchSession.rebuildProgress = {
      taskId: "t5",
      workflowType: "rag_reindex_novel",
      availableActions: ["retry"],
      raw: { task_id: "t5", result: { error: "boom" } },
    }
    globalThis.api.tasks.retry = vi.fn(async () => ({ status: "pending" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    const ok = await workflow.retryFailedTask()
    expect(ok).toBe(true)
    expect(globalThis.api.tasks.retry).toHaveBeenCalledWith("t5", "p1")
    expect(globalThis.toast).toHaveBeenCalledWith("任务已重新加入队列", "success")
    expect(ragSearchSession.taskRetryPending).toBe(false)
    scope.stop()
  })

  it("无 retry 权限时直接返回 false", async () => {
    ragSearchSession.rebuildProgress = { taskId: "t5", availableActions: [] }
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    expect(await workflow.retryFailedTask()).toBe(false)
    expect(globalThis.api.tasks.retry).not.toHaveBeenCalled()
    scope.stop()
  })

  it("项目切换后不让旧重试响应覆盖新项目任务", async () => {
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({ state })
    scopeRagSessionToProject("p-old")
    ragSearchSession.rebuildProgress = {
      taskId: "t-old",
      workflowType: "rag_reindex_novel",
      availableActions: ["retry"],
      raw: { task_id: "t-old", result: { error: "boom" } },
    }
    let resolveRetry
    globalThis.api.tasks.retry = vi.fn(() => new Promise((resolve) => { resolveRetry = resolve }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))

    const pending = workflow.retryFailedTask()
    state.currentProjectId = "p-new"
    scopeRagSessionToProject("p-new")
    ragSearchSession.rebuildProgress = { taskId: "t-new", status: "running" }
    ragSearchSession.taskRetryPending = true
    resolveRetry({ status: "pending" })

    await expect(pending).resolves.toBe(true)
    expect(ragSearchSession.rebuildProgress).toEqual({ taskId: "t-new", status: "running" })
    expect(ragSearchSession.taskRetryPending).toBe(true)
    expect(globalThis.toast).not.toHaveBeenCalledWith("任务已重新加入队列", "success")
    scope.stop()
  })
})

describe("recoverRebuildWorkflow", () => {
  it("从 localStorage 恢复活动工作流并轮询", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      { taskId: "t7", workflowType: "rag_reindex_novel", projectId: "p1", view: "rag" },
    ]))
    globalThis.api.tasks.get = vi.fn(async () => ({
      task_id: "t7",
      task_type: "rag_reindex_novel",
      status: "done",
      progress: 100,
      result: { chunks_created: 42 },
    }))
    const statusFields = makeStatusFields()
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields }))

    workflow.recoverRebuildWorkflow()
    expect(ragSearchSession.rebuildProgress?.taskId).toBe("t7")
    await vi.waitFor(() => {
      expect(statusFields.totalChunks).toBe(42)
    })
    expect(globalThis.api.tasks.get).toHaveBeenCalledWith("t7", "p1")
    scope.stop()
  })

  it("终态刷新失败也会收口已完成工作流", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      { taskId: "t-refresh", workflowType: "rag_retry_embeddings", projectId: "p1", view: "rag" },
    ]))
    globalThis.api.tasks.get = vi.fn(async () => ({
      task_id: "t-refresh",
      task_type: "rag_retry_embeddings",
      status: "done",
      progress: 100,
      result: { remaining_retryable_count: 0 },
    }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({
      statusFields: makeStatusFields(),
      refreshStatus: vi.fn().mockRejectedValue(new Error("暂时不可用")),
    }))

    workflow.recoverRebuildWorkflow()
    await vi.waitFor(() => expect(globalThis.toast).toHaveBeenCalledWith(
      "索引任务已完成，但状态刷新失败：暂时不可用",
      "warning",
    ))

    const persisted = JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]")
    expect(persisted.some((item) => item.taskId === "t-refresh")).toBe(false)
    scope.stop()
  })
})

describe("项目会话隔离", () => {
  it("跨项目时清理重建与预热元数据，同项目重挂载时保留", () => {
    scopeRagSessionToProject("p-old")
    ragSearchSession.rebuildProgress = { taskId: "old-task" }
    ragSearchSession.rebuildInfo = "旧项目索引"
    ragSearchSession.hits = [{ id: "old-hit" }]
    ragSearchSession.prewarmState = "ready"
    ragSearchSession.prewarmWarning = "旧项目警告"
    ragSearchSession.prewarmResult = { embedding_dim: 512 }
    ragSearchSession.rebuildForm = { contentMode: "working", start: "2", end: "4" }

    expect(scopeRagSessionToProject("p-old")).toBe(false)
    expect(ragSearchSession.prewarmResult).toEqual({ embedding_dim: 512 })
    expect(ragSearchSession.rebuildForm).toEqual({ contentMode: "working", start: "2", end: "4" })

    expect(scopeRagSessionToProject("p-new")).toBe(true)
    expect(ragSearchSession.ownerProjectId).toBe("p-new")
    expect(ragSearchSession.rebuildProgress).toBeNull()
    expect(ragSearchSession.rebuildInfo).toBeNull()
    expect(ragSearchSession.hits).toEqual([])
    expect(ragSearchSession.prewarmState).toBe("idle")
    expect(ragSearchSession.prewarmWarning).toBe("")
    expect(ragSearchSession.prewarmResult).toBeNull()
    expect(ragSearchSession.rebuildForm).toEqual({ contentMode: "canonical", start: "", end: "" })
  })
})

describe("prewarm（已迁移至 prewarmManager，见其测试）", () => {
  it("useRagWorkflow 不再暴露 prewarm（避免组件生命周期内重启）", () => {
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    expect(workflow.prewarm).toBeUndefined()
    scope.stop()
  })
})
