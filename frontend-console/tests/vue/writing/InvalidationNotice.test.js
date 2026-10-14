import { setBridgeOverrides, resetBridgeOverrides } from "../../../vue/bridge/index.js"
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
  expect(wrapper.text()).toContain("地图册")
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

it("地图名和对应章节就地可见，内部标识不显示", async () => {
  let target = null
  setBridgeOverrides({ router: { navigate: (...args) => { target = args } } })
  const notice = normalizeInvalidationNotice({ affected: [{ consumer: "map_atlas", node_id: "hidden-map-id", map_title: "东岸地图", chapter_index: 3, basis: "known" }] })
  const wrapper = mount(InvalidationNotice, { props: { notice } })
  expect(wrapper.text()).toContain("东岸地图 · 第 3 章")
  expect(wrapper.text()).toContain("去地图核对")
  expect(wrapper.text()).not.toContain("hidden-map-id")
  await wrapper.findAll("button").find((button) => button.text() === "去地图核对").trigger("click")
  expect(target.slice(0, 3)).toEqual(["map", null, true])
  expect(new URLSearchParams(target[3]).get("node_id")).toBe("hidden-map-id")
  resetBridgeOverrides()
})

it("主提示只用作者语言说明地图未核对，范围诊断不展开", () => {
  const coverage = "保守扩大：从锚定受影响章的最早 Scene（含）起的全部系统派生投影已失效；地图册未核对完整，请到地图核对来源"
  const wrapper = mount(InvalidationNotice, {
    props: {
      notice: notice({
        coverage_note: coverage,
        invalidated: [{ consumer: "map_atlas", label: "地图册", detail: { maps: [], checked: false, note: "地图册未核对：来源查询暂时失败" } }],
      }),
    },
  })
  const status = wrapper.get(".writing-invalidation-notice")
  expect(status.text()).toContain("地图册未核对：这次没能检查哪些地图引用了本章")
  expect(status.text()).not.toContain("投影")
  expect(status.text()).not.toContain("Scene")

  const withoutMapGap = mount(InvalidationNotice, { props: { notice: notice({ coverage_note: coverage }) } })
  expect(withoutMapGap.text()).not.toContain("保守扩大")
  expect(withoutMapGap.text()).not.toContain("地图册未核对")
})
