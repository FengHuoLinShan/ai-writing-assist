import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { normalizeInvalidationNotice } from "../../../vue/views/writing/invalidationModel.js"
import InvalidationNotice from "../../../vue/views/writing/components/InvalidationNotice.vue"

function notice(overrides = {}) {
  return normalizeInvalidationNotice({
    chapter_index: 3,
    affected: [
      { consumer: "story_scene_checkpoint", scene_index: 4, reason: "anchored_chapter_edited", basis: "known" },
      { consumer: "story_scene_checkpoint", scene_index: 5, reason: "conservative_expansion_unregistered", basis: "unknown" },
    ],
    unknown_scope: true,
    receipt_id: "receipt-abc",
    invalidated: [{ consumer: "evidence_chapter_index", label: "章节证据索引" }],
    ...overrides,
  }, { chapterIndex: 3 })
}

describe("InvalidationNotice", () => {
  it("保存后就地展示作者语言摘要、待核实说明与重算入口", () => {
    const wrapper = mount(InvalidationNotice, { props: { notice: notice() } })

    expect(wrapper.get(".writing-invalidation-notice__headline").text())
      .toBe("这次修改让第 3 章起的场景状态需要更新（涉及场景 4、5）。")
    expect(wrapper.get(".writing-invalidation-notice__unknown").text()).toContain("部分影响范围待核实")
    expect(wrapper.get(".writing-invalidation-notice__hint").text()).toContain("继续写作")
    expect(wrapper.get("button").text()).toBe("查看受影响与重算选项")
  })

  it("范围完全已知时不出现待核实说明", () => {
    const wrapper = mount(InvalidationNotice, {
      props: {
        notice: notice({
          unknown_scope: false,
          affected: [{ consumer: "evidence_chapter_index", reason: "anchored_chapter_edited", basis: "known" }],
        }),
      },
    })

    expect(wrapper.find(".writing-invalidation-notice__unknown").exists()).toBe(false)
  })

  it("点击入口发出 open 事件（不弹窗打断）", async () => {
    const wrapper = mount(InvalidationNotice, { props: { notice: notice() } })

    await wrapper.get("button").trigger("click")

    expect(wrapper.emitted("open")).toHaveLength(1)
  })
})
