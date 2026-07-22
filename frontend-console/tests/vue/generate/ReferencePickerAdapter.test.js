import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

const picker = vi.hoisted(() => ({ destroy: vi.fn(), resolve: vi.fn(async () => []), setItems: vi.fn() }))
const createReferencePicker = vi.hoisted(() => vi.fn(() => picker))
vi.mock("../../../shared/referencePicker.js", () => ({ createReferencePicker }))
import ReferencePickerAdapter from "../../../vue/views/generate/components/ReferencePickerAdapter.vue"

enableAutoUnmount(afterEach)
beforeEach(() => vi.clearAllMocks())

describe("ReferencePickerAdapter narrow imperative seam", () => {
  it("owns and explicitly destroys the vanilla widget", () => {
    const wrapper = mount(ReferencePickerAdapter, { props: { projectId: "p1", sources: [{ kind: "entity", search: vi.fn() }], modelValue: [] } })
    expect(createReferencePicker).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(picker.destroy).toHaveBeenCalledOnce()
  })

  it("项目切换时销毁并按新 projectId 重建", async () => {
    const wrapper = mount(ReferencePickerAdapter, { props: { projectId: "p1", sources: [{ kind: "entity", search: vi.fn() }], modelValue: ["e1"] } })
    await flushPromises()
    await wrapper.setProps({ projectId: "p2" })
    await flushPromises()
    expect(createReferencePicker).toHaveBeenCalledTimes(2)
    expect(createReferencePicker.mock.calls[1][0].projectId).toBe("p2")
    expect(picker.destroy).toHaveBeenCalled()
    expect(picker.resolve).toHaveBeenLastCalledWith([{ kind: "entity", id: "e1" }])
  })

  it("连续同步时旧 resolve 先返回也不会提前解锁 onChange", async () => {
    const resolvers = new Map()
    picker.resolve.mockImplementation((refs) => new Promise((resolve) => {
      resolvers.set(refs[0].id, resolve)
    }))
    const wrapper = mount(ReferencePickerAdapter, {
      props: {
        projectId: "p1",
        sources: [{ kind: "entity", search: vi.fn() }],
        modelValue: ["e1"],
      },
    })
    await flushPromises()
    await wrapper.setProps({ modelValue: ["e2"] })
    await flushPromises()
    const onChange = createReferencePicker.mock.calls[0][0].onChange

    resolvers.get("e1")([])
    await flushPromises()
    onChange([], [{ kind: "entity", id: "user-choice" }])
    expect(wrapper.emitted("update:modelValue")).toBeUndefined()

    resolvers.get("e2")([])
    await flushPromises()
    onChange([], [{ kind: "entity", id: "user-choice" }])
    expect(wrapper.emitted("update:modelValue")).toEqual([[ ["user-choice"] ]])
  })
})
