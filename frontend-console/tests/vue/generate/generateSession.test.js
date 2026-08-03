import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  generateSessionKey,
  readGenerateContextPreview,
  readGenerateSession,
  serializeGenerateSession,
  writeGenerateContextPreview,
  writeGenerateSession,
} from "../../../vue/views/generate/generateSession.js"

const pageProposalDraft = {
  schemaVersion: 1,
  suggestionId: "suggestion-1",
  editor: { title: "作者标题", pageType: "custom", freeText: "概览", sectionsText: "[{\"title\":\"章节\"}]", assetsText: "[]" },
}

beforeEach(() => localStorage.clear())

describe("generate Vue bounded session", () => {
  it("isolates project, source page, and target", () => {
    expect(generateSessionKey("p1", "page-1", "world_bible_page")).toBe("generate_world_workspace_state_v2_p1_page-1_world_bible_page")
    expect(generateSessionKey("p2", null, "core_entity")).not.toBe(generateSessionKey("p1", null, "core_entity"))
  })

  it("上下文预览跨目标保留且按项目隔离", () => {
    writeGenerateContextPreview("p1", { bundle: { sections: [{ key: "world" }] }, markdown: "# 预览", source: "task", request: { task: "检查" } })
    expect(readGenerateContextPreview("p1")).toMatchObject({ markdown: "# 预览", source: "task" })
    expect(readGenerateContextPreview("p2")).toEqual({ bundle: null, markdown: "", source: null, request: null })
  })

  it("round-trips a suggestion-bound page proposal draft while old v2 sessions remain compatible", () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    expect(writeGenerateSession(key, { ...readGenerateSession(key), suggestionId: "suggestion-1", pageProposalDraft })).toBe(true)
    expect(readGenerateSession(key).pageProposalDraft).toEqual(pageProposalDraft)

    localStorage.setItem(generateSessionKey("old"), JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧会话" }] }))
    expect(readGenerateSession(generateSessionKey("old"))).toMatchObject({ messages: [{ role: "user", content: "旧会话" }], pageProposalDraft: null })
  })

  it("drops only a malformed proposal draft and keeps the rest of the session with one warning", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "保留的对话" }], suggestionId: "suggestion-1", pageProposalDraft: { schemaVersion: 9 } }))
    const notify = vi.fn()

    expect(readGenerateSession(key, { notify })).toMatchObject({ messages: [{ role: "user", content: "保留的对话" }], suggestionId: "suggestion-1", pageProposalDraft: null })
    expect(notify).toHaveBeenCalledWith("invalid-page-proposal-draft", expect.stringContaining("无法恢复"))
    expect(JSON.parse(localStorage.getItem(key)).pageProposalDraft).toBeNull()
  })

  it("uses UTF-8 bytes and never overwrites a valid snapshot with oversized data", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧" }] }))
    expect(serializeGenerateSession({ messages: [{ role: "user", content: "界".repeat(180_000) }] }).serialized).toBeNull()
    expect(writeGenerateSession(key, { messages: [{ role: "user", content: "界".repeat(180_000) }] })).toBe(false)
    expect(localStorage.getItem(key)).toContain("旧")
  })

  it("does not overwrite a valid snapshot when the proposal draft alone exceeds the bound", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧快照" }] }))
    const tooLargeDraft = { ...pageProposalDraft, editor: { ...pageProposalDraft.editor, sectionsText: "界".repeat(180_000) } }

    expect(writeGenerateSession(key, { messages: [], pageProposalDraft: tooLargeDraft })).toBe(false)
    expect(localStorage.getItem(key)).toContain("旧快照")
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
