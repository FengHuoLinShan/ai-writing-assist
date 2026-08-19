import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import ConflictDetailDialog from "../../../vue/views/writing/components/ConflictDetailDialog.vue"

function model(overrides = {}) {
  return {
    open: true,
    busy: false,
    error: null,
    sourcePreview: null,
    check: {
      id: "check-1",
      chapter_index: 2,
      include_candidates: true,
      ai_review_status: "partial",
      items: [
        {
          id: "rule-1",
          severity: "high",
          kind: "forbidden_present",
          status: "open",
          source_module: "world",
          evidence_summary: '<img src=x onerror="alert(1)">',
          location_json: {
            text_range: { start: 7, end: 12 },
            source: { module: "world", label: "世界设定", field: "rule", type: "lore", excerpt: "禁止传送" },
            open_target: { kind: "world_object" },
            needs_review_reason: "pending_source",
          },
          ai_suggestion: {
            strategy: "改写",
            suggested_text: "改为步行",
            rationale: "遵守设定",
            constraints: ["保留语气"],
            risk_notes: ["节奏变慢"],
          },
        },
        {
          id: "ai-1",
          severity: "medium",
          kind: "motivation_gap",
          status: "later",
          source_module: "outline",
          evidence_summary: "动机不足",
          is_ai_judgment: true,
          needs_review: true,
          confidence: 0.72,
          llm_rationale: "需要更明确的触发点",
        },
      ],
    },
    ...overrides,
  }
}

describe("ConflictDetailDialog", () => {
  enableAutoUnmount(afterEach)

  it("以 Vue 文本节点完整展示规则、AI 判断、证据和建议", () => {
    const wrapper = mount(ConflictDetailDialog, { props: { model: model() } })
    expect(wrapper.text()).toContain("字面预警")
    expect(wrapper.text()).toContain("AI 判断")
    expect(wrapper.text()).toContain("状态：部分生成")
    expect(wrapper.text()).toContain("禁止传送")
    expect(wrapper.text()).toContain("需要人工检查")
    expect(wrapper.text()).toContain("置信度 72%")
    expect(wrapper.get("textarea").element.value).toBe("改为步行")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">')
  })

  it("把可覆盖的规则交给作者决定，AI 与历史结果不会冒充确定性阻断", () => {
    const items = [
      { id: "rule-high", severity: "high", kind: "forbidden_present", status: "open", source_module: "writing", evidence_summary: "命中禁止项" },
      { id: "rule-review", severity: "high", kind: "map_risk", status: "open", source_module: "world", evidence_summary: "候选地图证据", needs_review: true },
      { id: "ai-soft", severity: "high", kind: "motivation_gap", status: "open", source_module: "outline", evidence_summary: "动机可加强", is_ai_judgment: true },
      { id: "ai-choice", severity: "medium", kind: "emotion_jump", status: "open", source_module: "outline", evidence_summary: "需作者判断", is_ai_judgment: true, needs_review: true },
      { id: "rule-closed", severity: "high", kind: "required_missing", status: "resolved", source_module: "outline", evidence_summary: "已修复" },
      { id: "ai-later", severity: "medium", kind: "voice_or_pov_drift", status: "later", source_module: "outline", evidence_summary: "以后再看", is_ai_judgment: true },
    ]
    const wrapper = mount(ConflictDetailDialog, {
      props: {
        model: model({
          check: {
            ...model().check,
            status: "degraded",
            version_number: 3,
            scene_id: "scene-private-id",
            summary_json: { degraded_sources: ["outline", "world.map.candidates"] },
            items,
          },
        }),
      },
    })
    const action = (id) => wrapper.find(`[data-conflict-item-id="${id}"] [data-author-action]`)

    expect(action("rule-high").attributes("data-author-action")).toBe("can_improve")
    expect(action("rule-review").attributes("data-author-action")).toBe("can_improve")
    expect(action("ai-soft").attributes("data-author-action")).toBe("can_improve")
    expect(action("ai-choice").attributes("data-author-action")).toBe("needs_decision")
    expect(action("rule-closed").exists()).toBe(false)
    expect(action("ai-later").exists()).toBe(false)
    expect(wrapper.text()).toContain("来源版本：工作稿 v3")
    expect(wrapper.text()).toContain("定向复检：第 2 章当前场景")
    expect(wrapper.get('[role="status"][data-author-action="needs_decision"]').text()).toContain("故事结构、地图资料")
    expect(wrapper.find('[data-author-action="must_fix"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain("scene-private-id")
  })

  it("从 Vue 事件送出状态决策、AI 请求、定位、来源与可编辑建议", async () => {
    const wrapper = mount(ConflictDetailDialog, { props: { model: model() } })
    await wrapper.get('[data-conflict-item-id="rule-1"] [data-action="later-conflict"]').trigger("click")
    await wrapper.get('[data-action="conflict-ai-review"]').trigger("click")
    await wrapper.get('[data-conflict-item-id="rule-1"] [data-action="generate-conflict-suggestion"]').trigger("click")
    await wrapper.get('[data-conflict-item-id="rule-1"] [data-action="locate-conflict"]').trigger("click")
    await wrapper.get('[data-conflict-item-id="rule-1"] [data-action="open-conflict-source"]').trigger("click")
    await wrapper.get("textarea").setValue("作者修改后的建议")
    await wrapper.get('[data-conflict-item-id="rule-1"] [data-action="apply-conflict-suggestion"]').trigger("click")

    expect(wrapper.emitted("status")[0]).toEqual([{ itemId: "rule-1", status: "later" }])
    expect(wrapper.emitted("ai-review")).toHaveLength(1)
    expect(wrapper.emitted("suggestion")[0]).toEqual(["rule-1"])
    expect(wrapper.emitted("locate")[0]).toEqual(["rule-1"])
    expect(wrapper.emitted("source")[0]).toEqual(["rule-1"])
    expect(wrapper.emitted("apply")[0]).toEqual([{ itemId: "rule-1", text: "作者修改后的建议" }])
  })

  it("记忆来源详情也保持在 Vue 树内", async () => {
    const wrapper = mount(ConflictDetailDialog, {
      props: { model: model({ sourcePreview: { kind: "memory", title: "记忆来源", chapterIndex: 7, characterId: "char-1" } }) },
    })
    expect(wrapper.get('[aria-label="冲突来源详情"]').text()).toContain("第 7 章")
    expect(wrapper.get('[aria-label="冲突来源详情"]').text()).toContain("char-1")
    await wrapper.get('[aria-label="冲突来源详情"] button').trigger("click")
    expect(wrapper.emitted("dismiss-source")).toHaveLength(1)
  })

  it("只为持久化证据支持的正文定位和来源打开动作启用导航", async () => {
    const items = [
      {
        id: "nested-range",
        kind: "forbidden_present",
        source_module: "writing",
        location_json: { text_range: { start: "7", end: "12" }, open_target: { kind: "text_range" } },
      },
      {
        id: "legacy-range",
        kind: "forbidden_present",
        source_module: "writing",
        location_json: { start: 3, end: 6 },
      },
      {
        id: "world-source",
        kind: "world_rule",
        source_module: "world",
        location_json: { open_target: { kind: "world_object" } },
      },
      {
        id: "outline-source",
        kind: "required_missing",
        source_module: "outline",
        location_json: {},
      },
      {
        id: "memory-source",
        kind: "continuity_location_mismatch",
        source_module: "memory",
        location_json: { open_target: { kind: "memory_chapter" } },
      },
      {
        id: "broken-text-range",
        kind: "forbidden_present",
        source_module: "world",
        location_json: { text_range: {}, open_target: { kind: "text_range" } },
      },
      {
        id: "unknown-ai",
        kind: "motivation_gap",
        source_module: "ai",
        is_ai_judgment: true,
        location_json: {},
      },
    ]
    const wrapper = mount(ConflictDetailDialog, {
      props: { model: model({ check: { ...model().check, items } }) },
    })
    const navigation = (itemId, action) => wrapper.get(`[data-conflict-item-id="${itemId}"] [data-action="${action}"]`)

    for (const itemId of ["nested-range", "legacy-range"]) {
      expect(navigation(itemId, "locate-conflict").text()).toBe("定位正文")
      expect(navigation(itemId, "locate-conflict").attributes("disabled")).toBeUndefined()
    }
    expect(navigation("nested-range", "open-conflict-source").text()).toBe("打开来源")
    expect(navigation("nested-range", "open-conflict-source").attributes("disabled")).toBeUndefined()
    expect(navigation("legacy-range", "open-conflict-source").text()).toBe("无可打开来源")
    expect(navigation("legacy-range", "open-conflict-source").attributes("disabled")).toBeDefined()

    for (const itemId of ["world-source", "outline-source", "memory-source"]) {
      expect(navigation(itemId, "locate-conflict").text()).toBe("无正文定位")
      expect(navigation(itemId, "locate-conflict").attributes("disabled")).toBeDefined()
      expect(navigation(itemId, "open-conflict-source").text()).toBe("打开来源")
      expect(navigation(itemId, "open-conflict-source").attributes("disabled")).toBeUndefined()
    }
    for (const itemId of ["broken-text-range", "unknown-ai"]) {
      expect(navigation(itemId, "locate-conflict").text()).toBe("无正文定位")
      expect(navigation(itemId, "locate-conflict").attributes("disabled")).toBeDefined()
      expect(navigation(itemId, "open-conflict-source").text()).toBe("无可打开来源")
      expect(navigation(itemId, "open-conflict-source").attributes("disabled")).toBeDefined()
    }

    await navigation("nested-range", "locate-conflict").trigger("click")
    await navigation("legacy-range", "locate-conflict").trigger("click")
    await navigation("nested-range", "open-conflict-source").trigger("click")
    await navigation("world-source", "open-conflict-source").trigger("click")
    await navigation("outline-source", "open-conflict-source").trigger("click")
    await navigation("memory-source", "open-conflict-source").trigger("click")
    for (const itemId of ["broken-text-range", "unknown-ai"]) {
      await navigation(itemId, "locate-conflict").trigger("click")
      await navigation(itemId, "open-conflict-source").trigger("click")
    }

    expect(wrapper.emitted("locate")).toEqual([["nested-range"], ["legacy-range"]])
    expect(wrapper.emitted("source")).toEqual([["nested-range"], ["world-source"], ["outline-source"], ["memory-source"]])
  })
})
