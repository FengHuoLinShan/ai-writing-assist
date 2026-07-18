/**
 * useRagWorkflow 测试 — 重建/重试/恢复/预热（对应原 ragView.test.js 的
 * 轮询恢复与重试用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope, reactive } from "vue"
import { useRagWorkflow } from "../../../vue/views/rag/useRagWorkflow.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ragSearchSession, resetRagSearchSession } from "../../../vue/views/rag/ragSearchSession.js"

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
  resetRagSearchSession()
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
      expect.any(Object),
    )
    expect(ragSearchSession.rebuildProgress?.taskId).toBe("t1")
    expect(globalThis.toast).toHaveBeenCalledWith("索引重建任务已提交", "success")
    const persisted = JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]")
    expect(persisted.some((w) => w.taskId === "t1" && w.workflowType === "rag_reindex_novel")).toBe(true)
    scope.stop()
  })

  it("章节区间不完整时不写入范围", async () => {
    globalThis.api.rag.rebuild = vi.fn(async () => ({ task_id: "t1" }))
    const scope = effectScope()
    const workflow = scope.run(() => useRagWorkflow({ statusFields: makeStatusFields() }))
    await workflow.rebuildIndex({ contentMode: "canonical", start: "", end: "3" })
    expect(globalThis.api.rag.rebuild).toHaveBeenCalledWith(
      expect.not.objectContaining({ start_chapter: expect.anything() }),
      expect.any(Object),
    )
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
      expect.any(Object),
    )
    expect(ragSearchSession.rebuildProgress?.workflowType).toBe("rag_retry_embeddings")
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
    scope.stop()
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
