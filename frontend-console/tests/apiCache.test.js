/**
 * API 缓存失效逻辑测试 — 回归
 *
 * 背景: 回收站(recycle-bin)列表是 GET 缓存。恢复(/projects/{id}/restore)、
 * 永久删除(/projects/{id}/permanent)是写操作,必须失效同一集合(/projects)的所有列表缓存,
 * 否则 30s TTL 内重开回收站显示已删除的旧项目,重复删除报"资源不存在"。
 *
 * 旧实现按 "base 或 base 父路径的字符串 include" 匹配,/{id}/restore 的父路径是
 * /projects/{id},不含 recycle-bin key,导致遗漏。新实现按集合根(第一路径段)失效。
 *
 * api.js 用 window.api 导出,内部 _invalidateRelatedCache/_apiCache 不可 import,
 * 故此处镜像其失效语义并断言行为(与 state-preservation 测试同一模式)。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import "../api.js"

// ---- 镜像 api.js 的失效实现 ----
const _apiCache = new Map()

function _invalidateRelatedCache(path) {
  const base = path.split("?")[0]
  const collectionRoot = "/" + base.split("/").filter(Boolean)[0]
  for (const key of _apiCache.keys()) {
    const keyPath = key.slice(key.indexOf(":") + 1)
    if (keyPath === collectionRoot || keyPath.startsWith(collectionRoot + "/") || keyPath.startsWith(collectionRoot + "?")) {
      _apiCache.delete(key)
    }
  }
}

function seedCache() {
  _apiCache.set("GET:/projects?skip=0&limit=20", { data: [], time: Date.now() })
  _apiCache.set("GET:/projects/recycle-bin?skip=0&limit=20", { data: [], time: Date.now() })
  _apiCache.set("GET:/projects/p1", { data: {}, time: Date.now() })
  _apiCache.set("GET:/world/entities?novel_id=p1", { data: [], time: Date.now() })
}

beforeEach(() => {
  _apiCache.clear()
  seedCache()
})

describe("_invalidateRelatedCache — 集合根失效", () => {
  it("软删除 DELETE /projects/{id} 失效 recycle-bin 与列表缓存", () => {
    _invalidateRelatedCache("/projects/p1")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
    expect(_apiCache.has("GET:/projects?skip=0&limit=20")).toBe(false)
  })

  it("恢复 POST /projects/{id}/restore 失效 recycle-bin 缓存(回归)", () => {
    _invalidateRelatedCache("/projects/p1/restore")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
    expect(_apiCache.has("GET:/projects?skip=0&limit=20")).toBe(false)
  })

  it("永久删除 DELETE /projects/{id}/permanent 失效 recycle-bin 缓存(回归)", () => {
    _invalidateRelatedCache("/projects/p1/permanent")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
  })

  it("不跨集合误失效: 改 /projects 不影响 /world 缓存", () => {
    _invalidateRelatedCache("/projects/p1/permanent")
    expect(_apiCache.has("GET:/world/entities?novel_id=p1")).toBe(true)
  })
})

// ============================================================
// 实际 api.js 缓存行为测试
// ============================================================

describe("api.js cache behavior", () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    window.api.clearCache()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it("health check requests bypass cache by using unique _ts", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ok" }),
    }))

    const dateSpy = vi.spyOn(Date, "now")
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(2000)

    const r1 = await window.api.healthCheck()
    const r2 = await window.api.healthCheck()

    dateSpy.mockRestore()

    expect(r1).toBe(true)
    expect(r2).toBe(true)
    expect(globalThis.fetch).toHaveBeenCalledTimes(2)

    const urls = globalThis.fetch.mock.calls.map((call) => call[0])
    expect(urls[0]).not.toBe(urls[1])
    expect(new URL(urls[0]).searchParams.has("_ts")).toBe(true)
    expect(new URL(urls[1]).searchParams.has("_ts")).toBe(true)
  })

  it("failed POST does not clear existing GET cache", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Cached" }]),
    }))

    const first = await window.api.projects.list()
    expect(first).toEqual([{ id: "p1", title: "Cached" }])
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)

    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "internal error" }),
    }))

    await expect(window.api.projects.create({ name: "new" })).rejects.toThrow()

    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Fresh" }]),
    }))

    const second = await window.api.projects.list()
    expect(second).toEqual([{ id: "p1", title: "Cached" }])
    // GET 仍命中缓存，不应再次发起网络请求
    expect(globalThis.fetch).toHaveBeenCalledTimes(0)
  })

  it("successful POST clears related GET cache", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Cached" }]),
    }))

    await window.api.projects.list()

    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: "p2", title: "Created" }),
    }))

    await window.api.projects.create({ name: "new" })

    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Fresh" }]),
    }))

    const second = await window.api.projects.list()
    expect(second).toEqual([{ id: "p1", title: "Fresh" }])
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })

  it("concurrent GET callers share the parsed JSON result, not raw Response", async () => {
    let resolveFetch
    globalThis.fetch = vi.fn(() => new Promise((resolve) => {
      resolveFetch = resolve
    }))

    const promiseA = window.api.projects.list()
    const promiseB = window.api.projects.list()

    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    resolveFetch({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Shared" }]),
    })

    await expect(promiseA).resolves.toEqual([{ id: "p1", title: "Shared" }])
    await expect(promiseB).resolves.toEqual([{ id: "p1", title: "Shared" }])
  })

  it("GET with external abort signal does not poison the shared pending GET", async () => {
    const resolvers = []
    globalThis.fetch = vi.fn((_url, init) => new Promise((resolve, reject) => {
      const onAbort = () => {
        const err = new Error("Aborted")
        err.name = "AbortError"
        reject(err)
      }
      init.signal?.addEventListener("abort", onAbort, { once: true })
      resolvers.push((value) => {
        init.signal?.removeEventListener("abort", onAbort)
        resolve(value)
      })
    }))

    const controller = new AbortController()
    const abortable = window.api.request("/projects", { signal: controller.signal })
    const shared = window.api.request("/projects")

    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    controller.abort()
    resolvers[1]({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Shared" }]),
    })

    await expect(abortable).rejects.toThrow("请求已取消")
    await expect(shared).resolves.toEqual([{ id: "p1", title: "Shared" }])
  })

  it("cached GET returns clean up their per-call timeout", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: "p1", title: "Cached" }]),
    }))

    await window.api.projects.list()

    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout")
    const cached = await window.api.projects.list()

    expect(cached).toEqual([{ id: "p1", title: "Cached" }])
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    expect(clearTimeoutSpy).toHaveBeenCalled()
    clearTimeoutSpy.mockRestore()
  })

  it("GET callers with different external signals do not share pending promise", async () => {
    let resolveFirst
    globalThis.fetch = vi.fn((_url, init) => new Promise((resolve, reject) => {
      if (init.signal?.aborted) {
        const err = new Error("Aborted")
        err.name = "AbortError"
        reject(err)
        return
      }
      const onAbort = () => {
        const err = new Error("Aborted")
        err.name = "AbortError"
        reject(err)
      }
      init.signal?.addEventListener("abort", onAbort, { once: true })
      resolveFirst = (value) => {
        init.signal?.removeEventListener("abort", onAbort)
        resolve(value)
      }
    }))

    const controllerA = new AbortController()
    const controllerB = new AbortController()

    const promiseA = window.api.request("/projects", { signal: controllerA.signal })
    const promiseB = window.api.request("/projects", { signal: controllerB.signal })

    expect(globalThis.fetch).toHaveBeenCalledTimes(2)

    controllerA.abort()

    resolveFirst({ ok: true, status: 200, json: () => Promise.resolve([{ id: "p1" }]) })

    await expect(promiseA).rejects.toThrow("请求已取消")
    await expect(promiseB).resolves.toEqual([{ id: "p1" }])
  })

  it("does not pass timeout or stray signal to fetch init", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    }))

    const externalController = new AbortController()
    await window.api.request("/projects", { timeout: 12345, signal: externalController.signal })

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init).not.toHaveProperty("timeout")
    // 外部 signal 不应直接出现在 init 中；api.js 会将其与内部 timeout 合并后传递
    expect(init.signal).not.toBe(externalController.signal)
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })

  it("distinguishes external abort from timeout", async () => {
    globalThis.fetch = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      if (init.signal?.aborted) {
        const err = new Error("Aborted")
        err.name = "AbortError"
        reject(err)
        return
      }
      const onAbort = () => {
        const err = new Error("Aborted")
        err.name = "AbortError"
        reject(err)
      }
      init.signal?.addEventListener("abort", onAbort, { once: true })
    }))

    const controller = new AbortController()
    const promise = window.api.request("/projects", { signal: controller.signal })
    controller.abort()

    await expect(promise).rejects.toThrow("请求已取消")
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })
})
