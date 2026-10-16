import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import OutlineFloat from "../../../vue/views/writing/components/OutlineFloat.vue"

enableAutoUnmount(afterEach)

function model(overrides = {}) {
  return {
    open: true,
    loading: false,
    error: null,
    threads: [{ id: "thread-1", title: "归潮线", chapter_ids: [1, "3"] }],
    ...overrides,
  }
}

describe("OutlineFloat", () => {
  it("names the complementary float, close control, and mapped chapter links", async () => {
    const wrapper = mount(OutlineFloat, { props: { model: model(), currentChapter: 3 } })

    expect(wrapper.find('[aria-label="大纲浮窗"]').exists()).toBe(true)

    const close = wrapper.get('[aria-label="关闭大纲浮窗"]')
    expect(close.attributes("type")).toBe("button")
    await close.trigger("click")
    expect(wrapper.emitted("close")).toHaveLength(1)

    const firstChapter = wrapper.get('[aria-label="打开第 1 章"]')
    const currentChapter = wrapper.get('[aria-label="打开第 3 章"]')
    expect(firstChapter.attributes("type")).toBe("button")
    expect(firstChapter.attributes("aria-current")).toBeUndefined()
    expect(currentChapter.attributes("aria-current")).toBe("true")
    await currentChapter.trigger("click")
    expect(wrapper.emitted("select")).toEqual([[3]])
  })

  it("announces loading and errors with their existing text", () => {
    const loading = mount(OutlineFloat, { props: { model: model({ loading: true, threads: [] }) } })
    expect(loading.get('[role="status"]').text()).toBe("加载中...")
    const error = mount(OutlineFloat, { props: { model: model({ error: "大纲读取失败", threads: [] }) } })
    expect(error.get('[role="alert"]').text()).toBe("大纲读取失败")
  })

  it("shows author plan separately from verified cutoff prose and emits explicit confirmation", async () => {
    const id = "character-private-test-id"
    const wrapper = mount(OutlineFloat, {
      props: {
        model: model({
          characterArcs: [{
            character_id: id,
            character_name: "沈禾",
            is_pov: true,
            comparison: {
              cutoff: { chapter_cutoff: 4 },
              coverage: "partial",
              plan: {
                version: 2,
                source: "author_confirmed",
                plan_text: "在失去同伴后学会请求帮助。",
              },
              plan_archived: false,
              actual_events: [{
                chapter_index: 3,
                source_label: "第 3 章正式正文",
                field: "求助行为",
                value: "向同伴求援",
                quote: "她终于叫住了正要离开的同伴。",
                range_hash: "range",
              }],
              unknowns: ["第 4 章的某些状态尚未验证。"],
            },
          }],
          arcDrafts: { [id]: "开始愿意向同伴求助。" },
          arcPreviews: { [id]: { expected_version: 2, proposed_plan_text: "开始愿意向同伴求助。" } },
        }),
        currentChapter: 4,
        currentScene: { id: "scene-private-id", title: "雨夜", scene_index: 4, chapter_ids: [4] },
      },
    })

    expect(wrapper.text()).toContain("人物弧线：作者计划 / 实际对照")
    expect(wrapper.text()).toContain("作者确认计划")
    expect(wrapper.text()).toContain("仅供导演")
    expect(wrapper.text()).toContain("第 3 章正式正文")
    expect(wrapper.text()).toContain("她终于叫住了正要离开的同伴。")
    expect(wrapper.text()).toContain("未知与缺口（1）")
    expect(wrapper.text()).not.toContain(id)
    expect(wrapper.text()).not.toContain("scene-private-id")
    await wrapper.get("button.btn-primary").trigger("click")
    expect(wrapper.emitted("confirm-arc")).toEqual([[id]])
  })
})
