import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import ChapterTree from "../../../vue/views/writing/components/ChapterTree.vue"

enableAutoUnmount(afterEach)

describe("ChapterTree", () => {
  it("只按顺序显示章节，并保留底部唯一新建入口和外附收起条", async () => {
    const wrapper = mount(ChapterTree, {
      props: {
        chapterList: [1, 3],
        chapters: {
          1: { title: "开端", word_count: 100 },
          3: { title: "归潮", word_count: 300 },
        },
        selectedChapter: 3,
      },
    })

    expect(wrapper.get(".chapter-tree-title").text()).toBe("共 2 章")
    expect(wrapper.findAll(".chapter-row").map((row) => row.text())).toEqual([
      expect.stringContaining("第 1 章开端"),
      expect.stringContaining("第 3 章归潮"),
    ])
    expect(wrapper.find(".scene-tree-label").exists()).toBe(false)
    expect(wrapper.findAll(".chapter-tree-create")).toHaveLength(1)
    expect(wrapper.findAll('[aria-label="新建章节"]')).toHaveLength(1)
    expect(wrapper.get('.chapter-title-text[title="归潮"]').exists()).toBe(true)

    await wrapper.get('[aria-label="打开第 1 章：开端，100 字"]').trigger("click")
    expect(wrapper.emitted("select")).toEqual([[1]])
    await wrapper.get('[aria-label="收起章节目录"]').trigger("click")
    expect(wrapper.emitted("toggle-collapse")).toHaveLength(1)
    await wrapper.setProps({ collapsed: true })
    expect(wrapper.get('[aria-label="展开章节目录"]').text()).toContain("展开")
    expect(wrapper.find(".chapter-tree-card").exists()).toBe(false)
  })
})
