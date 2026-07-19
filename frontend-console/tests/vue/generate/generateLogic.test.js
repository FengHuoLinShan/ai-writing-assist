import { describe, expect, it } from "vitest"
import { buildPovInstruction, buildTaskPayload, buildWorldPayload, sectionDiff, validateTaskPayload } from "../../../vue/views/generate/logic/generateLogic.js"

describe("generate Vue pure contracts", () => {
  it("preserves world source baseline, explicit references, and service limits", () => {
    const payload = buildWorldPayload({
      projectId: "p1", sourcePageId: "page-1", targetKind: "world_bible_page",
      sourcePage: { id: "page-1", version_number: 7 }, sourceDraft: { id: "draft-1", updated_at: "t1" },
      templates: [], selectedTemplateId: "builtin:none", activationProfiles: [], activationProfileId: null,
      worldPageTemplates: [], messages: Array.from({ length: 41 }, (_, index) => ({ role: "user", content: String(index) })),
      selectedChapters: Array.from({ length: 21 }, (_, index) => ({ chapter_index: index + 1 })), qualityMode: "pro", includeWorldSynopsis: true,
      selectedSceneId: "scene-1", selectedThreadIds: ["thread-1"], selectedCharacterIds: ["character-1"], selectedEntityIds: ["entity-1"],
    })
    expect(payload.novel_id).toBe("p1")
    expect(payload.source_context).toEqual({ kind: "world_bible_page", page_id: "page-1", baseline: { kind: "draft", page_version: 7, draft_id: "draft-1", draft_updated_at: "t1" } })
    expect(payload.target).toEqual({ kind: "world_bible_page", page_id: "page-1" })
    expect(payload.messages).toHaveLength(40)
    expect(payload.selected_chapter_indices).toHaveLength(20)
    expect(payload).toEqual(expect.objectContaining({ scene_id: "scene-1", thread_ids: ["thread-1"], character_ids: ["character-1"], entity_ids: ["entity-1"] }))
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
