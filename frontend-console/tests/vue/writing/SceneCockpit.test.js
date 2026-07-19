import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it } from "vitest"
import SceneCockpit from "../../../vue/views/writing/components/SceneCockpit.vue"

const scene = {
  id: "s1",
  title: "Scene <script>",
  scene_index: 2,
  narrative_tag: "turn",
  goal: "找到线索",
  must_happen: "打开门",
  must_not_happen: "暴露身份",
  core_conflict: "时间不足",
  emotional_beat: "犹豫到决断",
  source: "第一章",
  foreshadowing: "钥匙",
}

function mountCockpit() {
  return mount(SceneCockpit, {
    props: {
      projectId: "p1",
      chapter: 1,
      scene,
      alerts: [{ code: "a1", severity: "high", source: "现场", message: "高风险 <img>" }],
      people: [{ id: "c1", name: "阿青 <script>", role: "POV" }],
      location: { id: "l1", name: "黑塔", description: "顶层" },
      mapSummary: {
        primary_location: { name: "黑塔" },
        characters: [{ name: "阿青" }],
        events: [{ name: "门打开" }],
        factions: [{ name: "守夜人" }],
        crises: [{ name: "倒计时" }],
        warnings: [{ code: "character_cross_map" }],
      },
      conflict: { latest: { id: "check-1" } },
    },
  })
}

describe("SceneCockpit", () => {
  beforeEach(() => localStorage.clear())

  it("在 Vue tabs 中渲染人物、地点、设定、地图和警报操作", async () => {
    const wrapper = mountCockpit()
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).toContain("Scene <script>")

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "人物").trigger("click")
    expect(wrapper.text()).toContain("阿青 <script>")
    await wrapper.findAll("button").find((button) => button.text() === "插入").trigger("click")
    expect(wrapper.emitted("insert-text")[0]).toEqual(["阿青 <script>"])

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "地图").trigger("click")
    expect(wrapper.text()).toContain("势力：守夜人")
    expect(wrapper.text()).toContain("人物上一场在其他地图")

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "警报").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "运行规则检查").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看最近校验").trigger("click")
    expect(wrapper.emitted("run-conflict")).toHaveLength(1)
    expect(wrapper.emitted("open-conflict")).toHaveLength(1)
  })

  it("支持模块折叠和持久化排序", async () => {
    const wrapper = mountCockpit()
    const goal = wrapper.get('[data-cockpit-module="goal"]')
    await goal.find(".scene-cockpit-module__head > button").trigger("click")
    expect(goal.classes()).toContain("is-collapsed")

    await goal.find('[aria-label="上移目标"]').trigger("click")
    expect(wrapper.findAll("[data-cockpit-module]")[0].attributes("data-cockpit-module")).toBe("goal")
    expect(JSON.parse(localStorage.getItem("writing_scene_cockpit_order:p1"))[0]).toBe("goal")
  })
})
