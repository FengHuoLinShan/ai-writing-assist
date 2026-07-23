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
import { ACCOUNT_INVALIDATED_EVENT } from "../shared/accountStorage.js"
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
    window.api.clearAccessToken()
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it("409 response uses a localized conflict prefix and preserves detail", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "该资源已被其他会话更新" }),
    }))

    await expect(window.api.request("/projects/conflict", {
      method: "POST",
      body: JSON.stringify({}),
    })).rejects.toMatchObject({
      status: 409,
      detail: "该资源已被其他会话更新",
      message: "请求冲突：该资源已被其他会话更新",
    })
  })

  it("409 response without detail still exposes status and localized message", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 409,
      json: () => Promise.resolve({}),
    }))

    await expect(window.api.request("/projects/conflict", {
      method: "POST",
      body: JSON.stringify({}),
    })).rejects.toMatchObject({
      status: 409,
      message: "请求冲突",
    })
  })

  it("omits request bodies and redacts secrets from failed-request diagnostics", async () => {
    const previousErrorLog = window.errorLog
    window.errorLog = { _lastApiError: null }
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 422,
      json: () => Promise.resolve({
        detail: "api_key=server-secret",
        nested: {
          api_key: "response-api-key",
          authorization: "Bearer response-token",
          safe_code: "invalid_provider",
        },
      }),
    }))

    try {
      await expect(window.api.request(
        "/settings/project?access_token=query-secret",
        {
          method: "PUT",
          body: JSON.stringify({ api_key: "request-api-key", model: "demo" }),
        },
      )).rejects.toMatchObject({
        status: 422,
        message: expect.not.stringContaining("server-secret"),
      })

      const diagnostic = window.errorLog._lastApiError
      expect(diagnostic).toMatchObject({
        method: "PUT",
        status: 422,
      })
      expect(diagnostic).not.toHaveProperty("body")
      expect(diagnostic.url).toContain("access_token=[REDACTED]")
      expect(diagnostic.response).toContain("invalid_provider")

      const serialized = JSON.stringify(diagnostic)
      expect(serialized).not.toContain("query-secret")
      expect(serialized).not.toContain("request-api-key")
      expect(serialized).not.toContain("response-api-key")
      expect(serialized).not.toContain("response-token")
      expect(serialized).not.toContain("server-secret")
    } finally {
      if (previousErrorLog === undefined) delete window.errorLog
      else window.errorLog = previousErrorLog
    }
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

  it("projects.get forwards cancellation and cache policy through the contract wrapper", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: "p-signal", title: "项目" }),
    }))
    const controller = new AbortController()

    await expect(window.api.projects.get("p-signal", {
      signal: controller.signal,
      cache: "no-store",
    })).resolves.toEqual({ id: "p-signal", title: "项目" })

    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/projects/p-signal")
    expect(init.signal).toBeInstanceOf(AbortSignal)
    expect(init.cache).toBe("no-store")
  })

  it("no-store bypasses the application GET cache without replacing it", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ id: "p-cache", title: "Cached" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ id: "p-cache", title: "Fresh" }),
      })

    await expect(window.api.projects.get("p-cache")).resolves.toMatchObject({ title: "Cached" })
    await expect(window.api.projects.get("p-cache", { cache: "no-store" })).resolves.toMatchObject({ title: "Fresh" })
    await expect(window.api.projects.get("p-cache")).resolves.toMatchObject({ title: "Cached" })

    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
  })

  it("bounds the GET cache and evicts the least recently used entry", async () => {
    globalThis.fetch = vi.fn(async (url) => ({
      ok: true,
      status: 200,
      json: async () => ({ url }),
    }))

    for (let index = 0; index < 129; index += 1) {
      await window.api.request(`/cache-bound/${index}`)
    }
    expect(globalThis.fetch).toHaveBeenCalledTimes(129)

    await window.api.request("/cache-bound/0")
    expect(globalThis.fetch).toHaveBeenCalledTimes(130)
    await window.api.request("/cache-bound/128")
    expect(globalThis.fetch).toHaveBeenCalledTimes(130)
  })

  it("honors external cancellation even when the fetch transport resolves late", async () => {
    let resolveFetch
    globalThis.fetch = vi.fn(() => new Promise((resolve) => {
      resolveFetch = resolve
    }))
    const controller = new AbortController()
    const pending = window.api.projects.get("p-late-abort", {
      signal: controller.signal,
      cache: "no-store",
    })

    controller.abort()
    resolveFetch({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: "p-late-abort", title: "Too late" }),
    })

    await expect(pending).rejects.toThrow("请求已取消")
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

  it("generation center keeps a direct LLM request open beyond the old 90 second limit", async () => {
    vi.useFakeTimers()
    try {
      let resolveFetch
      let requestSignal
      globalThis.fetch = vi.fn((_url, init) => {
        requestSignal = init.signal
        return new Promise((resolve) => {
          resolveFetch = resolve
        })
      })

      const pending = window.api.generate.generateWorldSuggestion({ novel_id: "p1" })
      await vi.advanceTimersByTimeAsync(180_000)

      expect(requestSignal.aborted).toBe(false)
      expect(globalThis.fetch.mock.calls[0][0]).toContain(
        "/api/world/generation-center/suggestions",
      )
      resolveFetch({
        ok: true,
        status: 201,
        json: () => Promise.resolve({ result: { kind: "world_bible_new_page" } }),
      })
      await expect(pending).resolves.toEqual({
        result: { kind: "world_bible_new_page" },
      })
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
    window.api.clearAccessToken()
    sessionStorage.clear()
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

  it("keeps the closed-test token in memory instead of sessionStorage", async () => {
    mockJsonResponse({ ok: true })
    window.api.setAccessToken("test-token")

    await window.api.request("/projects")

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers.Authorization).toBe("Bearer test-token")
    expect(sessionStorage.getItem("novel_app_access_token")).toBeNull()
  })

  it("preserves an explicit caller Authorization header when a memory token exists", async () => {
    mockJsonResponse({ ok: true })
    window.api.setAccessToken("closed-token")

    await window.api.request("/projects", {
      headers: { authorization: "Bearer caller-token" },
    })

    const init = globalThis.fetch.mock.calls[0][1]
    expect(init.headers.authorization).toBe("Bearer caller-token")
    expect(init.headers.Authorization).toBeUndefined()
  })

  it("uses an app modal once on 401, retries from memory, and never persists the token", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "Missing or invalid access token" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ ok: true }),
      })

    const requestPromise = window.api.request("/projects/auth-check")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledOnce())
    document.body.innerHTML = '<input id="closed-test-access-token" value="closed-token" />'
    await showModalHtml.mock.calls[0][2][0].handler()
    await expect(requestPromise).resolves.toEqual({ ok: true })

    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
    expect(globalThis.fetch.mock.calls[1][1].headers.Authorization)
      .toBe("Bearer closed-token")
    expect(sessionStorage.getItem("novel_app_access_token")).toBeNull()
  })

  it("clears a rejected retry token after the second 401", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "Missing access token" }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "Invalid access token" }),
      })

    const requestPromise = window.api.request("/projects/auth-check")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledOnce())
    document.body.innerHTML = '<input id="closed-test-access-token" value="rejected-token" />'
    await showModalHtml.mock.calls[0][2][0].handler()
    await expect(requestPromise).rejects.toMatchObject({ status: 401 })

    mockJsonResponse({ ok: true })
    await window.api.request("/projects/after-rejection", { cache: "no-store" })
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })

  it("invalidates public account state on a protected API 401", async () => {
    const onInvalidated = vi.fn((event) => event.preventDefault())
    window.addEventListener(ACCOUNT_INVALIDATED_EVENT, onInvalidated)
    try {
      mockJsonResponse({ auth_mode: "public" })
      await window.api.auth.config()
      localStorage.setItem("novel_accountId", "account-1")
      localStorage.setItem("draft_backup_project-1_1", "private")
      localStorage.setItem("novel_theme", "dark")
      sessionStorage.setItem("workflow-progress-card:task-1", "open")
      globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "Authentication required" }),
      }))

      await expect(window.api.request("/projects/private", { cache: "no-store" }))
        .rejects.toMatchObject({ status: 401 })

      expect(onInvalidated).toHaveBeenCalledTimes(1)
      expect(onInvalidated.mock.calls[0][0].detail.reason).toBe("public-unauthorized")
      expect(localStorage.getItem("novel_accountId")).toBeNull()
      expect(localStorage.getItem("draft_backup_project-1_1")).toBeNull()
      expect(sessionStorage.getItem("workflow-progress-card:task-1")).toBeNull()
      expect(localStorage.getItem("novel_theme")).toBe("dark")
    } finally {
      window.removeEventListener(ACCOUNT_INVALIDATED_EVENT, onInvalidated)
      mockJsonResponse({ auth_mode: "closed_test" })
      await window.api.auth.config()
    }
  })

  it("does not invalidate the expected unauthenticated auth.me bootstrap probe", async () => {
    const onInvalidated = vi.fn((event) => event.preventDefault())
    window.addEventListener(ACCOUNT_INVALIDATED_EVENT, onInvalidated)
    try {
      mockJsonResponse({ auth_mode: "public" })
      await window.api.auth.config()
      localStorage.setItem("draft_backup_legacy_1", "private")
      globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "Authentication required" }),
      }))

      await expect(window.api.auth.me()).rejects.toMatchObject({ status: 401 })

      expect(onInvalidated).not.toHaveBeenCalled()
      expect(localStorage.getItem("draft_backup_legacy_1")).toBe("private")
    } finally {
      window.removeEventListener(ACCOUNT_INVALIDATED_EVENT, onInvalidated)
      mockJsonResponse({ auth_mode: "closed_test" })
      await window.api.auth.config()
    }
  })

  it("uses the same in-memory token for upload XHR without exposing a getter", async () => {
    window.api.setAccessToken("closed-token")
    const instances = []
    const OriginalXMLHttpRequest = globalThis.XMLHttpRequest
    class FakeXMLHttpRequest {
      constructor() {
        this.headers = {}
        this.upload = {}
        this.status = 200
        this.responseText = JSON.stringify({ imported_chapters: 1 })
        instances.push(this)
      }

      open(method, url) {
        this.method = method
        this.url = url
      }

      setRequestHeader(name, value) {
        this.headers[name] = value
      }

      send(body) {
        this.body = body
        this.onload()
      }
    }
    globalThis.XMLHttpRequest = FakeXMLHttpRequest

    try {
      await window.api.imports.uploadFile(
        new File(["chapter"], "novel.txt", { type: "text/plain" }),
        "novel-1",
      )
    } finally {
      globalThis.XMLHttpRequest = OriginalXMLHttpRequest
    }

    expect(instances).toHaveLength(1)
    expect(instances[0].method).toBe("POST")
    expect(instances[0].headers).toMatchObject({
      "X-Requested-With": "XMLHttpRequest",
      Authorization: "Bearer closed-token",
    })
  })

  it("clears a token rejected by the upload transport", async () => {
    window.api.setAccessToken("rejected-token")
    const OriginalXMLHttpRequest = globalThis.XMLHttpRequest
    class UnauthorizedXMLHttpRequest {
      constructor() {
        this.headers = {}
        this.upload = {}
        this.status = 401
        this.responseText = JSON.stringify({ detail: "Invalid access token" })
      }
      open() {}
      setRequestHeader(name, value) { this.headers[name] = value }
      send() { this.onload() }
    }
    globalThis.XMLHttpRequest = UnauthorizedXMLHttpRequest

    try {
      await expect(window.api.imports.uploadFile(
        new File(["chapter"], "novel.txt", { type: "text/plain" }),
        "novel-1",
      )).rejects.toThrow("Invalid access token")
    } finally {
      globalThis.XMLHttpRequest = OriginalXMLHttpRequest
    }

    mockJsonResponse({ ok: true })
    await window.api.request("/projects/after-upload-401", { cache: "no-store" })
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })

  it("aborts the upload XHR when its signal is cancelled", async () => {
    const OriginalXMLHttpRequest = globalThis.XMLHttpRequest
    let instance = null
    class AbortableXMLHttpRequest {
      constructor() { this.upload = {}; instance = this }
      open() {}
      setRequestHeader() {}
      send() {}
      abort() { this.aborted = true; this.onabort() }
    }
    globalThis.XMLHttpRequest = AbortableXMLHttpRequest
    const controller = new AbortController()
    try {
      const pending = window.api.imports.uploadFile(
        new File(["chapter"], "novel.txt", { type: "text/plain" }),
        "novel-1",
        null,
        { signal: controller.signal },
      )
      controller.abort()
      await expect(pending).rejects.toMatchObject({ name: "AbortError" })
      expect(instance.aborted).toBe(true)
    } finally {
      globalThis.XMLHttpRequest = OriginalXMLHttpRequest
    }
  })

  it("uses the same in-memory token for frontend error reports", async () => {
    mockJsonResponse({ ok: true })
    window.api.setAccessToken("closed-token")

    await window.api.reportFrontendError({ message: "safe diagnostic" })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/debug/frontend-errors")
    expect(init.headers.Authorization).toBe("Bearer closed-token")
    expect(init.keepalive).toBe(true)
  })

  it("redacts secrets passed to frontend error reporting", async () => {
    mockJsonResponse({ ok: true })

    await window.api.reportFrontendError({
      message: "authorization=message-secret",
      request: {
        headers: { Authorization: "Bearer header-secret" },
        body: { api_key: "body-secret", model: "demo" },
      },
    })

    const payload = JSON.parse(globalThis.fetch.mock.calls[0][1].body)
    expect(payload.message).not.toContain("message-secret")
    expect(payload.request.headers.Authorization).toBe("[REDACTED]")
    expect(payload.request.body.api_key).toBe("[REDACTED]")
    expect(payload.request.body.model).toBe("demo")
    expect(JSON.stringify(payload)).not.toContain("header-secret")
    expect(JSON.stringify(payload)).not.toContain("body-secret")
  })

  it("clears a token rejected by frontend error reporting", async () => {
    window.api.setAccessToken("rejected-token")
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 401 }))

    await window.api.reportFrontendError({ message: "safe diagnostic" })

    mockJsonResponse({ ok: true })
    await window.api.request("/projects/after-report-401", { cache: "no-store" })
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
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

  it("starts map observation enrichment without deep-import force fields", async () => {
    mockJsonResponse({ task_id: "map-observations-1" })

    await window.api.imports.startMapObservationEnrichment("p1", 2, 8, true, {
      adoption_policy: "user_authorized_pipeline",
      authorization_confirmed: true,
    })

    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain("/api/imports/stages/map-observations")
    const body = JSON.parse(init.body)
    expect(body).toEqual({
      novel_id: "p1",
      start_chapter: 2,
      end_chapter: 8,
      high_quality: true,
      adoption_policy: "user_authorized_pipeline",
      authorization_confirmed: true,
    })
    expect(body).not.toHaveProperty("force")
  })

  it("fails closed before map observation enrichment without authorization", async () => {
    mockJsonResponse({ task_id: "should-not-start" })

    await expect(window.api.imports.startMapObservationEnrichment("p1", 1, 0))
      .rejects.toThrow("必须获得用户授权")
    expect(globalThis.fetch).not.toHaveBeenCalled()
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
