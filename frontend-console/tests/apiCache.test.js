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
import "../apiContracts.js"
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
    sessionStorage.clear()
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

  it("Scene fusion preview keeps the LLM request open beyond the default timeout", async () => {
    vi.useFakeTimers()
    try {
      let resolveFetch
      let requestSignal
      globalThis.fetch = vi.fn((url, init) => {
        requestSignal = init.signal
        return new Promise((resolve) => {
          resolveFetch = resolve
        })
      })

      const pending = window.api.outline.previewSceneFusion("p1", {
        source_scene_ids: ["s1", "s2"],
        primary_scene_id: "s1",
      })
      await vi.advanceTimersByTimeAsync(15_001)

      expect(requestSignal.aborted).toBe(false)
      expect(globalThis.fetch.mock.calls[0][0]).toContain(
        "/api/outline/scene-workbench/fusion/preview?novel_id=p1",
      )
      resolveFetch({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ mode: "fusion" }),
      })
      await expect(pending).resolves.toEqual({ mode: "fusion" })
    } finally {
      vi.useRealTimers()
    }
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

  it("永久删除请求显式携带二次确认", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 204 }))

    await window.api.projects.permanentDelete("p1")

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/projects/p1/permanent?confirmed=true")
    expect(init.method).toBe("DELETE")
  })

  it("批量永久删除使用单次已确认请求", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ deleted_ids: ["p1", "p2"], deleted_count: 2 }),
    }))

    await window.api.projects.permanentDeleteMany(["p1", "p2"])

    expect(globalThis.fetch).toHaveBeenCalledOnce()
    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/projects/recycle-bin/permanent-delete")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({
      project_ids: ["p1", "p2"],
      confirmed: true,
    })
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

describe("api.js request headers", () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    window.api.clearCache()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  function mockJsonResponse(payload = {}) {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(payload),
    }))
  }

  it("does not force X-Requested-With on GET requests", async () => {
    mockJsonResponse({ ok: true })

    await window.api.request("/settings/llm-defaults")

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers["X-Requested-With"]).toBeUndefined()
  })

  it("adds X-Requested-With to PUT, POST, and DELETE requests", async () => {
    for (const method of ["PUT", "POST", "DELETE"]) {
      mockJsonResponse({ ok: true })

      await window.api.request(`/settings/header-check-${method}`, { method })

      const init = globalThis.fetch.mock.calls[0][1]
      expect(init.headers["X-Requested-With"]).toBe("XMLHttpRequest")
    }
  })

  it("lets callers override X-Requested-With", async () => {
    mockJsonResponse({ ok: true })

    await window.api.request("/settings/llm-defaults", {
      method: "PUT",
      headers: { "X-Requested-With": "CustomClient" },
    })

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers["X-Requested-With"]).toBe("CustomClient")
  })

  it("keeps FormData Content-Type unset while adding X-Requested-With", async () => {
    mockJsonResponse({ ok: true })
    const form = new FormData()
    form.append("file", new Blob(["demo"]), "demo.txt")

    await window.api.request("/imports/upload", {
      method: "POST",
      body: form,
    })

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers["X-Requested-With"]).toBe("XMLHttpRequest")
    expect(init.headers["Content-Type"]).toBeUndefined()
  })

  it("adds Authorization when a closed-test token is stored in sessionStorage", async () => {
    mockJsonResponse({ ok: true })
    sessionStorage.setItem("novel_app_access_token", "test-token")

    await window.api.request("/projects")

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers.Authorization).toBe("Bearer test-token")
  })

  it("sends the explicit import authorization snapshot for stage starts", async () => {
    mockJsonResponse({ task_id: "import-1" })

    await window.api.imports.startStage("scenes", "p1", 1, 3, false, true, {
      adoption_policy: "user_authorized_pipeline",
      authorization_confirmed: true,
    })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/imports/stages/scenes")
    expect(JSON.parse(init.body)).toMatchObject({
      novel_id: "p1",
      start_chapter: 1,
      end_chapter: 3,
      high_quality: true,
      adoption_policy: "user_authorized_pipeline",
      authorization_confirmed: true,
    })
  })

  it("fails closed before starting an import without user authorization", async () => {
    mockJsonResponse({ task_id: "should-not-start" })

    await expect(window.api.imports.startStage("scenes", "p1", 1, 3))
      .rejects.toThrow("必须获得用户授权")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("posts edited Scene preview data to the explicit apply endpoint", async () => {
    mockJsonResponse({ status: "applied", scene_ids: ["scene-1"], total_scenes: 1 })

    await window.api.outline.applyChapterScenePreview({
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      source_task_id: "task-1",
      draft_scenes: [{ title: "用户修订" }],
      confirmed: true,
    })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/outline/chapter-scenes/apply")
    expect(JSON.parse(init.body)).toMatchObject({
      source_task_id: "task-1",
      draft_scenes: [{ title: "用户修订" }],
      confirmed: true,
    })
  })

  it("posts edited outline preview data to the explicit apply endpoint", async () => {
    mockJsonResponse({ status: "applied", total_threads: 1, total_arcs: 0, total_scenes: 0 })

    await window.api.outline.applyStructurePreview({
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      source_task_id: "task-1",
      draft_structure: { threads: [{ name: "用户修订" }] },
      confirmed: true,
    })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/outline/generate/apply")
    expect(JSON.parse(init.body)).toMatchObject({
      source_task_id: "task-1",
      draft_structure: { threads: [{ name: "用户修订" }] },
      confirmed: true,
    })
  })
})
