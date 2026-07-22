import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneMemoryRepairPanel from "../../../vue/views/map/components/SceneMemoryRepairPanel.vue"

function checkpoint(overrides = {}) {
  return {
    id: "cp-map",
    novel_id: "p1",
    scene_id: "s1",
    scene_index: 2,
    stage_index: 3,
    dimension: "map",
    status: "manual_required",
    source: "system_generated",
    confirmed: false,
    display_summary: "地图事实 2 条",
    gap_reason: "1 条已采用地图事实缺少 Scene 锚点",
    evidence_refs: [{ type: "map_fact", id: "f1", label: "港口仍被封锁" }],
    ...overrides,
  }
}

describe("SceneMemoryRepairPanel", () => {
  let api
  let toast
  let wrapper

  beforeEach(() => {
    api = {
      memory: {
        ensureSceneCheckpoints: vi.fn(async () => ({
          novel_id: "p1",
          scene_id: "s1",
          scene_index: 2,
          scene_title: "雾港封锁",
          coverage_status: "manual_required",
          items: [checkpoint()],
          missing_dimensions: [],
        })),
        repairSceneCheckpoint: vi.fn(async () => ({ checkpoint: checkpoint({ status: "ready", source: "manual" }) })),
      },
    }
    toast = vi.fn()
    setBridgeOverrides({ api, toast })
  })

  afterEach(() => {
    wrapper?.unmount()
    resetBridgeOverrides()
  })

  it("presents evidence, current fact, and one primary repair decision", async () => {
    wrapper = mount(SceneMemoryRepairPanel, { props: { projectId: "p1", sceneId: "s1" } })
    await vi.waitFor(() => expect(wrapper.text()).toContain("雾港封锁"))

    expect(wrapper.text()).toContain("当前事实")
    expect(wrapper.text()).toContain("地图事实 2 条")
    expect(wrapper.text()).toContain("查看来源证据 1 条")
    expect(wrapper.text()).toContain("你的决定")
    expect(wrapper.findAll("button.btn-primary")).toHaveLength(1)
    expect(wrapper.html()).not.toContain("state_json")
    expect(wrapper.html()).toMatchSnapshot()
  })

  it("submits a plain-language repair and confirmation", async () => {
    wrapper = mount(SceneMemoryRepairPanel, { props: { projectId: "p1", sceneId: "s1" } })
    await vi.waitFor(() => expect(wrapper.text()).toContain("需要判断"))
    await wrapper.find('input[value="replace_with_summary"]').setValue(true)
    await wrapper.find('textarea[rows="4"]').setValue("人物仍在旧港，北门保持封锁")
    await wrapper.find('textarea[rows="2"]').setValue("按 Scene 正文核对")
    await wrapper.find("form").trigger("submit")

    await vi.waitFor(() => expect(api.memory.repairSceneCheckpoint).toHaveBeenCalled())
    expect(api.memory.repairSceneCheckpoint).toHaveBeenCalledWith("p1", {
      scene_id: "s1",
      dimension: "map",
      expected_checkpoint_id: "cp-map",
      decision: "replace_with_summary",
      decision_summary: "按 Scene 正文核对",
      replacement_summary: "人物仍在旧港，北门保持封锁",
      confirmed: true,
    })
  })

  it("reloads current facts when the checkpoint changed before confirmation", async () => {
    api.memory.repairSceneCheckpoint.mockRejectedValueOnce(
      Object.assign(new Error("请求冲突"), { status: 409 }),
    )
    wrapper = mount(SceneMemoryRepairPanel, { props: { projectId: "p1", sceneId: "s1" } })
    await vi.waitFor(() => expect(wrapper.text()).toContain("需要判断"))
    await wrapper.find('textarea[rows="2"]').setValue("正文核对")
    await wrapper.find("form").trigger("submit")

    await vi.waitFor(() => expect(api.memory.ensureSceneCheckpoints).toHaveBeenCalledTimes(2))
    expect(toast).toHaveBeenCalledWith(
      "阶段事实已更新，请核对最新内容后再确认",
      "warning",
    )
  })
})
