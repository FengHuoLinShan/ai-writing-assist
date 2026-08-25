import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  CREATIVE_CONTINUATION_STORAGE_PREFIX,
  GENERATE_INTERRUPTED_CHAT_MESSAGE,
  clearCreativeContinuation,
  generateSessionKey,
  hasGenerateSession,
  normalizeConvergenceDraft,
  normalizeExternalPackets,
  normalizePovForm,
  normalizeTaskForm,
  normalizeVisualBrief,
  readCreativeContinuation,
  readGenerateContextPreview,
  readGenerateSession,
  serializeGenerateSession,
  writeCreativeContinuation,
  writeGenerateContextPreview,
  writeGenerateSession,
} from "../../../vue/views/generate/generateSession.js"

const pageProposalDraft = {
  schemaVersion: 1,
  suggestionId: "suggestion-1",
  editor: { title: "作者标题", pageType: "custom", freeText: "概览", sectionsText: "[{\"title\":\"章节\"}]", assetsText: "[]" },
}
const convergenceDraft = {
  schemaVersion: 1,
  manifestHash: "a".repeat(64),
  sourceSnapshot: { kind: "project" },
  stale: false,
  coverage: { complete: true, scopeLabel: "最近两条对话", sourceCount: 2, excludedMessageCount: 0, missingCount: 0, issues: [] },
  detailSummary: { before_grouping: 10, after_deduplication: 4, retained_in_sources: 2 },
  cards: [{ cardId: "C1", title: "制度边界", items: [{ itemId: "C1I1", text: "数字继续开放", disposition: "open" }], sourceRefs: [] }],
  nextBoundary: "人物选择改变时再扩展",
  authorMessage: "可编辑作者消息",
}
const visualBrief = {
  schemaVersion: 1,
  manifestHash: "a".repeat(64),
  sourceLabel: "白堤 · 已发布世界笔记",
  purpose: "overview",
  mustKeep: "保留三河汇流",
  exactLabels: "白堤",
  openItems: "邻城方向继续开放",
  avoid: "不要新增国界",
  createdAt: "2026-08-11T12:00:00.000Z",
  confirmedAt: null,
  stale: false,
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe("generate Vue bounded session", () => {
  it("isolates project, source page, and target", () => {
    expect(generateSessionKey("p1", "page-1", "world_bible_page")).toBe("generate_world_workspace_state_v2_p1_page-1_world_bible_page")
    expect(generateSessionKey("p2", null, "core_entity")).not.toBe(generateSessionKey("p1", null, "core_entity"))
    expect(generateSessionKey("p1", null, "core_entity", "world_core")).not.toBe(generateSessionKey("p1", null, "core_entity"))
  })

  it("round-trips a bounded task draft without leaking it across project keys", () => {
    const key = generateSessionKey("p1")
    const taskForm = normalizeTaskForm({
      task: "检查人物动机", scope: "chapter", entity_ids: ["e1"], character_ids: ["c1"],
      scene_id: "scene-1", chapter_index: 0, budget_tokens: 2_000_000,
      reveal_mode: "unknown", viewpoint_character_id: "c1", include_world_synopsis: false,
    })
    expect(writeGenerateSession(key, { messages: [], taskPreset: "conflict_check", taskForm })).toBe(true)
    expect(readGenerateSession(key)).toMatchObject({
      taskPreset: "conflict_check",
      taskForm: { task: "检查人物动机", scope: "chapter", chapter_index: null, budget_tokens: 1_000_000, reveal_mode: "author_safe", include_world_synopsis: false },
    })
    expect(readGenerateSession(generateSessionKey("p2")).taskForm.task).toBe("")
  })

  it("round-trips a bounded POV form without leaking it across project keys", () => {
    const key = generateSessionKey("p1")
    const povForm = normalizePovForm({ chapterIndex: "2", sceneId: "scene-1", viewpointCharacterId: "char-1", instruction: "保持克制" })

    expect(writeGenerateSession(key, { messages: [], povForm })).toBe(true)
    expect(readGenerateSession(key).povForm).toEqual({ chapterIndex: 2, sceneId: "scene-1", viewpointCharacterId: "char-1", instruction: "保持克制" })
    expect(readGenerateSession(generateSessionKey("p2")).povForm).toEqual({ chapterIndex: null, sceneId: "", viewpointCharacterId: "", instruction: "" })
  })

  it("上下文预览跨目标保留且按项目隔离", () => {
    writeGenerateContextPreview("p1", { bundle: { novel_id: "p1", sections: [{ key: "world" }] }, markdown: "# 预览", source: "task", request: { novel_id: "p1", task: "检查" } })
    expect(readGenerateContextPreview("p1")).toMatchObject({ markdown: "# 预览", source: "task" })
    expect(readGenerateContextPreview("p2")).toEqual({ bundle: null, markdown: "", source: null, request: null })
  })

  it("丢弃项目不匹配的会话预览", () => {
    const key = "generate_context_preview_v1:p1-cross"
    sessionStorage.setItem(key, JSON.stringify({ bundle: { novel_id: "p2" }, request: { novel_id: "p2" }, source: "task" }))
    expect(readGenerateContextPreview("p1-cross")).toEqual({ bundle: null, markdown: "", source: null, request: null })
    expect(sessionStorage.getItem(key)).toBeNull()
  })

  it("round-trips a suggestion-bound page proposal draft while old v2 sessions remain compatible", () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    expect(writeGenerateSession(key, { ...readGenerateSession(key), composer: "尚未发送的输入", selectedWorldPageIds: ["page-2"], suggestionId: "suggestion-1", pageProposalDraft })).toBe(true)
    expect(readGenerateSession(key)).toMatchObject({ composer: "尚未发送的输入", selectedWorldPageIds: ["page-2"], pageProposalDraft })

    localStorage.setItem(generateSessionKey("old"), JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "旧会话" }] }))
    expect(readGenerateSession(generateSessionKey("old"))).toMatchObject({ messages: [{ role: "user", content: "旧会话" }], pageProposalDraft: null })
  })

  it("round-trips a bounded convergence draft without source bodies", () => {
    const key = generateSessionKey("p1")
    expect(normalizeConvergenceDraft(convergenceDraft)).toBe(convergenceDraft)
    expect(writeGenerateSession(key, { messages: [{ role: "user", content: "原对话" }], convergenceDraft })).toBe(true)

    const restored = readGenerateSession(key)
    expect(restored.convergenceDraft).toEqual(convergenceDraft)
    expect(JSON.stringify(restored.convergenceDraft)).not.toContain("source body")
  })

  it("keeps one external return body plus a bounded, content-free packet history", () => {
    const key = generateSessionKey("p1")
    const record = {
      hash: "b".repeat(64), packetIndex: 2, packetTotal: 5, characterCount: 12,
      status: "previewed", previewedAt: 123, manifestHash: "c".repeat(64),
      sourceCount: 3, coveredSourceCount: 3,
      dispositionCounts: { compatible: 1, repair: 1, candidate: 0, unmapped: 0, exact_duplicate: 0 },
    }
    expect(writeGenerateSession(key, { messages: [], externalPacketDraft: "外部回包原文", externalPackets: [record, { hash: "bad" }] })).toBe(true)

    expect(readGenerateSession(key)).toMatchObject({ externalPacketDraft: "外部回包原文", externalPackets: [record] })
    expect(normalizeExternalPackets(Array.from({ length: 25 }, (_, index) => ({ ...record, hash: index.toString(16).padStart(64, "0"), packetIndex: index + 1, packetTotal: null })))).toHaveLength(20)
    expect(JSON.stringify(readGenerateSession(key).externalPackets)).not.toContain("外部回包原文")
    expect(normalizeExternalPackets([{ ...record, status: "exact_duplicate", packetIndex: 3 }])[0].status).toBe("exact_duplicate")
  })

  it("round-trips one bounded local visual brief and drops malformed purposes", () => {
    const key = generateSessionKey("p1")
    expect(normalizeVisualBrief(visualBrief)).toEqual(visualBrief)
    expect(writeGenerateSession(key, { messages: [], convergenceDraft, visualBrief })).toBe(true)
    expect(readGenerateSession(key).visualBrief).toEqual(visualBrief)

    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "保留" }], visualBrief: { ...visualBrief, purpose: "agent_decides" } }))
    const notify = vi.fn()
    expect(readGenerateSession(key, { notify })).toMatchObject({ messages: [{ role: "user", content: "保留" }], visualBrief: null })
    expect(notify).toHaveBeenCalledWith("invalid-visual-brief", expect.stringContaining("无法恢复"))
  })

  it("drops only a malformed convergence draft and keeps the conversation", () => {
    const key = generateSessionKey("p1")
    localStorage.setItem(key, JSON.stringify({ savedAt: 1, messages: [{ role: "user", content: "保留对话" }], convergenceDraft: { schemaVersion: 1, manifestHash: "x", stale: false, authorMessage: "", cards: [{ cardId: "C1", title: "坏卡片", items: [] }] } }))
    const notify = vi.fn()

    expect(readGenerateSession(key, { notify })).toMatchObject({ messages: [{ role: "user", content: "保留对话" }], convergenceDraft: null })
    expect(notify).toHaveBeenCalledWith("invalid-convergence-draft", expect.stringContaining("无法恢复"))
  })

  it("compacts only rebuildable convergence detail before dropping author choices", () => {
    const key = generateSessionKey("p1")
    const notify = vi.fn()
    const large = {
      ...convergenceDraft,
      cards: [{
        ...convergenceDraft.cards[0],
        commonGround: ["展开说明".repeat(140_000)],
        dependencies: ["依赖说明".repeat(140_000)],
        sourceRefs: [{ key: "m1", label: "对话来源", sourceRef: { source_type: "author_message" } }],
      }],
    }

    expect(writeGenerateSession(key, { messages: [], convergenceDraft: large }, { notify })).toBe(true)
    const restored = readGenerateSession(key)
    expect(restored.convergenceDraft.cards[0]).toMatchObject({
      commonGround: [], dependencies: [],
      items: [{ itemId: "C1I1", text: "数字继续开放", disposition: "open" }],
      sourceRefs: [{ key: "m1", label: "对话来源", sourceRef: { source_type: "author_message" } }],
    })
    expect(restored.convergenceDraft.authorMessage).toBe("可编辑作者消息")
    expect(notify).toHaveBeenCalledWith("compacted-convergence", expect.stringContaining("来源、选择和作者消息"))
  })

  it("stores only an allowlisted project route and drops invalid or evicted continuations", () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    writeGenerateSession(key, { composer: "继续白堤校验", messages: [] })
    expect(writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: "page-1", target: "world_bible_page", ignored: "不会持久化" },
    }, { now: () => 123 })).toBe(true)
    expect(readCreativeContinuation("p1")).toEqual({
      schema_version: 1,
      project_id: "p1",
      destination: "generate",
      route: { source_page_id: "page-1", target: "world_bible_page" },
      last_meaningful_at: 123,
    })
    expect(readCreativeContinuation("p2")).toBeNull()
    expect(hasGenerateSession(key)).toBe(true)

    localStorage.removeItem(key)
    expect(hasGenerateSession(key)).toBe(false)
    expect(clearCreativeContinuation("p1")).toBe(true)
    expect(localStorage.getItem(`${CREATIVE_CONTINUATION_STORAGE_PREFIX}p1`)).toBeNull()
    expect(writeCreativeContinuation("p1", { destination: "shell", route: {} })).toBe(false)
  })

  it("keeps a World Core preset and saved checkpoint in its continuation", () => {
    expect(writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: null, target: "core_entity", preset: "world_core", checkpoint_id: "checkpoint-1" },
    }, { now: () => 456 })).toBe(true)
    expect(readCreativeContinuation("p1")).toEqual({
      schema_version: 1,
      project_id: "p1",
      destination: "generate",
      route: { source_page_id: null, target: "core_entity", preset: "world_core", checkpoint_id: "checkpoint-1" },
      last_meaningful_at: 456,
    })
  })

  it("serializes a pending assistant as an interruption without mutating the live message", () => {
    const pending = { role: "assistant", content: "正在思考...", pending: true }
    const completed = { role: "assistant", content: "真实回复" }
    const result = serializeGenerateSession({ messages: [{ role: "user", content: "上一条" }, pending, completed] })

    expect(pending).toEqual({ role: "assistant", content: "正在思考...", pending: true })
    expect(JSON.parse(result.serialized).messages).toEqual([
      { role: "user", content: "上一条" },
      { role: "assistant", content: GENERATE_INTERRUPTED_CHAT_MESSAGE, error: true, interrupted: true },
      completed,
    ])
  })

  it("keeps the same byte bound when a large pending bubble is converted to interruption", () => {
    const result = serializeGenerateSession({ messages: [{ role: "assistant", content: "界".repeat(180_000), pending: true }] })

    expect(result.serialized).not.toBeNull()
    expect(JSON.parse(result.serialized).messages).toEqual([
      { role: "assistant", content: GENERATE_INTERRUPTED_CHAT_MESSAGE, error: true, interrupted: true },
    ])
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
