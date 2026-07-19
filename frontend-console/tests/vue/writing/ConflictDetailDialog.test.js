import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
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
            source: { module: "world", label: "世界设定", field: "rule", type: "lore", excerpt: "禁止传送" },
            open_target: { kind: "map_object" },
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
  it("以 Vue 文本节点完整展示规则、AI 判断、证据和建议", () => {
    const wrapper = mount(ConflictDetailDialog, { props: { model: model() } })
    expect(wrapper.text()).toContain("规则命中")
    expect(wrapper.text()).toContain("AI 判断")
    expect(wrapper.text()).toContain("状态：部分生成")
    expect(wrapper.text()).toContain("禁止传送")
    expect(wrapper.text()).toContain("需要人工检查")
    expect(wrapper.text()).toContain("置信度 72%")
    expect(wrapper.get("textarea").element.value).toBe("改为步行")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">')
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
})
