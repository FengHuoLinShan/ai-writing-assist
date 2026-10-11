import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneLensSummary from "../../../vue/views/writing/components/SceneLensSummary.vue"

const hash = "a".repeat(64)

const scene = { id: "scene-1", title: "灯塔下", chapter_ids: ["2"], structure_meta: {} }

function lensData(fields) {
  return {
    state_fingerprint: "fp-1",
    subject_choices: {},
    role_visible_knowledge: [],
    scene_world_state: [],
    warnings: [],
    object_states: [
      {
        subject_id: "entity-1",
        label: "铜钥匙",
        fields,
        knowledge: [],
        unknowns: [],
      },
    ],
  }
}

function fieldWithProvenance(status) {
  return {
    field: "custody_holder",
    display: "乙",
    layer: "fact",
    confidence: "derived",
    possibly_false: false,
    source: {
      checkpoint_id: "checkpoint-1",
      provenance: {
        field: "custody_holder",
        event_id: status === "unverified" ? null : "event-1",
        status,
        source_refs: status === "exact"
          ? [{
            draft_id: "draft-1",
            chapter_index: 2,
            version_number: 1,
            content_mode: "working",
            start_offset: 10,
            end_offset: 24,
            source_hash: hash,
            range_hash: "b".repeat(64),
          }]
          : [],
      },
    },
  }
}

function mountSummary(lens) {
  return mount(SceneLensSummary, {
    props: { scene, lens, projectId: "p1" },
    global: { stubs: { SceneStateTrial: true, SceneCheckpointHistory: true } },
  })
}

describe("SceneLensSummary field provenance drill-down", () => {
  beforeEach(() => {
    setBridgeOverrides({})
  })
  afterEach(() => {
    resetBridgeOverrides()
  })

  it("shows the first-entry empty state when no field carries provenance", () => {
    const wrapper = mountSummary({
      loading: false,
      error: null,
      data: lensData([{ field: "custody_holder", display: "乙", layer: "fact", confidence: "derived", source: { checkpoint_id: "checkpoint-1" } }]),
    })

    expect(wrapper.text()).toContain("本场状态还没有逐字段来源记录；随着正文推进和状态整理，每个字段会逐步标出具体依据。")
    expect(wrapper.findAll(".scene-lens__provenance-badge")).toHaveLength(0)
  })

  it("marks field status inline and opens the drill-down panel on demand", async () => {
    const wrapper = mountSummary({
      loading: false,
      error: null,
      data: lensData([fieldWithProvenance("exact"), fieldWithProvenance("unverified")]),
    })

    const badges = wrapper.findAll(".scene-lens__provenance-badge")
    expect(bordersTexts(badges)).toEqual(["有据", "来源待核实"])

    await wrapper.findAll("button").find((button) => button.text() === "字段来源").trigger("click")
    expect(wrapper.findComponent({ name: "SceneFieldProvenance" }).exists()).toBe(true)

    await wrapper.findAll("button").find((button) => button.text() === "收起来源").trigger("click")
    expect(wrapper.findComponent({ name: "SceneFieldProvenance" }).exists()).toBe(false)
  })

  it("renders the collapsed history entry as a secondary affordance", () => {
    const wrapper = mount(SceneLensSummary, {
      props: { scene, lens: { loading: false, error: null, data: lensData([fieldWithProvenance("exact")]) }, projectId: "p1" },
      global: { stubs: { SceneStateTrial: true } },
    })

    const entry = wrapper.find(".scene-checkpoint-history")
    expect(entry.exists()).toBe(true)
    expect(entry.attributes("open")).toBeUndefined()
    expect(entry.find("summary").text()).toBe("历史版本")
    // 折叠态不打扰：未展开时不拉取、不渲染空态文案。
    expect(wrapper.text()).not.toContain("本场还没有历史版本记录")
  })
})

function bordersTexts(badges) {
  return badges.map((badge) => badge.text())
}
