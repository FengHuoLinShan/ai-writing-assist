/**
 * EditorialDesk 测试 — 编辑约定保存的编辑审读失效守卫。
 */
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"

import EditorialDesk from "../../../vue/components/EditorialDesk.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const BRIEF = {
  version: 1,
  brief: {
    target_readers: "", genre_promise: "", goals: [], voice: "",
    preserve: [], intentional_choices: [], excluded_targets: [],
  },
}
const POLICY = { feature_available: true, enabled: false, automatic_available: true, excluded_chapters: [], generation: 1 }

function activeReview(id = "rev-1") {
  return {
    id, status: "running", scope: { scope: "book", start_chapter: 1, end_chapter: null },
    checked_chapters: [], unchecked_chapters: [1], missing: [],
    context_sources: [], context_omissions: [], report: null, error: null, brief_changed: false,
  }
}

let apiMock
let confirmMock

beforeEach(() => {
  confirmMock = vi.fn(() => true)
  apiMock = {
    projects: {
      editorialBrief: vi.fn(async () => BRIEF),
      saveEditorialBrief: vi.fn(async (_projectId, body) => ({ version: 2, brief: body.brief })),
      editorialBriefForWriting: vi.fn(async () => ({ enabled: false, brief: null })),
      setEditorialBriefForWriting: vi.fn(async (_projectId, enabled) => ({ enabled })),
    },
    assistant: {
      editorialPolicy: vi.fn(async () => POLICY),
      editorialReviews: vi.fn(async () => [activeReview()]),
      editorialIssues: vi.fn(async () => []),
    },
  }
  setBridgeOverrides({ api: apiMock, confirm: confirmMock, state: { currentProjectId: "p1" } })
})

afterEach(() => resetBridgeOverrides())

async function mountDesk() {
  const wrapper = mount(EditorialDesk, { props: { projectId: "p1", active: true } })
  await flushPromises()
  return wrapper
}

function saveBriefButton(wrapper) {
  const button = wrapper.findAll("button").find((item) => item.text() === "保存编辑约定")
  if (!button) throw new Error("保存编辑约定按钮未找到")
  return button
}

describe("EditorialDesk saveBrief", () => {
  it("有进行中审读时保存编辑约定会先确认；取消则不保存", async () => {
    confirmMock.mockReturnValue(false)
    const wrapper = await mountDesk()

    await saveBriefButton(wrapper).trigger("click")
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining("编辑审读"))
    expect(apiMock.projects.saveEditorialBrief).not.toHaveBeenCalled()
  })

  it("确认后正常保存编辑约定", async () => {
    confirmMock.mockReturnValue(true)
    const wrapper = await mountDesk()

    await saveBriefButton(wrapper).trigger("click")
    await flushPromises()

    expect(apiMock.projects.saveEditorialBrief).toHaveBeenCalled()
  })

  it("没有进行中审读时保存不弹确认框", async () => {
    apiMock.assistant.editorialReviews.mockResolvedValue([])
    const wrapper = await mountDesk()

    await saveBriefButton(wrapper).trigger("click")
    await flushPromises()

    expect(confirmMock).not.toHaveBeenCalled()
    expect(apiMock.projects.saveEditorialBrief).toHaveBeenCalled()
  })
})

describe("EditorialDesk 写作开关", () => {
  function writingToggleInput(wrapper) {
    return wrapper.get(".editorial-desk__writing-toggle input[type='checkbox']")
  }

  it("首次开启且约定有内容时，不误报约定还是空的", async () => {
    apiMock.projects.setEditorialBriefForWriting.mockResolvedValue({
      enabled: true,
      effective: true,
    })
    const wrapper = await mountDesk()

    await writingToggleInput(wrapper).setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain("已开启：这份约定将进入 AI 正文建议与续写的参考资料确认。")
    expect(wrapper.text()).not.toContain("开关已开启，但编辑约定还是空的")
  })

  it("开启但约定为空时明确提示需要先保存约定", async () => {
    apiMock.projects.setEditorialBriefForWriting.mockResolvedValue({
      enabled: true,
      effective: false,
    })
    const wrapper = await mountDesk()

    await writingToggleInput(wrapper).setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain("已开启，但编辑约定还是空的")
    expect(wrapper.text()).toContain("开关已开启，但编辑约定还是空的")
  })

  it("切换项目后迟到的开关回包不写入当前项目状态", async () => {
    let resolveToggle
    apiMock.projects.setEditorialBriefForWriting.mockImplementation(
      () => new Promise((resolve) => { resolveToggle = resolve })
    )
    const wrapper = await mountDesk()

    await writingToggleInput(wrapper).setValue(true)
    await wrapper.setProps({ projectId: "p2" })
    resolveToggle({ enabled: true, effective: true })
    await flushPromises()

    expect(wrapper.text()).not.toContain("已开启：这份约定将进入")
    expect(writingToggleInput(wrapper).element.checked).toBe(false)
    // 迟到回包仍要解除处理中，新项目的开关不能一直不可点
    expect(writingToggleInput(wrapper).element.disabled).toBe(false)
  })

  it("说明角色视角建议不使用编辑约定", async () => {
    const wrapper = await mountDesk()

    expect(wrapper.get(".editorial-desk__writing-toggle").text()).toContain(
      "「AI 角色视角建议」不使用它"
    )
  })

  it("active 时轮询意见；切项目重启轮询且不重复起表，卸载后停表", async () => {
    vi.useFakeTimers()
    try {
      const reviewsCalls = () => apiMock.assistant.editorialReviews.mock.calls.length
      const callsWith = (projectId) => apiMock.assistant.editorialReviews.mock.calls
        .filter(([id]) => id === projectId).length

      const wrapper = mount(EditorialDesk, { props: { projectId: "p1", active: true } })
      await flushPromises()
      expect(reviewsCalls()).toBe(1)

      vi.advanceTimersByTime(8000)
      expect(callsWith("p1")).toBe(2)

      // 仍 active 时切换项目：load() 拉新项目一次，旧 interval 被清除、起新表。
      await wrapper.setProps({ projectId: "p2" })
      await flushPromises()
      expect(callsWith("p2")).toBe(1)

      vi.advanceTimersByTime(8000)
      expect(callsWith("p2")).toBe(2)
      expect(callsWith("p1")).toBe(2)

      // 同一项目失活再激活：只重起一个 interval，不叠加。
      await wrapper.setProps({ active: false })
      await flushPromises()
      await wrapper.setProps({ active: true })
      await flushPromises()
      const before = reviewsCalls()
      vi.advanceTimersByTime(8000)
      expect(reviewsCalls()).toBe(before + 1)

      wrapper.unmount()
      vi.advanceTimersByTime(8000 * 10)
      expect(reviewsCalls()).toBe(before + 1)
    } finally {
      vi.useRealTimers()
    }
  })
})
