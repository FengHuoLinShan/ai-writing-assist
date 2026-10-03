/**
 * 表格迁移纯逻辑测试 — 标签、目标选项、payload 组装与 409 判定。
 */
import { describe, expect, it } from "vitest"

import {
  PREVIEW_TABS,
  actionLabel,
  columnTargetOptions,
  conflictItems,
  decisionOptionsFor,
  decisionsPayload,
  isPreviewStale,
  isRevisionConflict,
  itemDecisionScope,
  mappingPayload,
  referenceOnlyItems,
  sessionStatusLabel,
  sheetKindLabel,
  sheetWantsAiByDefault,
} from "../../../vue/views/project/logic/spreadsheetMigration.js"

describe("spreadsheetMigration 逻辑", () => {
  it("表类型与列目标使用作者语言", () => {
    expect(sheetKindLabel("characters")).toBe("人物表")
    expect(sheetKindLabel("unknown-kind")).toBe("unknown-kind")
    expect(sessionStatusLabel("applied")).toBe("已导入")
    expect(actionLabel("fill_empty")).toBe("补全空字段")
  })

  it("各表类型的列目标选项与后端分组一致", () => {
    const characterOptions = columnTargetOptions("characters")
    expect(characterOptions).toContain("name")
    expect(characterOptions).toContain("role")
    expect(characterOptions).not.toContain("source_name")

    const worldOptions = columnTargetOptions("world_objects")
    expect(worldOptions).toContain("name")
    expect(worldOptions).toContain("hidden_truth")
    // 人物专属字段不出现在设定表选项中
    expect(worldOptions).not.toContain("role")
    expect(worldOptions).not.toContain("personality")

    const relationOptions = columnTargetOptions("relations")
    expect(relationOptions).toContain("relation_type")
    expect(relationOptions).not.toContain("name")

    const storyOptions = columnTargetOptions("chapter_outline")
    expect(storyOptions).toContain("must_not_happen")
    expect(storyOptions).not.toContain("relation_type")

    expect(columnTargetOptions("skip")).toEqual(["ignore"])
  })

  it("决策选项按条目类型收窄", () => {
    expect(decisionOptionsFor("entity").map((option) => option.action)).toEqual([
      "auto",
      "different_object",
      "use_existing",
      "append_note",
      "skip",
    ])
    expect(decisionOptionsFor("relation").map((option) => option.action)).toEqual([
      "auto",
      "skip",
    ])
    expect(decisionOptionsFor("story").map((option) => option.action)).toEqual([
      "auto",
      "skip",
    ])
    // 未知范围按实体处理，且文案取自统一标签表
    expect(decisionOptionsFor(undefined)).toEqual(decisionOptionsFor("entity"))
    expect(decisionOptionsFor("entity")[0].label).toBe("按建议")
  })

  it("条目决策范围：显式字段优先，旧会话按形状判别", () => {
    expect(itemDecisionScope({ decision_scope: "relation" })).toBe("relation")
    expect(itemDecisionScope({ kind: "chapter_plan" })).toBe("story")
    expect(itemDecisionScope({ source_label: "张三" })).toBe("relation")
    expect(itemDecisionScope({ label: "张三", fills: [] })).toBe("entity")
    expect(itemDecisionScope(null)).toBe("entity")
  })

  it("大纲类表默认交给 AI 整理，人物/关系表不默认", () => {
    expect(sheetWantsAiByDefault("chapter_outline")).toBe(true)
    expect(sheetWantsAiByDefault("story_outline")).toBe(true)
    expect(sheetWantsAiByDefault("characters")).toBe(false)
    expect(sheetWantsAiByDefault("relations")).toBe(false)
  })

  it("mapping payload 携带 revision CAS 与选项", () => {
    const payload = mappingPayload(
      { novel_id: "n1", revision: 3 },
      [{ sheet_key: "f0s0", kind: "characters", header_row: 1, columns: { c0: "name" } }],
      { written_chapter_policy: "link_scene" },
    )
    expect(payload).toEqual({
      novel_id: "n1",
      expected_revision: 3,
      sheets: [
        {
          sheet_key: "f0s0",
          kind: "characters",
          header_row: 1,
          columns: { c0: "name" },
        },
      ],
      options: {
        written_chapter_policy: "link_scene",
        outline_head_policy: "create_if_missing",
      },
    })
  })

  it("decisions payload 展开决策映射并保留关系分组", () => {
    const payload = decisionsPayload(
      {
        k1: { action: "skip" },
        k2: { action: "use_existing", relation_kind: "social" },
        k3: { action: "auto", accept_ai: true },
      },
      { 师徒: "social" },
    )
    expect(payload.decisions).toEqual([
      { item_key: "k1", action: "skip" },
      { item_key: "k2", action: "use_existing", relation_kind: "social" },
      { item_key: "k3", action: "auto", accept_ai: true },
    ])
    expect(payload.relation_kind_groups).toEqual({ 师徒: "social" })
  })

  it("409 判定区分 revision 冲突与预览过期", () => {
    expect(isRevisionConflict({ code: "migration_revision_stale" })).toBe(true)
    expect(isRevisionConflict({ code: "migration_preview_stale" })).toBe(false)
    expect(isPreviewStale({ code: "migration_preview_stale" })).toBe(true)
    expect(isPreviewStale({ code: "migration_revision_stale" })).toBe(false)
  })

  it("冲突页签汇总三类冲突，仅参考单独分页", () => {
    const preview = {
      world_items: [{ item_key: "a", action: "conflict" }, { item_key: "b", action: "create" }],
      relations: [{ item_key: "c", action: "conflict" }],
      structures: [
        { item_key: "d", action: "conflict" },
        { item_key: "e", action: "reference_only" },
      ],
    }
    expect(conflictItems(preview).map((item) => item.item_key)).toEqual(["a", "c", "d"])
    expect(referenceOnlyItems(preview).map((item) => item.item_key)).toEqual(["e"])
    expect(PREVIEW_TABS.map((tab) => tab.key)).toContain("conflicts")
  })
})
