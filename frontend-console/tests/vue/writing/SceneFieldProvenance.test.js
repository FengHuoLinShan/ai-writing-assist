import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { sceneFieldProvenance } from "../../../vue/views/writing/sceneLensModel.js"
import SceneFieldProvenance from "../../../vue/views/writing/components/SceneFieldProvenance.vue"

const hash = "a".repeat(64)

function exactProvenance() {
  return sceneFieldProvenance({
    field: "custody_holder",
    event_id: "event-1",
    status: "exact",
    source_refs: [{
      draft_id: "draft-1",
      chapter_index: 2,
      version_number: 1,
      content_mode: "working",
      start_offset: 10,
      end_offset: 24,
      source_hash: hash,
      range_hash: "b".repeat(64),
    }],
  })
}

describe("SceneFieldProvenance", () => {
  beforeEach(() => {
    setBridgeOverrides({})
  })
  afterEach(() => {
    resetBridgeOverrides()
    vi.restoreAllMocks()
  })

  it("renders the exact badge with the draft range in author language", () => {
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "保管人", provenance: exactProvenance() },
    })

    expect(wrapper.get(".scene-field-provenance__badge").text()).toBe("有据")
    expect(wrapper.text()).toContain("第 2 章 · 第 1 版工作稿 · 第 10–24 字")
    expect(wrapper.text()).toContain("诊断编号 event-1")
    expect(wrapper.text()).toContain("回看原文")
  })

  it("reopens the draft range through readEvidence and shows the excerpt", async () => {
    const readEvidence = vi.fn().mockResolvedValue({ text: "乙从甲手里接过铜钥匙。", highlight_start: 0, highlight_end: 10 })
    setBridgeOverrides({ api: { context: { readEvidence } } })
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "保管人", provenance: exactProvenance() },
    })

    await wrapper.get("button").trigger("click")

    expect(readEvidence).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      content_mode: "working",
      source_ref: expect.objectContaining({
        draft_id: "draft-1",
        chapter_index: 2,
        version_number: 1,
        start_offset: 10,
        end_offset: 24,
        source_hash: hash,
      }),
    }))
    expect(wrapper.get("blockquote").text()).toContain("乙从甲手里接过铜钥匙。")
  })

  it("keeps the failure copy honest when the draft cannot be read back", async () => {
    const readEvidence = vi.fn().mockRejectedValue(new Error("stale"))
    setBridgeOverrides({ api: { context: { readEvidence } } })
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "保管人", provenance: exactProvenance() },
    })

    await wrapper.get("button").trigger("click")
    await Promise.resolve()

    expect(wrapper.text()).toContain("原文暂时回读不到")
    expect(wrapper.find("blockquote").exists()).toBe(false)
  })

  it("states unverified without inventing precision", () => {
    const provenance = sceneFieldProvenance({
      field: "custody_owner",
      event_id: null,
      status: "unverified",
      source_refs: [],
    })
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "所有人", provenance },
    })

    expect(wrapper.get(".scene-field-provenance__badge").text()).toBe("来源待核实")
    expect(wrapper.text()).toContain("来源待核实：这条状态暂时没有追到具体稿件段落，不会当作已核对的事实。")
    expect(wrapper.find("button").exists()).toBe(false)
  })

  it("states conflict without picking a winner", () => {
    const provenance = sceneFieldProvenance({
      field: "opening_key_id",
      event_id: "event-2",
      status: "conflict",
      source_refs: [],
    })
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "所需钥匙", provenance },
    })

    expect(wrapper.get(".scene-field-provenance__badge").text()).toBe("来源冲突")
    expect(wrapper.text()).toContain("多条记录相互冲突，尚未人工核实；请以正文为准。")
  })

  it("does not offer reopening when the range lacks fingerprints", () => {
    const provenance = sceneFieldProvenance({
      field: "location_id",
      status: "exact",
      source_refs: [{
        draft_id: "draft-1",
        chapter_index: 1,
        version_number: 1,
        content_mode: "working",
        start_offset: 0,
        end_offset: 5,
      }],
    })
    const wrapper = mount(SceneFieldProvenance, {
      props: { projectId: "p1", fieldLabel: "所在", provenance },
    })

    expect(wrapper.text()).toContain("第 1 章 · 第 1 版工作稿 · 第 0–5 字")
    expect(wrapper.find("button").exists()).toBe(false)
  })
})
