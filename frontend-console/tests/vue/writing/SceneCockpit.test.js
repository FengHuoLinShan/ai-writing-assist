import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
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

function mountCockpit(overrides = {}) {
  return mount(SceneCockpit, {
    props: {
      projectId: "p1",
      chapter: 1,
      scene,
      scenes: [scene],
      allScenes: [scene],
      alerts: [{ code: "a1", severity: "high", source: "现场", message: "高风险 <img>" }],
      people: [{ id: "c1", name: "阿青 <script>", role: "POV" }],
      location: { id: "l1", name: "黑塔", description: "顶层" },
      conflict: { latest: { id: "check-1" } },
      ...overrides,
    },
  })
}

describe("SceneCockpit", () => {
  beforeEach(() => localStorage.clear())

  it("在 Vue tabs 中渲染人物、地点、设定和警报操作", async () => {
    const wrapper = mountCockpit()
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).toContain("Scene <script>")

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "人物").trigger("click")
    expect(wrapper.text()).toContain("阿青 <script>")
    await wrapper.findAll("button").find((button) => button.text() === "插入").trigger("click")
    expect(wrapper.emitted("insert-text")[0]).toEqual(["阿青 <script>"])

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "警报").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "运行规则检查").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看最近校验").trigger("click")
    expect(wrapper.emitted("run-conflict")).toHaveLength(1)
    expect(wrapper.emitted("open-conflict")).toHaveLength(1)
  })

  it("默认显示白名单本场摘要，扩展资料需显式点击", async () => {
    const wrapper = mountCockpit({
      scene: {
        ...scene,
        structure_meta: { outcome: "拿到钥匙", private_prompt: "不应展示" },
      },
    })
    expect(wrapper.get(".scene-lens").text()).toContain("拿到钥匙")
    expect(wrapper.text()).not.toContain("不应展示")
    expect(wrapper.emitted("load-lens")).toBeUndefined()
    await wrapper.get(".scene-lens__load button").trigger("click")
    expect(wrapper.emitted("load-lens")).toHaveLength(1)
  })

  it("扩展资料失败时保留静态摘要并可重试", async () => {
    const wrapper = mountCockpit({
      lens: { loading: false, data: null, error: "网络暂时不可用" },
    })
    expect(wrapper.get(".scene-lens").text()).toContain("找到线索")
    expect(wrapper.get(".scene-lens").text()).toContain("静态摘要已保留")
    await wrapper.get(".scene-lens__load button").trigger("click")
    expect(wrapper.emitted("load-lens")).toHaveLength(1)
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

  it("由写作副驾驶内层标题发出 rail 折叠请求", async () => {
    const wrapper = mountCockpit()
    await wrapper.get('[aria-label="收起写作副驾驶"]').trigger("click")
    expect(wrapper.emitted("toggle-collapse")).toHaveLength(1)

    await wrapper.setProps({ railCollapsed: true })
    expect(wrapper.classes()).toContain("is-collapsed")
    expect(wrapper.find(".cockpit-tabs").exists()).toBe(false)
    expect(wrapper.get('[aria-label="展开写作副驾驶"]').attributes("aria-expanded")).toBe("false")
  })

  it("在顶部手选本章 Scene，跨章只作标记", async () => {
    const crossChapter = { ...scene, id: "s2", title: "跨章会面", chapter_ids: ["1", "2"] }
    const wrapper = mountCockpit({ scenes: [scene, crossChapter], allScenes: [scene, crossChapter] })

    expect(wrapper.findAll(".scene-cockpit-switcher__item")).toHaveLength(2)
    expect(wrapper.findAll(".scene-cockpit-switcher__item")[1].text()).toContain("跨章")
    await wrapper.findAll(".scene-cockpit-switcher__item")[1].trigger("click")
    expect(wrapper.emitted("select-scene")[0]).toEqual(["s2"])
  })

  it("关联弹窗支持连续关联、新建以及打开工作台", async () => {
    const associateScene = vi.fn(async () => ({ id: "s2" }))
    const createScene = vi.fn(async () => ({ id: "s3" }))
    const unlinked = { id: "s2", title: "旅店暗号", scene_index: 3, status: "draft", chapter_ids: [] }
    const wrapper = mountCockpit({ allScenes: [scene, unlinked], associateScene, createScene })

    await wrapper.findAll("button").find((button) => button.text().includes("关联 Scene")).trigger("click")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(associateScene).toHaveBeenCalledWith("s2")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
    await wrapper.setProps({ allScenes: [scene, { ...unlinked, chapter_ids: ["1"] }] })
    expect(wrapper.get('[aria-label="旅店暗号已关联"]').text()).toBe("✓")

    await wrapper.findAll("button").find((button) => button.text().includes("新建 Scene")).trigger("click")
    await wrapper.get("#scene-associate-title-input").setValue("  钟楼会面  ")
    await wrapper.get(".scene-associate-create").trigger("submit")
    expect(createScene).toHaveBeenCalledWith("钟楼会面")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)

    await wrapper.findAll("button").find((button) => button.text().includes("打开 Scene 工作台")).trigger("click")
    expect(wrapper.emitted("organize")).toHaveLength(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it("关联失败时保留当前行并可原位重试", async () => {
    const associateScene = vi.fn()
      .mockRejectedValueOnce(new Error("网络暂时不可用"))
      .mockResolvedValueOnce({ id: "s2" })
    const unlinked = { id: "s2", title: "旅店暗号", scene_index: 3, status: "draft", chapter_ids: [] }
    const wrapper = mountCockpit({ allScenes: [scene, unlinked], associateScene })
    await wrapper.findAll("button").find((button) => button.text().includes("关联 Scene")).trigger("click")

    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(wrapper.text()).toContain("网络暂时不可用")
    expect(wrapper.get('[aria-label="关联 旅店暗号"]').exists()).toBe(true)
    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(associateScene).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
  })
})
