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

    const panel = wrapper.get('aside[aria-label="大纲浮窗"]')
    expect(panel.element.tagName).toBe("ASIDE")
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
})
