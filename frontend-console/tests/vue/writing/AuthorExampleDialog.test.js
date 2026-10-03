import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import AuthorExampleDialog from "../../../vue/views/writing/components/AuthorExampleDialog.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

function mountDialog(props = {}) {
  return mount(AuthorExampleDialog, {
    attachTo: document.body,
    props: {
      open: false,
      projectId: "p1",
      draft: { content: "月光把巷子洗成了铅白色。", chapterIndex: 2, title: "第二章", candidateId: null },
      ...props,
    },
  })
}

async function openDialog(wrapper) {
  await wrapper.setProps({ open: true })
  await flushPromises()
}

beforeEach(() => {
  setBridgeOverrides({
    api: {
      projects: {
        authorExamples: vi.fn(async () => ({ version: 0, examples: [] })),
        saveAuthorExamples: vi.fn(async () => ({ version: 1, examples: [] })),
      },
    },
    toast: vi.fn(),
  })
})

afterEach(() => {
  resetBridgeOverrides()
  document.body.innerHTML = ""
})

describe("AuthorExampleDialog", () => {
  it("进入时把焦点移入对话框，关闭后还原", async () => {
    const origin = document.createElement("button")
    document.body.appendChild(origin)
    origin.focus()

    const wrapper = mountDialog()
    await openDialog(wrapper)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.find('[role="dialog"]').element.contains(document.activeElement)).toBe(true)

    await wrapper.setProps({ open: false })
    expect(document.activeElement).toBe(origin)
  })

  it("Esc 关闭对话框", async () => {
    const wrapper = mountDialog()
    await openDialog(wrapper)
    await wrapper.find('[role="dialog"]').trigger("keydown", { key: "Escape" })
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("Tab 在对话框内循环，不逃逸", async () => {
    const wrapper = mountDialog()
    await openDialog(wrapper)
    const dialog = wrapper.find('[role="dialog"]')

    await dialog.trigger("keydown", { key: "Tab" })
    const focused = document.activeElement
    expect(dialog.element.contains(focused)).toBe(true)
    const focusables = Array.from(
      dialog.element.querySelectorAll("input:not([disabled]), textarea:not([disabled]), button:not([disabled])")
    )
    expect(focusables.length).toBeGreaterThan(1)
    // 从最后一个控件 Tab 应回到第一个
    focusables[focusables.length - 1].focus()
    await dialog.trigger("keydown", { key: "Tab" })
    expect(document.activeElement).toBe(focusables[0])
    // Shift+Tab 从第一个应回到最后一个
    focusables[0].focus()
    await dialog.trigger("keydown", { key: "Tab", shiftKey: true })
    expect(document.activeElement).toBe(focusables[focusables.length - 1])
  })
})
