import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import AIResultTraceDetails from "../../../vue/components/AIResultTraceDetails.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function confirmation(overrides = {}) {
  return {
    id: "confirmation-1",
    task: "生成正文建议",
    scope: "chapter",
    compiled_at: "2026-09-16T05:00:00Z",
    selected_asset_ids: { writing_drafts: ["draft-source"], world_entities: ["entity-1"] },
    result_refs: [
      { type: "task", id: "task-1" },
      { type: "writing_draft", id: "draft-1" },
    ],
    result_status: "adopted",
    stale_reasons: ["source_changed"],
    ...overrides,
  }
}

function task(overrides = {}) {
  return {
    task_id: "task-1",
    task_type: "writing_generate",
    status: "done",
    result: { knowledge_review: { status: "passed", issues: [] } },
    operation: {
      version: 1,
      submission_mode: "exact_operation",
      stage: "reviewing",
      error_code: null,
      retryable: false,
      possible_charge: true,
      partial_result: true,
      available_actions: ["dismiss"],
    },
    ...overrides,
  }
}

async function openTrace(wrapper) {
  const details = wrapper.get("details")
  details.element.open = true
  await details.trigger("toggle")
  await flushPromises()
}

afterEach(() => resetBridgeOverrides())

describe("AIResultTraceDetails", () => {
  it("组合展示资料、运行、复核、失效和成果，不暴露 raw ID", async () => {
    const navigate = vi.fn(() => true)
    setBridgeOverrides({
      api: {
        context: { getConfirmation: vi.fn(async () => confirmation()) },
        tasks: { get: vi.fn(async () => task()) },
      },
      router: { navigate },
    })
    const wrapper = mount(AIResultTraceDetails, {
      props: { projectId: "novel-1", confirmationId: "confirmation-1", taskId: "task-1" },
    })

    await openTrace(wrapper)

    expect(wrapper.text()).toContain("正文 1")
    expect(wrapper.text()).toContain("世界资料 1")
    expect(wrapper.text()).toContain("已采用")
    expect(wrapper.text()).toContain("可能已产生调用费用")
    expect(wrapper.text()).toContain("保留了部分成果")
    expect(wrapper.text()).toContain("可用操作：关闭运行记录")
    expect(wrapper.text()).toContain("知识复核")
    expect(wrapper.text()).toContain("当时依据后来已变化")
    expect(wrapper.text()).not.toContain("draft-1")
    await wrapper.get(".ai-result-trace__actions button").trigger("click")
    expect(navigate).toHaveBeenCalled()
  })

  it("Task 已不可用时仍展示 Confirmation 与成果", async () => {
    setBridgeOverrides({
      api: {
        context: { getConfirmation: vi.fn(async () => confirmation({ stale_reasons: [] })) },
        tasks: { get: vi.fn(async () => { throw new Error("not found") }) },
      },
      router: { navigate: vi.fn(() => true) },
    })
    const wrapper = mount(AIResultTraceDetails, {
      props: { projectId: "novel-1", confirmationId: "confirmation-1", taskId: "task-1" },
    })

    await openTrace(wrapper)

    expect(wrapper.text()).toContain("运行详情已不可用")
    expect(wrapper.text()).toContain("打开正文成果")
  })

  it("Confirmation 读取失败可就地重试", async () => {
    const getConfirmation = vi.fn()
      .mockRejectedValueOnce(new Error("网络暂时不可用"))
      .mockResolvedValueOnce(confirmation({ stale_reasons: [] }))
    setBridgeOverrides({
      api: { context: { getConfirmation }, tasks: { get: vi.fn(async () => task()) } },
    })
    const wrapper = mount(AIResultTraceDetails, {
      props: { projectId: "novel-1", confirmationId: "confirmation-1", taskId: "task-1" },
    })

    await openTrace(wrapper)
    expect(wrapper.get("[role='alert']").text()).toContain("网络暂时不可用")
    await wrapper.get("[role='alert'] button").trigger("click")
    await flushPromises()
    expect(getConfirmation).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("正文 1")
  })

  it("首次展开显示加载状态", async () => {
    let resolveConfirmation
    setBridgeOverrides({
      api: {
        context: { getConfirmation: vi.fn(() => new Promise((resolve) => { resolveConfirmation = resolve })) },
        tasks: { get: vi.fn(async () => task()) },
      },
    })
    const wrapper = mount(AIResultTraceDetails, {
      props: { projectId: "novel-1", confirmationId: "confirmation-1", taskId: "task-1" },
    })

    const details = wrapper.get("details")
    details.element.open = true
    await details.trigger("toggle")
    expect(wrapper.get("[role='status']").text()).toContain("正在读取记录")
    resolveConfirmation(confirmation())
    await flushPromises()
  })

  it("兼容旧记录与未知成果类型，不显示 raw ID", async () => {
    setBridgeOverrides({
      api: {
        context: {
          getConfirmation: vi.fn(async () => confirmation({
            selected_asset_ids: {},
            result_refs: [{ type: "legacy_result", id: "private-result-id" }],
            result_status: "legacy_state",
            stale_reasons: [],
          })),
        },
        tasks: {
          get: vi.fn(async () => ({
            task_id: "task-1",
            task_type: "writing_generate",
            status: "failed",
            error_message: "运行暂时失败",
            available_actions: ["restart_origin"],
            result: {},
          })),
        },
      },
      router: { navigate: vi.fn(() => false) },
      toast: vi.fn(),
    })
    const wrapper = mount(AIResultTraceDetails, {
      props: { projectId: "novel-1", confirmationId: "confirmation-1", taskId: "task-1" },
    })

    await openTrace(wrapper)

    expect(wrapper.text()).toContain("旧记录未保留可展示的资料分组")
    expect(wrapper.text()).toContain("已保留运行记录")
    expect(wrapper.text()).toContain("运行暂时失败")
    expect(wrapper.text()).toContain("回到原页面重新开始")
    expect(wrapper.text()).toContain("打开第 1 项成果")
    expect(wrapper.text()).not.toContain("private-result-id")
  })
})
