import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ProactiveCare from "../../../vue/components/ProactiveCare.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let wrapper, api
beforeEach(() => {
  api = {
    carePolicy: vi.fn(async () => ({ available: true, policy: { enabled: false, categories: ["writing"], allow_web: false, daily_limit: 12, excluded_targets: [] }, pending_count: 0 })),
    careNotices: vi.fn(async () => ({ items: [{ id: "notice-1", title: "年龄待核对", summary: "两处年龄不同", status: "unread", source: { target: { type: "writing_draft", id: "draft-1" } } }] })),
    saveCarePolicy: vi.fn(), decideCareNotice: vi.fn(async () => ({})),
  }
  setBridgeOverrides({ api: { assistant: api } })
})
afterEach(() => { wrapper?.unmount(); resetBridgeOverrides() })

it("does not claim saved or discard policy edits on failure and reminder refresh", async () => {
  wrapper = mount(ProactiveCare, { props: { targetId: "p1" } })
  await flushPromises()
  expect(wrapper.text()).toContain("1 项待看")
  await wrapper.find('input[type="number"]').setValue("3")
  api.saveCarePolicy.mockRejectedValue(new Error("offline"))
  await wrapper.find("form").trigger("submit")
  await flushPromises()
  expect(wrapper.text()).toContain("设置未保存")
  expect(wrapper.text()).not.toContain("设置已保存")
  await wrapper.findAll("button").find(button => button.text() === "刷新提醒").trigger("click")
  await flushPromises()
  expect(wrapper.find('input[type="number"]').element.value).toBe("3")
  await wrapper.findAll("button").find(button => button.text() === "这是刻意安排").trigger("click")
  await flushPromises()
  expect(api.decideCareNotice).toHaveBeenCalledWith("p1", "notice-1", { action: "intentional" })
  expect(wrapper.text()).not.toContain("年龄待核对")
})

it("discards reminder responses from a previously selected project", async () => {
  let finish
  api.careNotices.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  wrapper = mount(ProactiveCare, { props: { targetId: "p1" } })
  await flushPromises()
  api.careNotices.mockResolvedValue({ items: [] })
  await wrapper.setProps({ targetId: "p2" })
  await flushPromises()
  finish({ items: [{ id: "old", title: "上一作品私密提醒", status: "unread" }] })
  await flushPromises()
  expect(wrapper.text()).not.toContain("上一作品私密提醒")
})
