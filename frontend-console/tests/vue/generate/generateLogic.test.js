import { describe, expect, it } from "vitest"
import {
  buildPovInstruction, buildTaskPayload, buildVisualBriefMarkdown, buildWorldCoreCheckpointContext, buildWorldCoreCheckpointRequest, buildWorldDesignCheckpointRequest, buildWorldHandoffMarkdown, buildWorldPayload, compileConvergenceMessage,
  convergenceDraftFromCheckpoint, convergenceDraftFromResponse, convergenceSourceMatchesPayload, externalPacketBatchSummary, externalPacketCharacterCount, hashExternalPacket,
  parseExternalPacketPosition, sectionDiff, validateTaskPayload, visualBriefFromConvergence,
} from "../../../vue/views/generate/logic/generateLogic.js"

function worldCoreFixture() {
  return {
    coverage: { complete: true, scope_label: "一个灵感", source_count: 1, covered_source_keys: ["m1"], manifest_hash: "a".repeat(64) },
    manifest: [{ key: "m1", kind: "conversation", label: "作者灵感", content_hash: "1".repeat(64), source_ref: { source_type: "author_message", source_hash: "2".repeat(64) } }],
    detail_summary: { before_grouping: 3, after_deduplication: 3, retained_in_sources: 0 },
    decision_cards: [{
      card_id: "C1", title: "规则", common_ground: [], dependencies: [], affected_targets: ["current_world_target"], source_keys: ["m1"], why_now: "收拢",
      items: ["one", "two", "three"].map((key, index) => ({ item_id: `I${index + 1}`, text: `规则 ${index + 1}`, suggested_disposition: "include", world_core_rule_key: key })),
    }],
    source_snapshot: { kind: "project" },
    world_core: {
      ready_for_handoff: true, issues: [], author_seed_source_keys: ["m1"], rule_count: 3,
      snapshot: {
        author_seeds: [{ source_key: "m1", disposition: "included" }],
        rule_atoms: ["one", "two", "three"].map((key) => ({ rule_key: key, title: key, source_keys: ["m1"], can: "可以", cannot: "不能", cost: "代价", failure: "故障", maintenance: "维护" })),
        blocking_contradictions: [],
        vertical_slice: { rule_key: "one", daily_consequence: "日常", failure_consequence: "故障后果" },
      },
    },
  }
}

describe("generate Vue pure contracts", () => {
  it("preserves world source baseline, explicit references, and service limits", () => {
    const relatedPages = Array.from({ length: 18 }, (_, index) => ({ id: `page-${index + 2}` }))
    const payload = buildWorldPayload({
      projectId: "p1", sourcePageId: "page-1", targetKind: "world_bible_page",
      sourcePage: { id: "page-1", version_number: 7 }, sourceDraft: { id: "draft-1", updated_at: "t1" },
      templates: [], selectedTemplateId: "builtin:none", activationProfiles: [], activationProfileId: null,
      worldPageTemplates: [], messages: Array.from({ length: 41 }, (_, index) => ({ role: "user", content: String(index) })),
      selectedChapters: Array.from({ length: 21 }, (_, index) => ({ chapter_index: index + 1 })), qualityMode: "pro", includeWorldSynopsis: true,
      selectedSceneId: "scene-1", selectedThreadIds: ["thread-1"], selectedCharacterIds: ["character-1"], selectedEntityIds: ["entity-1"],
      worldPages: [{ id: "page-1" }, ...relatedPages], selectedWorldPageIds: ["page-1", ...relatedPages.map((item) => item.id), "page-2", "missing-page"],
    })
    expect(payload.novel_id).toBe("p1")
    expect(payload.source_context).toEqual({ kind: "world_bible_page", page_id: "page-1", baseline: { kind: "draft", page_version: 7, draft_id: "draft-1", draft_updated_at: "t1" } })
    expect(payload.target).toEqual({ kind: "world_bible_page", page_id: "page-1" })
    expect(payload.messages).toHaveLength(40)
    expect(payload.selected_chapter_indices).toHaveLength(20)
    expect(payload).toEqual(expect.objectContaining({ scene_id: "scene-1", thread_ids: ["thread-1"], character_ids: ["character-1"], entity_ids: ["entity-1"] }))
    expect(payload.selected_asset_refs).toHaveLength(16)
    expect(payload.selected_asset_refs.at(0)).toEqual({ type: "world_bible_page", id: "page-2" })
    expect(payload.selected_asset_refs.at(-1)).toEqual({ type: "world_bible_page", id: "page-17" })
  })

  it("excludes interrupted local recovery entries from subsequent world-chat payloads", () => {
    const payload = buildWorldPayload({
      projectId: "p1", sourcePageId: null, targetKind: "core_entity", sourcePage: null, sourceDraft: null,
      templates: [], selectedTemplateId: "builtin:none", activationProfiles: [], activationProfileId: null, worldPageTemplates: [],
      messages: [
        { role: "user", content: "继续完善" },
        { role: "assistant", content: "中断说明", error: true, interrupted: true },
        { role: "assistant", content: "可继续参考的历史回复" },
      ],
      selectedChapters: [], qualityMode: "fast", includeWorldSynopsis: true,
    })

    expect(payload.messages).toEqual([
      { role: "user", content: "继续完善" },
      { role: "assistant", content: "可继续参考的历史回复" },
    ])
  })

  it("builds and restores a typed World Core checkpoint without assistant prose", () => {
    const draft = convergenceDraftFromResponse({
      coverage: { complete: true, scope_label: "三个灵感", source_count: 1, covered_source_keys: ["m1"], manifest_hash: "a".repeat(64) },
      manifest: [{ key: "m1", kind: "conversation", label: "对话第 1 条 · 你", content_hash: "1".repeat(64), source_ref: { source_type: "author_message", source_hash: "2".repeat(64) } }],
      detail_summary: { before_grouping: 3, after_deduplication: 3, retained_in_sources: 0 },
      decision_cards: [{
        card_id: "C1", title: "规则", common_ground: [], dependencies: [], affected_targets: ["current_world_target"], source_keys: ["m1"], why_now: "收拢",
        items: ["one", "two", "three", "four"].map((key, index) => ({ item_id: `I${index + 1}`, text: `规则 ${index + 1}`, suggested_disposition: index === 2 ? "discard" : "include", world_core_rule_key: key })),
      }],
      source_snapshot: { kind: "project" },
      world_core: {
        ready_for_handoff: true, issues: [], author_seed_source_keys: ["m1"], rule_count: 3,
        snapshot: {
          author_seeds: [{ source_key: "m1", disposition: "included" }],
          rule_atoms: ["one", "two", "three", "four"].map((key) => ({ rule_key: key, title: key, source_keys: ["m1"], can: "可以", cannot: "不能", cost: "代价", failure: "故障", maintenance: "维护" })),
          blocking_contradictions: [],
          vertical_slice: { rule_key: "one", daily_consequence: "日常", failure_consequence: "故障后果" },
        },
      },
    })
    const request = buildWorldCoreCheckpointRequest({ novelId: "p1", draft, roundNo: 3, action: "consolidate" })

    expect(request).toMatchObject({
      novel_id: "p1",
      checkpoint: {
        schema_version: "world_core_checkpoint.v1",
        round_no: 3,
        source_manifest_hash: "a".repeat(64),
        seeds: [{ seed_key: "seed_1", source_ref: { source_type: "conversation", source_id: "m1", source_hash: "2".repeat(64) } }],
        decisions: expect.arrayContaining([
          expect.objectContaining({ disposition: "locked", rule_key: "one" }),
          expect.objectContaining({ disposition: "locked", rule_key: "two" }),
          expect.objectContaining({ disposition: "rejected", rule_key: "three" }),
        ]),
      },
    })
    const restored = convergenceDraftFromCheckpoint({ id: "hidden", target_type: "world_core_checkpoint", payload_json: request.checkpoint })
    expect(restored.worldCore).toMatchObject({ ready: true, restored: true, ruleCount: 3 })
    expect(restored.cards[0].items[2].disposition).toBe("rejected")
    const context = buildWorldCoreCheckpointContext(restored)
    expect(context).toContain("作者显式保存的阶段结果")
    expect(context).toContain("明确否定")
    expect(context).not.toContain("assistant prose")

    draft.cards[0].items[3].disposition = "open"
    expect(buildWorldCoreCheckpointRequest({ novelId: "p1", draft, roundNo: 4, action: "consolidate" })).toBeNull()
  })

  it("builds an honest full-taxonomy design seed without inventing coverage", () => {
    const draft = convergenceDraftFromResponse(worldCoreFixture())
    const request = buildWorldDesignCheckpointRequest({ novelId: "p1", projectTitle: "潮汐城", draft, roundNo: 3, action: "consolidate" })
    const state = request.checkpoint.world_state

    expect(request.checkpoint).toMatchObject({ schema_version: "world_design_checkpoint.v1", depth: "seed" })
    expect(state).toMatchObject({ schema_version: "0.1.0", project: { title: "潮汐城" }, fiction_core: { editor: { status: "not-started" } } })
    expect(state.facets).toHaveLength(22)
    expect(state.facets[0]).toMatchObject({ id: "F01", name: "本体法则与不可行域" })
    expect(state.coupling_chains).toHaveLength(5)
    expect(state.coupling_chains[0]).toMatchObject({ id: "C01", name: "权利链" })
    expect(state.pressure_tests).toHaveLength(12)
    expect(state.pressure_tests[0]).toMatchObject({ id: "T01", name: "主角移除" })
    expect(Object.values(state.reproduction_loops).every((item) => item.status === "gap" && !item.evidence.length)).toBe(true)
    expect(state.pressure_tests.every((item) => item.status === "not-run")).toBe(true)
    expect(convergenceDraftFromCheckpoint({ target_type: "world_design_checkpoint", payload_json: request.checkpoint })?.worldCore.restored).toBe(true)
  })

  it("compiles selective convergence choices without turning open details into facts", () => {
    const draft = convergenceDraftFromResponse({
      coverage: { complete: true, scope_label: "最近 40 条对话", source_count: 1, excluded_message_count: 4, manifest_hash: "a".repeat(64) },
      manifest: [{ key: "m1", kind: "conversation", label: "对话", content_hash: "1".repeat(64), source_ref: { source_type: "author_message" } }],
      detail_summary: { before_grouping: 3, after_deduplication: 3, retained_in_sources: 0 },
      decision_cards: [{
        card_id: "C1", title: "制度", common_ground: [], dependencies: [], affected_targets: ["current_world_target", "outline"], source_keys: ["m1"], why_now: "现在决定",
        items: [
          { item_id: "i1", text: "采用制度骨架", suggested_disposition: "include" },
          { item_id: "i2", text: "税率数字", suggested_disposition: "open" },
          { item_id: "i3", text: "废弃旧组织", suggested_disposition: "discard" },
        ],
      }],
      source_snapshot: { kind: "world_bible_page", page_id: "page-1", page_version: 2, draft_id: "draft-1", draft_updated_at: "t1" },
    })

    const message = compileConvergenceMessage(draft)
    expect(message).toContain("本次纳入：\n- 采用制度骨架")
    expect(message).toContain("继续开放（不得写成已确认事实）：\n- 税率数字")
    expect(message).toContain("明确放弃（后续不要恢复）：\n- 废弃旧组织")
    expect(message).toContain("故事结构")
    expect(convergenceSourceMatchesPayload(draft, { source_context: { kind: "world_bible_page", page_id: "page-1", baseline: { kind: "draft", page_version: 2, draft_id: "draft-1", draft_updated_at: "t1" } } })).toBe(true)
    expect(convergenceSourceMatchesPayload(draft, { source_context: { kind: "world_bible_page", page_id: "page-1", baseline: { kind: "draft", page_version: 2, draft_id: "draft-1", draft_updated_at: "t2" } } })).toBe(false)
  })

  it("builds one ID-free handoff string from the covered convergence snapshot", () => {
    const draft = convergenceDraftFromResponse({
      coverage: { complete: true, scope_label: "当前页与对话", source_count: 2, excluded_message_count: 3, manifest_hash: "a".repeat(64) },
      manifest: [
        { key: "m1", kind: "conversation", label: "作者目标", content_hash: "1".repeat(64), source_ref: { source_type: "author_message", source_id: "internal-message-id" } },
        { key: "m2", kind: "source_page", label: "潮港制度", content_hash: "2".repeat(64), source_ref: { source_type: "world_bible_page", source_id: "internal-page-id" } },
      ],
      detail_summary: { before_grouping: 2, after_deduplication: 2, retained_in_sources: 0 },
      decision_cards: [{ card_id: "C1", title: "港口边界", common_ground: ["保留潮汐贸易"], items: [{ item_id: "I1", text: "税率继续开放", suggested_disposition: "open" }], dependencies: [], affected_targets: ["current_world_target"], source_keys: ["m1", "m2"], why_now: "先固定边界" }],
      source_snapshot: { kind: "world_bible_page", page_id: "internal-page-id", page_version: 3, draft_id: "internal-draft-id", content_hash: "3".repeat(64) },
    }, { now: () => Date.parse("2026-08-11T10:00:00Z") })
    const markdown = buildWorldHandoffMarkdown({
      projectTitle: "长篇项目", targetKind: "world_bible_page", convergenceDraft: draft,
      sourcePage: { id: "internal-page-id", title: "潮港制度" },
      sourceDraft: { id: "internal-draft-id", title: "潮港制度", free_text: "港口按潮窗开放。", sections_json: [{ section_id: "internal-section-id", title: "开放边界", body_markdown: "税率尚未决定。", projection_policy: "excluded", sensitivity_hint: "author_only" }] },
    })

    expect(markdown).toContain("handoff_version: world-handoff-v1")
    expect(markdown).toContain("港口按潮窗开放")
    expect(markdown).toContain("不进入普通 AI 上下文；仅作者")
    expect(markdown).toContain(`SHA-256 ${"2".repeat(64)}`)
    expect(markdown).toContain("55,000 字符")
    expect(markdown).toContain("外部回包里的 checks_run")
    expect(markdown).not.toContain("internal-page-id")
    expect(markdown).not.toContain("internal-draft-id")
    expect(markdown).not.toContain("internal-section-id")
    expect(buildWorldHandoffMarkdown({ convergenceDraft: { ...draft, stale: true } })).toBe("")
  })

  it("counts Unicode characters, hashes exact bytes, and reads optional packet position", async () => {
    expect(externalPacketCharacterCount("甲🙂乙")).toBe(3)
    const first = await hashExternalPacket("回包\n")
    expect(first).toMatch(/^[0-9a-f]{64}$/)
    expect(await hashExternalPacket("回包\n")).toBe(first)
    expect(await hashExternalPacket("回包")).not.toBe(first)
    expect(parseExternalPacketPosition("packet_index: 2\npacket_total: 5", 1)).toEqual({ packetIndex: 2, packetTotal: 5 })
    expect(parseExternalPacketPosition("没有包序号", 3)).toEqual({ packetIndex: 3, packetTotal: null })
  })

  it("keeps multi-packet completion honest and counts exact duplicates as no-op slots", () => {
    const record = (packetIndex, status = "decision_ready") => ({
      hash: String(packetIndex).padStart(64, "0"), packetIndex, packetTotal: 5,
      characterCount: 12, status, previewedAt: packetIndex,
    })
    const partial = externalPacketBatchSummary([
      record(1), record(2), record(4, "exact_duplicate"), record(5, "previewed"),
    ])
    expect(partial).toMatchObject({ packetTotal: 5, complete: false, missingPacketIndexes: [3] })
    expect(partial.label).toContain("缺第 3 包")

    const complete = externalPacketBatchSummary([
      record(1), record(2), record(3), record(4, "exact_duplicate"), record(5),
    ])
    expect(complete).toMatchObject({ packetTotal: 5, complete: true, missingPacketIndexes: [] })
    expect(complete.label).toContain("5/5")
  })

  it("builds one confirmed visual purpose from author decisions without promoting image details", () => {
    const draft = convergenceDraftFromResponse({
      coverage: { complete: true, scope_label: "白堤当前页", source_count: 1, manifest_hash: "a".repeat(64) },
      manifest: [{ key: "m1", kind: "source_page", label: "白堤", content_hash: "1".repeat(64) }],
      decision_cards: [{
        card_id: "C1", title: "空间边界", common_ground: ["保留三河汇流"], dependencies: [], affected_targets: ["map"], source_keys: ["m1"],
        items: [
          { item_id: "I1", text: "保留堤上聚落", suggested_disposition: "include" },
          { item_id: "I2", text: "邻城方向继续开放", suggested_disposition: "open" },
          { item_id: "I3", text: "不画正式国界", suggested_disposition: "discard" },
        ],
      }],
      source_snapshot: { kind: "world_bible_page", page_id: "internal-page-id", page_version: 2 },
    })
    const brief = visualBriefFromConvergence(draft, { sourceLabel: "白堤 · 已发布世界笔记", sourceTitle: "白堤" })
    brief.confirmedAt = "2026-08-11T12:00:00.000Z"
    const handoff = "# AI 小说创作交接快照\n\n- handoff_version: world-handoff-v1\n"
    const markdown = buildVisualBriefMarkdown({ handoffMarkdown: handoff, visualBrief: brief, convergenceDraft: draft })

    expect(brief).toMatchObject({ purpose: "overview", exactLabels: "白堤", stale: false })
    expect(brief.mustKeep).toContain("三河汇流")
    expect(brief.openItems).toContain("邻城方向继续开放")
    expect(brief.avoid).toContain("不画正式国界")
    expect(markdown).toContain("brief_version: world-visual-brief-v1")
    expect(markdown).toContain("候选图核对")
    expect(markdown).toContain("不创建图片资产")
    expect(markdown).not.toContain("internal-page-id")
    expect(buildVisualBriefMarkdown({ handoffMarkdown: handoff, visualBrief: { ...brief, stale: true }, convergenceDraft: draft })).toBe("")
  })

  it("keeps viewpoint separate, adds it to character context, and suppresses synopsis", () => {
    const payload = buildTaskPayload("p1", { task: "写场景", scope: "chapter", reveal_mode: "character", budget_tokens: 0, entity_ids: [], character_ids: ["related"], viewpoint_character_id: "pov", chapter_index: 2, scene_id: "scene-2", include_world_synopsis: true })
    expect(validateTaskPayload(payload)).toBeNull()
    expect(payload.character_ids).toEqual(["related", "pov"])
    expect(payload.viewpoint_character_id).toBe("pov")
    expect(payload.include_world_synopsis).toBe(false)
  })

  it("computes section changes without producing HTML", () => {
    expect(sectionDiff([{ section_id: "a", title: "旧" }, { section_id: "b" }], [{ section_id: "a", title: "新" }, { section_id: "c" }])).toEqual([
      expect.objectContaining({ kind: "修改", fields: ["标题"] }),
      expect.objectContaining({ kind: "新增" }),
      expect.objectContaining({ kind: "删除" }),
    ])
  })

  it("keeps the POV knowledge-boundary instruction contract", () => {
    const text = buildPovInstruction("保持克制", "避免剧透")
    expect(text).toContain("用户指令是作者意图，不等于角色知识")
    expect(text).toContain("角色判断、台词、内心只能使用确认上下文中该角色可见的信息")
  })
})
