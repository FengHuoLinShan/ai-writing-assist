/**
 * prewarmManager 测试 — 按项目一次性预热（P2 评审：去重/回写/切换 abort）。
 * 管理器为模块级状态，各用例使用唯一项目 ID 隔离。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { ensurePrewarm } from "../../../vue/views/rag/prewarmManager.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import {
  ragSearchSession,
  resetRagSearchSession,
  scopeRagSessionToProject,
} from "../../../vue/views/rag/ragSearchSession.js"

function useProject(projectId) {
  setBridgeOverrides({ state: { currentProjectId: projectId } })
}

beforeEach(() => {
  vi.clearAllMocks()
  resetRagSearchSession()
  ragSearchSession.prewarmState = "idle"
  ragSearchSession.prewarmWarning = ""
  ragSearchSession.prewarmResult = null
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("去重语义", () => {
  it("同项目 in-flight 期间不重复发起", async () => {
    useProject("p-inflight")
    let resolveFirst
    globalThis.api.rag.prewarm = vi.fn(() => new Promise((resolve) => { resolveFirst = resolve }))

    const first = ensurePrewarm()
    const second = await ensurePrewarm()
    expect(second).toBeNull()
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(1)
    resolveFirst({ status: "ready", embedding_dim: 1024, cache_stats: { hits: 1, misses: 0 } })
    await first
  })

  it("ready 之后不再发起（同项目）", async () => {
    useProject("p-ready")
    globalThis.api.rag.prewarm = vi.fn(async () => ({ status: "ready", embedding_dim: 1024, cache_stats: {} }))

    await ensurePrewarm()
    expect(await ensurePrewarm()).toBeNull()
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(1)
  })

  it("失败后允许重试（对应 vanilla 每次 onEnter 重试）", async () => {
    useProject("p-fail-retry")
    globalThis.api.rag.prewarm = vi.fn()
      .mockImplementationOnce(async () => {
        throw new Error("模型不可用")
      })
      .mockImplementationOnce(async () => ({ status: "ready", embedding_dim: 1024, cache_stats: {} }))

    await ensurePrewarm()
    expect(ragSearchSession.prewarmState).toBe("failed")
    await ensurePrewarm()
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(2)
    expect(ragSearchSession.prewarmState).toBe("ready")
  })

  it("force 重新发起（手动按钮）", async () => {
    useProject("p-force")
    globalThis.api.rag.prewarm = vi.fn(async () => ({ status: "ready", embedding_dim: 1024, cache_stats: {} }))
    await ensurePrewarm()
    await ensurePrewarm({ force: true })
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(2)
  })
})

describe("结果回写（vanilla _prewarm 字段回写语义）", () => {
  it("ready 时回写 dim/runtime/cache_stats", async () => {
    useProject("p-write")
    globalThis.api.rag.prewarm = vi.fn(async () => ({
      status: "ready",
      embedding_dim: 1536,
      cache_stats: { hits: 9, misses: 1 },
    }))

    await ensurePrewarm()
    expect(ragSearchSession.prewarmResult.embedding_dim).toBe(1536)
    expect(ragSearchSession.prewarmResult.embedding_runtime).toEqual({
      started: true,
      healthy: true,
      cache_stats: { hits: 9, misses: 1 },
    })
  })

  it("HTTP 成功但非 ready 仍回写（healthy=false）", async () => {
    useProject("p-degraded")
    globalThis.api.rag.prewarm = vi.fn(async () => ({
      status: "degraded",
      warning: "模型降级",
      embedding_dim: 512,
      cache_stats: {},
    }))

    await ensurePrewarm()
    expect(ragSearchSession.prewarmState).toBe("failed")
    expect(ragSearchSession.prewarmWarning).toBe("模型降级")
    expect(ragSearchSession.prewarmResult.embedding_runtime.healthy).toBe(false)
  })
})

describe("项目切换", () => {
  it("切换项目时 abort 旧请求且不写状态", async () => {
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({ state })
    let resolveFirst
    globalThis.api.rag.prewarm = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(async () => ({ status: "ready", embedding_dim: 1024, cache_stats: {} }))

    const first = ensurePrewarm()
    state.currentProjectId = "p-new"
    const second = ensurePrewarm()
    resolveFirst({ status: "ready", embedding_dim: 512, cache_stats: {} })
    await Promise.all([first, second])

    // 旧项目的晚到响应不覆盖新项目状态
    expect(ragSearchSession.prewarmResult.embedding_dim).toBe(1024)
  })

  it("新项目尚未发起预热时，旧项目晚到响应不写入新会话", async () => {
    const state = { currentProjectId: "p-deferred-old" }
    setBridgeOverrides({ state })
    let resolveFirst
    globalThis.api.rag.prewarm = vi.fn(() => new Promise((resolve) => { resolveFirst = resolve }))

    const first = ensurePrewarm()
    state.currentProjectId = "p-deferred-new"
    scopeRagSessionToProject("p-deferred-new")
    resolveFirst({ status: "ready", embedding_dim: 512, cache_stats: {} })

    await expect(first).resolves.toBeNull()
    expect(ragSearchSession.ownerProjectId).toBe("p-deferred-new")
    expect(ragSearchSession.prewarmState).toBe("idle")
    expect(ragSearchSession.prewarmResult).toBeNull()
  })
})
