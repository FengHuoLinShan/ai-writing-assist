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
      .toBe("这次修改让第 3 章的相关内容需要更新（涉及场景 4、5）。")
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

 it("只有索引刷新和未知覆盖时收在详情，保留核对说明与入口", async () => {
  const raw = { affected: [], invalidated: [{ consumer: "evidence_chapter_index" }, { consumer: "interaction_source_cache", detail: { purged_rows: 0 } }], unknown_scope: true, unsupported: [{ consumer: "map_atlas" }] }
  const wrapper = mount(InvalidationNotice, { props: { notice: normalizeInvalidationNotice(raw) } })
  expect(wrapper.find(".writing-invalidation-notice").exists()).toBe(false)
  expect(wrapper.get("details").attributes("open")).toBeUndefined()
  expect(wrapper.text()).toContain("地图集")
  expect(wrapper.text()).not.toContain("相关内容需要更新")
  await wrapper.get("button").trigger("click")
  expect(wrapper.emitted("open")).toHaveLength(1)
 })
 it("实际清理缓存或已有受影响资产时保留显著失效提示", () => {
  const raw = { affected: [], invalidated: [{ consumer: "interaction_source_cache", detail: { purged_rows: 1 } }], unknown_scope: true }
  const wrapper = mount(InvalidationNotice, { props: { notice: normalizeInvalidationNotice(raw) } })
  expect(wrapper.find(".writing-invalidation-notice").exists()).toBe(true)
 })

 it("真实空场景回执的零计数动作折叠，任何实际失效或缺失计数仍显著显示", () => {
  const invalidated = [
    { consumer: "evidence_chapter_index" },
    { consumer: "interaction_source_cache", detail: { purged_rows: 0 } },
    { consumer: "assistant_suggestion_validity", detail: { mode: "evidence_freshness" } },
    { consumer: "evolution_runs", detail: { run_keys: [], recompute_required: false } },
    { consumer: "story_state", detail: { stale_events: 0 } },
  ]
  const raw = { affected: [], invalidated, unknown_scope: true, unsupported: [{ consumer: "map_atlas" }] }
  expect(normalizeInvalidationNotice(raw).coverageOnly).toBe(true)
  for (const detail of [{ stale_events: 1 }, {}, { stale_events: 0, unknown_count: 0 }]) {
    expect(normalizeInvalidationNotice({ ...raw, invalidated: [...invalidated.slice(0, -1), { consumer: "story_state", detail }] }).coverageOnly).toBe(false)
  }
 })
