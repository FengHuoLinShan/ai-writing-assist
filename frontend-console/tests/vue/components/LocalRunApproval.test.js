import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import LocalRunApproval from "../../../vue/components/LocalRunApproval.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

describe("LocalRunApproval", () => {
  let pending, approve

  beforeEach(() => {
    vi.useFakeTimers()
    pending = vi.fn(async () => ({ items: [{ task_id: "task-1", label: "对象图片生成" }] }))
    approve = vi.fn(async () => ({}))
    setBridgeOverrides({ api: { localAgent: { pending, approve } } })
  })

  afterEach(() => {
    vi.useRealTimers()
    resetBridgeOverrides()
  })

  it("任务待确认时展示说明与勾选，确认后触发 approved 并隐藏", async () => {
    const wrapper = mount(LocalRunApproval, {
      props: { projectId: "p1", taskId: "task-1", executorKind: "codex", purpose: "对象图片生成" },
    })
    await flushPromises()
    expect(wrapper.text()).toContain("Codex")
    expect(wrapper.text()).toContain("请确认本机伴随程序正在运行")
    const button = wrapper.get("button")
    expect(button.attributes("disabled")).toBeDefined()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    expect(button.attributes("disabled")).toBeUndefined()
    await button.trigger("click")
    await flushPromises()
    expect(approve).toHaveBeenCalledWith("p1", "task-1")
    expect(wrapper.emitted("approved")).toHaveLength(1)
    expect(wrapper.find("section").exists()).toBe(false)
  })

  it("任务不在待确认列表时不展示", async () => {
    pending.mockResolvedValue({ items: [] })
    const wrapper = mount(LocalRunApproval, { props: { projectId: "p1", taskId: "task-1" } })
    await flushPromises()
    expect(wrapper.find("section").exists()).toBe(false)
  })

  it("按 3 秒轮询待确认状态，卸载后停止轮询", async () => {
    const wrapper = mount(LocalRunApproval, { props: { projectId: "p1", taskId: "task-1" } })
    await flushPromises()
    expect(pending).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(3000); await flushPromises()
    expect(pending).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    vi.advanceTimersByTime(9000); await flushPromises()
    expect(pending).toHaveBeenCalledTimes(2)
  })

  it("确认失败时就地展示错误", async () => {
    approve.mockRejectedValue(new Error("确认失败，请重试"))
    const wrapper = mount(LocalRunApproval, { props: { projectId: "p1", taskId: "task-1" } })
    await flushPromises()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get("button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("确认失败，请重试")
    expect(wrapper.find("section").exists()).toBe(true)
  })
})
