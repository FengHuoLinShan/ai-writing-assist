import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import ChapterTree from "../../../vue/views/writing/components/ChapterTree.vue"

enableAutoUnmount(afterEach)

describe("ChapterTree", () => {
  it("names chapter and Scene navigation while preserving select and toggle state", async () => {
    const wrapper = mount(ChapterTree, {
      props: {
        chapterList: [1, 3],
        chapters: {
          1: { title: "开端", word_count: 100 },
          3: { title: "归潮", word_count: 300 },
        },
        scenes: [{ id: "scene-1", title: "回声仓", chapter_ids: ["1", "3"] }],
        selectedChapter: 3,
      },
    })

    const previous = wrapper.get('[aria-label="上一章"]')
    const next = wrapper.get('[aria-label="下一章"]')
    expect(previous.attributes("type")).toBe("button")
    expect(previous.attributes("disabled")).toBeUndefined()
    expect(next.attributes("type")).toBe("button")
    expect(next.attributes("disabled")).toBeDefined()
    await previous.trigger("click")
    expect(wrapper.emitted("select")).toEqual([[1]])

    await wrapper.setProps({ selectedChapter: 1 })
    expect(previous.attributes("disabled")).toBeDefined()
    expect(next.attributes("disabled")).toBeUndefined()
    await wrapper.setProps({ selectedChapter: null })
    const sceneToggle = wrapper.get('[aria-label="收起 Scene 回声仓的章节"]')
    expect(sceneToggle.attributes("aria-expanded")).toBe("true")
    await sceneToggle.trigger("click")
    const collapsedToggle = wrapper.get('[aria-label="展开 Scene 回声仓的章节"]')
    expect(collapsedToggle.attributes("aria-expanded")).toBe("false")
    await collapsedToggle.trigger("click")
    expect(wrapper.get('[aria-label="收起 Scene 回声仓的章节"]').attributes("aria-expanded")).toBe("true")
  })
})
