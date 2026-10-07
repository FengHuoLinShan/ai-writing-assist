import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  RECOMPUTE_SCOPES,
  clearRecomputeReceiptsForTests,
  driftRowLabel,
  listRecomputeReceipts,
  normalizeInvalidationNotice,
  normalizeRecomputeDriftContext,
  normalizeRecomputeOutcome,
  normalizeRecomputePreview,
  recomputeAdoptPayload,
  recomputeConflictKind,
  recomputeOperationKey,
  recomputeRequestPayload,
  rememberRecomputeReceipt,
} from "../../../vue/views/writing/invalidationModel.js"

function invalidationView(overrides = {}) {
  return {
    novel_id: "p1",
    chapter_index: 3,
    changed: true,
    nothing_to_do: false,
    affected: [
      {
        consumer: "story_scene_checkpoint",
        scene_id: "scene-1",
        scene_index: 4,
        dimension: "entities",
        reason: "anchored_chapter_edited",
        basis: "known",
        note: "这一章被编辑",
      },
      {
        consumer: "story_scene_checkpoint",
        scene_id: null,
        scene_index: 5,
        dimension: null,
        reason: "conservative_expansion_unregistered",
        basis: "unknown",
        note: "场景 #5 无消费登记，按保守扩大失效",
      },
    ],
    unknown_scope: true,
    receipt_id: "receipt-abc",
    invalidated: [{ consumer: "evidence_chapter_index", label: "章节证据索引", detail: "requested_hash=x" }],
    unsupported: [{ consumer: "world_knowledge", reason: "尚未接线" }],
    coverage_note: "细粒度依赖登记后可收窄",
    recompute_options: [
      { kind: "reload_evidence", covers: ["evidence_chapter_index"] },
      { kind: "rebuild_derived_state", covers: ["story_scene_projections"] },
      { kind: "regenerate_prose", covers: ["prose_generation"] },
    ],
    diagnostics: { earliest_affected_scene_index: 4, source_change: null, untranslated_consumers: [] },
    ...overrides,
  }
}

describe("normalizeInvalidationNotice", () => {
  it("无失效信息时保持零打扰（null）", () => {
    expect(normalizeInvalidationNotice(null)).toBeNull()
    expect(normalizeInvalidationNotice(undefined)).toBeNull()
    expect(normalizeInvalidationNotice("text")).toBeNull()
    expect(normalizeInvalidationNotice([])).toBeNull()
    expect(normalizeInvalidationNotice({ nothing_to_do: true })).toBeNull()
    expect(normalizeInvalidationNotice({ affected: [], unknown_scope: false, invalidated: [], unsupported: [] })).toBeNull()
  })

  it("unknown_scope 为真即使无条目也提示待核实", () => {
    const notice = normalizeInvalidationNotice({ unknown_scope: true, receipt_id: "r1", chapter_index: 2 })
    expect(notice).not.toBeNull()
    expect(notice.hasUnknownScope).toBe(true)
    expect(notice.unknownScopeNote).toContain("待核实")
  })

  it("投影作者语言条目与徽章口径", () => {
    const notice = normalizeInvalidationNotice(invalidationView(), { chapterIndex: 9 })
    expect(notice.entries).toHaveLength(2)
    expect(notice.entries[0]).toMatchObject({
      consumerLabel: "场景状态存档",
      scopeLabel: "场景 4",
      reasonLabel: "依赖的这一章被修改",
      basis: "known",
    })
    expect(notice.entries[1]).toMatchObject({
      scopeLabel: "场景 5",
      reasonLabel: "依赖未登记，按保守方式标记",
      basis: "unknown",
    })
    expect(notice.invalidatedLabels).toEqual(["章节证据索引"])
    expect(notice.unsupportedLabels).toEqual(["世界书理解"])
    expect(notice.coverageNote).toBe("细粒度依赖登记后可收窄")
    expect(notice.receiptId).toBe("receipt-abc")
    expect(notice.chapterIndex).toBe(3)
    expect(notice.sceneIndexes).toEqual([4, 5])
    expect(notice.earliestSceneIndex).toBe(4)
  })

  it("缺章号时回退到保存章生成标题，未知消费者不冒充翻译", () => {
    const notice = normalizeInvalidationNotice(invalidationView({ chapter_index: undefined }), { chapterIndex: 7 })
    expect(notice.chapterIndex).toBe(7)
    expect(notice.headline).toContain("第 7 章起的场景状态需要更新")
    expect(notice.headline).toContain("场景 4、5")
    const raw = normalizeInvalidationNotice({
      affected: [{ consumer: "mystery_consumer", reason: "weird_reason", basis: "known" }],
      receipt_id: "r2",
      chapter_index: 1,
    })
    expect(raw.entries[0].consumerLabel).toBe("相关内容")
    expect(raw.entries[0].reasonLabel).toBe("依赖这次修改")
  })

  it("响应缺 recompute_options 时默认列三分类", () => {
    const notice = normalizeInvalidationNotice(invalidationView({ recompute_options: undefined }))
    expect(notice.recomputeOptions).toEqual(["reload_evidence", "rebuild_derived_state", "regenerate_prose"])
  })
})

describe("重算请求体（对齐 WritingRecomputeRequest，extra=forbid）", () => {
  const notice = () => normalizeInvalidationNotice(invalidationView())

  it("基础体只含五个白名单字段；rebuild 以场景锚为目标并带基线回执指纹", () => {
    const payload = recomputeRequestPayload({
      novelId: "p1",
      scope: "rebuild_derived_state",
      notice: notice(),
      operationId: "op-1",
    })
    expect(payload).toEqual({
      novel_id: "p1",
      operation_id: "op-1",
      scope: "rebuild_derived_state",
      targets: [{ scene_index: 4 }, { scene_index: 5 }],
      baseline_receipt_digest: "receipt-abc",
    })
    expect("mode" in payload).toBe(false)
    expect("confirmed" in payload).toBe(false)
  })

  it("reload_evidence 与 regenerate_prose 锚定章", () => {
    const base = { novelId: "p1", notice: notice(), operationId: "op-2" }
    expect(recomputeRequestPayload({ ...base, scope: "reload_evidence" }).targets).toEqual([{ chapter_index: 3 }])
    expect(recomputeRequestPayload({ ...base, scope: "regenerate_prose" }).targets).toEqual([{ chapter_index: 3 }])
  })

  it("adopt 体在基础体上仅加 confirmed 与预览来源指纹", () => {
    const payload = recomputeAdoptPayload({
      novelId: "p1",
      scope: "reload_evidence",
      notice: notice(),
      operationId: "op-3",
      expectedSourceDigest: "digest-xyz",
    })
    expect(payload).toEqual({
      novel_id: "p1",
      operation_id: "op-3",
      scope: "reload_evidence",
      targets: [{ chapter_index: 3 }],
      baseline_receipt_digest: "receipt-abc",
      confirmed: true,
      expected_source_digest: "digest-xyz",
    })
    expect(recomputeAdoptPayload({
      novelId: "p1",
      scope: "reload_evidence",
      notice: notice(),
      operationId: "op-4",
    }).expected_source_digest).toBeNull()
  })

  it("缺章号、未知分类或缺幂等键时拒绝组装；无场景条目的 rebuild 回退章锚", () => {
    const noChapter = normalizeInvalidationNotice(invalidationView({ chapter_index: undefined }))
    expect(recomputeRequestPayload({ novelId: "p1", scope: "reload_evidence", notice: noChapter, operationId: "op" })).toBeNull()
    expect(recomputeRequestPayload({ novelId: "p1", scope: "nope", notice: notice(), operationId: "op" })).toBeNull()
    expect(recomputeRequestPayload({ novelId: "p1", scope: "reload_evidence", notice: notice() })).toBeNull()
    expect(recomputeRequestPayload({ scope: "reload_evidence", notice: notice(), operationId: "op" })).toBeNull()
    const chapterOnly = normalizeInvalidationNotice({
      affected: [{ consumer: "evidence_chapter_index", reason: "anchored_chapter_edited", basis: "known" }],
      invalidated: [{ consumer: "evidence_chapter_index", label: "章节证据索引" }],
      receipt_id: "r3",
      chapter_index: 2,
    })
    expect(recomputeRequestPayload({
      novelId: "p1",
      scope: "rebuild_derived_state",
      notice: chapterOnly,
      operationId: "op-5",
    }).targets).toEqual([{ chapter_index: 2 }])
  })
})

function previewResponse(overrides = {}) {
  return {
    novel_id: "p1",
    operation_id: "op-1",
    request_hash: "hash",
    scope: "reload_evidence",
    targets: [{ chapter_index: 3 }],
    cost: "低：仅重新读取证据/重建章索引，不调用模型、不改状态",
    write_effect: "替换章索引/证据缓存；不触碰 Scene 状态与正文",
    covers: ["evidence_chapter_index"],
    executable: true,
    actions: [
      { action: "reload_evidence", chapter_index: 3, detail: "以当前工作稿重新读取第 3 章证据并重建章索引" },
    ],
    affected: [{ consumer: "evidence_chapter_index", basis: "known", chapter_index: 3, note: "章索引确定性重建" }],
    baseline_receipt_digest: "receipt-abc",
    source_digest: "digest-xyz",
    source_state: {
      chapters: {
        3: { draft_id: "d1", version_number: 4, content_hash: "f".repeat(64) },
      },
    },
    domain_write_performed: false,
    ...overrides,
  }
}

describe("预览投影（WritingRecomputePreviewResponse）", () => {
  it("消费动作清单、可执行标记、来源指纹与来源状态", () => {
    const preview = normalizeRecomputePreview(previewResponse())
    expect(preview).toMatchObject({
      scope: "reload_evidence",
      label: "重读证据",
      executable: true,
      targets: ["第 3 章"],
      sourceDigest: "digest-xyz",
    })
    expect(preview.actions).toHaveLength(1)
    expect(preview.actions[0]).toMatchObject({ anchorLabel: "第 3 章", detail: expect.stringContaining("第 3 章证据") })
    expect(preview.sourceChapters["3"]).toEqual({ version: 4, fingerprint: "f".repeat(64) })
  })

  it("regenerate_prose 预览 executable=false；缺字段回退本地文案", () => {
    const raw = previewResponse({
      scope: "regenerate_prose",
      targets: [{ chapter_index: 3 }],
      executable: false,
      cost: "",
      write_effect: "",
    })
    const preview = normalizeRecomputePreview(raw)
    expect(preview.executable).toBe(false)
    expect(preview.costNote).toContain("成本高")
    expect(normalizeRecomputePreview({ scope: "mystery" })).toBeNull()
    expect(normalizeRecomputePreview(null)).toBeNull()
  })
})

describe("执行回执与本地会话回执记录", () => {
  beforeEach(() => clearRecomputeReceiptsForTests())
  afterEach(() => clearRecomputeReceiptsForTests())

  it("回执投影为作者语言结果（无 replayed 字段口径）", () => {
    const outcome = normalizeRecomputeOutcome({
      operation_id: "op-1",
      scope: "reload_evidence",
      confirmed: true,
      domain_write_performed: true,
      results: { "chapter:3": { action: "reload_evidence" }, "chapter:4": { action: "reload_evidence" } },
    })
    expect(outcome).toMatchObject({ label: "重读证据", domainWritePerformed: true, handledCount: 2 })
    expect("replayed" in outcome).toBe(false)
  })

  it("本地回执按 novel 隔离、按 operation_id 去重", () => {
    const outcome = { operationId: "op-1", label: "重读证据", scope: "reload_evidence", domainWritePerformed: true, handledCount: 1 }
    rememberRecomputeReceipt("p1", outcome, { at: "2026-10-07T10:00:00Z" })
    rememberRecomputeReceipt("p1", outcome, { at: "2026-10-07T11:00:00Z" })
    rememberRecomputeReceipt("p2", outcome)
    const items = listRecomputeReceipts("p1")
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ key: "op-1", label: "重读证据", rememberedAt: "2026-10-07T10:00:00Z" })
    expect(listRecomputeReceipts("p2")).toHaveLength(1)
    expect(listRecomputeReceipts("p3")).toHaveLength(0)
  })
})

describe("冲突分类与漂移可比较数据", () => {
  it("409 + recompute_source_drift / recompute_scope_unsupported / 兼容旧码分类", () => {
    expect(recomputeConflictKind({ status: 409, body: { error: "recompute_source_drift" } })).toBe("source_drift")
    expect(recomputeConflictKind({ status: 409, body: { error: "recompute_scope_unsupported" } })).toBe("scope_unsupported")
    expect(recomputeConflictKind({ status: 409, code: "SOURCE_STALE" })).toBe("source_drift")
    expect(recomputeConflictKind({ status: 409, body: { error: "conflict" } })).toBeNull()
    expect(recomputeConflictKind({ status: 500 })).toBeNull()
    expect(recomputeConflictKind(null)).toBeNull()
  })

  it("漂移 context 逐章比较预览时与当前版本", () => {
    const error = {
      status: 409,
      body: {
        error: "recompute_source_drift",
        detail: "重算目标章节在预览后已再次修改",
        context: {
          expected_source_digest: "old",
          current_source_digest: "new",
          keep_current_draft: true,
          current: {
            3: { draft_id: "d1", version_number: 5, content_hash: "a".repeat(64) },
            4: { draft_id: null, version_number: null, content_hash: null },
          },
        },
      },
    }
    const drift = normalizeRecomputeDriftContext(error, {
      previewChapters: {
        3: { version: 4, fingerprint: "f".repeat(64) },
        5: { version: 2, fingerprint: "0".repeat(64) },
      },
    })
    expect(drift.keepCurrentDraft).toBe(true)
    expect(drift.rows).toHaveLength(3)
    expect(drift.rows.map((row) => driftRowLabel(row))).toEqual([
      "第 3 章：预览时第 4 版 → 当前第 5 版",
      "第 4 章：版本信息暂缺",
      "第 5 章：预览时为第 2 版工作稿，当前版本暂缺",
    ])
  })

  it("版本与指纹都未变时标记 unchanged；无预览状态时退化为当前清单", () => {
    const same = "f".repeat(64)
    const error = {
      status: 409,
      body: { error: "recompute_source_drift", context: { current: { 3: { version_number: 4, content_hash: same } } } },
    }
    const drift = normalizeRecomputeDriftContext(error, { previewChapters: { 3: { version: 4, fingerprint: same } } })
    expect(drift.rows[0].unchanged).toBe(true)
    expect(driftRowLabel(drift.rows[0])).toBe("第 3 章：版本未变（第 4 版）")
    const noPreview = normalizeRecomputeDriftContext(error, {})
    expect(driftRowLabel(noPreview.rows[0])).toBe("第 3 章：当前为第 4 版工作稿")
  })
})

describe("recomputeOperationKey", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("randomUUID 优先，无 Web Crypto 时失败关闭", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" })
    expect(recomputeOperationKey()).toBe("recompute-00000000-0000-4000-8000-000000000001")
    vi.stubGlobal("crypto", {})
    expect(() => recomputeOperationKey()).toThrow("当前浏览器无法安全生成操作标识")
  })
})

describe("RECOMPUTE_SCOPES 三分类文案", () => {
  it("三分类按成本升序且 regenerate_prose 声明仅作者显式选择", () => {
    expect(RECOMPUTE_SCOPES.map((scope) => scope.kind)).toEqual(["reload_evidence", "rebuild_derived_state", "regenerate_prose"])
    expect(RECOMPUTE_SCOPES[2].costNote).toContain("只在你的明确选择下执行")
    expect(RECOMPUTE_SCOPES[0].effectNote).toContain("不会变")
    expect(RECOMPUTE_SCOPES[1].effectNote).toContain("保留")
  })
})
