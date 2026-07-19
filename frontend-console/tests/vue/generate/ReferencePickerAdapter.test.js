import { afterEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

const picker = vi.hoisted(() => ({ destroy: vi.fn(), resolve: vi.fn(async () => []), setItems: vi.fn() }))
const createReferencePicker = vi.hoisted(() => vi.fn(() => picker))
vi.mock("../../../shared/referencePicker.js", () => ({ createReferencePicker }))
import ReferencePickerAdapter from "../../../vue/views/generate/components/ReferencePickerAdapter.vue"

enableAutoUnmount(afterEach)

describe("ReferencePickerAdapter narrow imperative seam", () => {
  it("owns and explicitly destroys the vanilla widget", () => {
    const wrapper = mount(ReferencePickerAdapter, { props: { projectId: "p1", sources: [{ kind: "entity", search: vi.fn() }], modelValue: [] } })
    expect(createReferencePicker).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(picker.destroy).toHaveBeenCalledOnce()
  })
})
