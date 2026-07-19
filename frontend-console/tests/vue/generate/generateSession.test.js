import { beforeEach, describe, expect, it, vi } from "vitest"
import { generateSessionKey, readGenerateSession, serializeGenerateSession, writeGenerateSession } from "../../../vue/views/generate/generateSession.js"

beforeEach(() => localStorage.clear())

describe("generate Vue bounded session", () => {
  it("isolates project, source page, and target", () => {
    expect(generateSessionKey("p1", "page-1", "world_bible_page")).toBe("generate_world_workspace_state_v2_p1_page-1_world_bible_page")
    expect(generateSessionKey("p2", null, "core_entity")).not.toBe(generateSessionKey("p1", null, "core_entity"))
  })

  it("uses UTF-8 bytes and never overwrites a valid snapshot with oversized data", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧" }] }))
    expect(serializeGenerateSession({ messages: [{ role: "user", content: "界".repeat(180_000) }] }).serialized).toBeNull()
    expect(writeGenerateSession(key, { messages: [{ role: "user", content: "界".repeat(180_000) }] })).toBe(false)
    expect(localStorage.getItem(key)).toContain("旧")
  })

  it("drops corrupted state and reports a visible warning", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, "{broken")
    const notify = vi.fn()
    expect(readGenerateSession(key, { notify }).messages).toEqual([])
    expect(localStorage.getItem(key)).toBeNull()
    expect(notify).toHaveBeenCalledWith("invalid-state", expect.stringContaining("已损坏"))
  })

  it("evicts the oldest generate snapshot and retries after a quota error", () => {
    const values = new Map([
      [generateSessionKey("old-1"), JSON.stringify({ savedAt: 1, messages: [] })],
      [generateSessionKey("old-2"), JSON.stringify({ savedAt: 2, messages: [] })],
    ])
    const target = generateSessionKey("current")
    let failOnce = true
    const storage = {
      get length() { return values.size },
      key: (index) => [...values.keys()][index] ?? null,
      getItem: (key) => values.get(key) ?? null,
      removeItem: (key) => values.delete(key),
      setItem(key, value) {
        if (key === target && failOnce) {
          failOnce = false
          throw new DOMException("quota", "QuotaExceededError")
        }
        values.set(key, value)
      },
    }
    const notify = vi.fn()

    expect(writeGenerateSession(target, { messages: [] }, { storage, notify })).toBe(true)
    expect(values.has(generateSessionKey("old-1"))).toBe(false)
    expect(values.has(generateSessionKey("old-2"))).toBe(true)
    expect(values.has(target)).toBe(true)
    expect(notify).toHaveBeenCalledWith("evicted", expect.stringContaining("最久未使用"))
  })

  it("keeps at most five project snapshots after a successful save", () => {
    for (let index = 1; index <= 5; index += 1) {
      localStorage.setItem(generateSessionKey(`p${index}`), JSON.stringify({ savedAt: index, messages: [] }))
    }
    const notify = vi.fn()

    expect(writeGenerateSession(generateSessionKey("p6"), { messages: [] }, { notify })).toBe(true)
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((key) => key?.startsWith("generate_world_workspace_state_v2_"))
    expect(keys).toHaveLength(5)
    expect(localStorage.getItem(generateSessionKey("p1"))).toBeNull()
    expect(localStorage.getItem(generateSessionKey("p6"))).not.toBeNull()
    expect(notify).toHaveBeenCalledWith("evicted", expect.any(String))
  })
})
