import { afterEach, describe, expect, it, vi } from "vitest"

import "../apiContracts.js"
import "../api.js"

function sseResponse(frame = "event: done\ndata: {\"status\":\"completed\"}\n\n") {
  const bytes = new TextEncoder().encode(frame)
  let read = false
  return {
    ok: true,
    body: {
      getReader() {
        return {
          async read() {
            if (read) return { done: true }
            read = true
            return { done: false, value: bytes }
          },
          releaseLock: vi.fn(),
        }
      },
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  globalThis.publicDemoMode = false
  globalThis.publicDemoRpMode = false
  document.cookie = "aaw_csrf=; Max-Age=0"
})

describe("公开演示 API 边界", () => {
  it("只给只读工作台 GET 附加 demo=1", async () => {
    const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ id: "demo-project" }) }))
    vi.stubGlobal("fetch", fetch)
    globalThis.publicDemoMode = true

    await globalThis.api.projects.get("demo-project", { cache: "no-store" })

    expect(fetch.mock.calls[0][0]).toBe("/api/projects/demo-project?demo=1")
    expect(fetch.mock.calls[0][1].method || "GET").toBe("GET")
  })

  it("给白名单中的只读检索 POST 附加 demo=1", async () => {
    const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ hits: [] }) }))
    vi.stubGlobal("fetch", fetch)
    globalThis.publicDemoMode = true

    await globalThis.api.context.searchEvidence({ novel_id: "demo-project", query: "雾港" })

    expect(fetch.mock.calls[0][0]).toBe("/api/evidence/compilation/evidence/search?demo=1")
    expect(fetch.mock.calls[0][1].method).toBe("POST")
  })

  it("匿名 direct stream 才携带临时 DeepSeek Key，且不附加工作台 demo query", async () => {
    document.cookie = "aaw_csrf=csrf-token"
    const fetch = vi.fn(async () => sseResponse())
    vi.stubGlobal("fetch", fetch)
    globalThis.publicDemoMode = true
    globalThis.publicDemoRpMode = true

    const events = []
    for await (const event of globalThis.api.interactions.streamDemoAttempt("journey-1", "attempt-1", "temporary-key")) {
      events.push(event)
    }

    expect(events).toEqual([{ event: "done", id: null, data: { status: "completed" } }])
    expect(fetch.mock.calls[0][0]).toBe("/api/interactions/journeys/journey-1/attempts/attempt-1/stream")
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST" })
    expect(fetch.mock.calls[0][1].headers).toMatchObject({
      "X-DeepSeek-API-Key": "temporary-key",
      "X-CSRF-Token": "csrf-token",
    })
  })

  it("只读工作台的可选接口 401 不触发账号失效或清除临时 Key", async () => {
    sessionStorage.setItem("ephemeralDeepSeekKey", "keep-until-session-ends")
    const fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ auth_mode: "public" }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Authentication required" }),
      })
    vi.stubGlobal("fetch", fetch)
    await globalThis.api.auth.config()
    globalThis.publicDemoMode = true

    await expect(globalThis.api.world.listSuggestions({ novel_id: "demo-project" }))
      .rejects.toMatchObject({ status: 401 })

    expect(sessionStorage.getItem("ephemeralDeepSeekKey")).toBe("keep-until-session-ends")
  })
})
