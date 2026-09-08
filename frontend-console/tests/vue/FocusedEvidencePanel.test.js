import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import FocusedEvidencePanel from "../../vue/components/FocusedEvidencePanel.vue"
import TargetedCompletionPanel from "../../vue/components/TargetedCompletionPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import { recoverActiveWorkflows } from "../../shared/workflowProgress.js"

enableAutoUnmount(afterEach)
const sourceRef = { kind: "source_range", source_ref: { draft_id: "draft-1", chapter_index: 1, source_hash: "a".repeat(64), range_hash: "b".repeat(64), start_offset: 0, end_offset: 8 } }
const result = (overrides = {}) => ({
  targets: [{ key: "root-1", name: "沈岚", depth: 0, resolution: "resolved" }],
  evidence: [{ key: "e1", text: "<img src=x>沈岚抵达北港。", source_ref: sourceRef.source_ref, selection_ref: sourceRef, target_keys: ["root-1"], match_basis: "literal" }],
  coverage: { complete: true, scanned_chapters: 2, total_chapters: 2, matched_occurrences: 3 }, warnings: [], ...overrides,
})
let api
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear()
  api = {
    context: {
      startFocusedSearch: vi.fn().mockResolvedValue({ task_id: "t1", status: "pending" }),
      getFocusedSearch: vi.fn().mockResolvedValue({ task_id: "t1", status: "completed", can_resume: false, result: result(), error: null }),
      resumeFocusedSearch: vi.fn().mockResolvedValue({ task_id: "t2", status: "pending" }),
    },
    tasks: { get: vi.fn().mockResolvedValue({ status: "done", result: { targeted_completion: { status: "done", root_count: 1, completed_roots: 1, created: 1, filled: 2, review: 0 } } }), cancel: vi.fn().mockResolvedValue({}) },
    imports: { targetedCompletion: vi.fn().mockResolvedValue({ task_id: "completion-1" }), resumeDeepImport: vi.fn(), rollbackTargetedCompletion: vi.fn().mockResolvedValue({ status: "rolled_back", conflicts: 0 }) },
  }
  setBridgeOverrides({ api, state: { currentProjectId: "p1" }, confirm: vi.fn(() => true) })
})
afterEach(() => { resetBridgeOverrides(); vi.useRealTimers() })

describe("专项查证实际交互", () => {
  it("停止请求失败后仍接收原任务的完成状态", async () => {
    vi.useFakeTimers()
    api.tasks.get.mockResolvedValueOnce({ status: "running" })
    api.tasks.cancel.mockRejectedValueOnce(new Error("网络暂时不可用"))
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    await wrapper.findAll("button").find(button => button.text() === "停止补全").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("网络暂时不可用")
    await vi.advanceTimersByTimeAsync(1500); await flushPromises()
    expect(wrapper.text()).toContain("新增 1 · 填空 2")
    expect(wrapper.get("input").element.disabled).toBe(false)
  })

  it("运行中的任务返回404后解除忙碌状态并允许重新开始", async () => {
    vi.useFakeTimers()
    api.tasks.get.mockResolvedValueOnce({ status: "running" })
      .mockRejectedValueOnce(Object.assign(new Error("Not found"), { status: 404 }))
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    await vi.advanceTimersByTimeAsync(1500); await flushPromises()
    expect(wrapper.text()).toContain("未找到原任务，请重新开始")
    expect(wrapper.get("input").element.disabled).toBe(false)
    expect(wrapper.findAll("button").some(button => button.text() === "停止补全")).toBe(false)
    expect(recoverActiveWorkflows("p1")).toHaveLength(0)
  })

  it("按需发起并携带当前场景边界，出处自动转义且加入资料只发引用", async () => {
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", consumer: "writing", sceneId: "s1", chapterIndex: 1, contentMode: "working" } })
    expect(api.context.startFocusedSearch).not.toHaveBeenCalled()
    await wrapper.get("input").setValue("沈岚")
    await wrapper.get("form").trigger("submit")
    await flushPromises()
    expect(api.context.startFocusedSearch).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", roots: [{ name: "沈岚" }], consumer: "writing", scene_id: "s1", chapter_index: 1, max_depth: 1 }))
    expect(wrapper.text()).toContain("第 1 章原文")
    expect(wrapper.text()).toContain("<img src=x>")
    expect(wrapper.find("img").exists()).toBe(false)
    await wrapper.findAll("button").find(button => button.text() === "加入本次参考资料").trigger("click")
    expect(wrapper.emitted("select-source")).toEqual([[sourceRef]])
    expect(api.imports.targetedCompletion).not.toHaveBeenCalled()
  })

  it("部分覆盖提示未查完，续查只传服务端任务标识", async () => {
    api.context.getFocusedSearch.mockResolvedValueOnce({ task_id: "t1", status: "recoverable", can_resume: true, result: result({ coverage: { complete: false, scanned_chapters: 1, total_chapters: 3, matched_occurrences: 1 }, warnings: ["关联发现未完成"] }) })
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(wrapper.text()).toContain("当前为部分结果")
    expect(wrapper.text()).toContain("关联发现未完成")
    await wrapper.findAll("button").find(button => button.text().includes("继续未完成")).trigger("click")
    await flushPromises()
    expect(api.context.resumeFocusedSearch).toHaveBeenCalledWith("t1", "p1")
    expect(wrapper.text()).toContain("声明范围内的查读已结束")
  })

  it("切场景后的晚到结果不会进入新场景，返回原场景可恢复任务", async () => {
    let finish
    api.context.getFocusedSearch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", consumer: "writing", initialName: "沈岚", sceneId: "s1", chapterIndex: 1 } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    await wrapper.setProps({ sceneId: "s2", chapterIndex: 2 })
    finish({ task_id: "t1", status: "completed", result: result() })
    await flushPromises()
    expect(wrapper.find(".focused-evidence__item").exists()).toBe(false)
    await wrapper.setProps({ sceneId: "s1", chapterIndex: 1 }); await flushPromises()
    expect(wrapper.find(".focused-evidence__item").exists()).toBe(true)
    expect(api.context.startFocusedSearch).toHaveBeenCalledTimes(1)
  })

  it("地图既有对象走精确引用，选择新名称时不会沿用旧对象身份", async () => {
    const target = { target_ref: { target_type: "core_entity", target_id: "place-1", target_path: "" } }
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", consumer: "map", roots: [target], initialName: "北港" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(api.context.startFocusedSearch).toHaveBeenLastCalledWith(expect.objectContaining({ roots: [target], consumer: "map", content_mode: "canonical" }))
    await wrapper.get("input").setValue("雪山")
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(api.context.startFocusedSearch).toHaveBeenLastCalledWith(expect.objectContaining({ roots: [{ name: "雪山" }] }))
  })

  it("失败保留输入，并明确展示服务端拒绝原因", async () => {
    api.context.startFocusedSearch.mockRejectedValueOnce(new Error("所选资料版本已变化，请重新查证"))
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(wrapper.get("input").element.value).toBe("沈岚")
    expect(wrapper.get('[role="alert"]').text()).toContain("资料版本已变化")
  })

  it("已提交查证的来源过期时停止轮询并允许重查", async () => {
    api.context.getFocusedSearch.mockRejectedValueOnce(Object.assign(new Error("stale source"), { status: 409 }))
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(wrapper.text()).toContain("原文或知识资料已变化")
    expect(wrapper.findAll("button").find(button => button.text() === "开始查证").element.disabled).toBe(false)
    expect(wrapper.find(".focused-evidence__item").exists()).toBe(false)
  })

  it("入队响应晚于离开时仍为原场景保存回执，不更新新场景", async () => {
    let finish
    api.context.startFocusedSearch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", sceneId: "s1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    await wrapper.setProps({ sceneId: "s2", initialName: "柳舟" })
    finish({ task_id: "late-task", status: "pending" }); await flushPromises()
    const saved = recoverActiveWorkflows("p1").find(item => item.taskId === "late-task")
    expect(saved.meta.name).toBe("沈岚")
    expect(saved.meta.contextKey).toContain("s1")
    expect(api.context.getFocusedSearch).not.toHaveBeenCalled()
    expect(wrapper.get("input").element.value).toBe("柳舟")
  })

  it("已有引用即使原文失效也能清空，避免阻塞后续生成", async () => {
    const wrapper = mount(FocusedEvidencePanel, { props: { projectId: "p1", selectedRefs: [sourceRef] } })
    await wrapper.findAll("button").find(button => button.text() === "清空本次资料选择").trigger("click")
    expect(wrapper.emitted("clear-selection")).toHaveLength(1)
  })
})

describe("手动查漏补全", () => {
  it("导入中的自动补全可直接显示原任务结果并撤销，不重新提交", async () => {
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", sourceTaskId: "deep-import-1" } })
    await flushPromises()
    expect(api.tasks.get).toHaveBeenCalledWith("deep-import-1", "p1")
    expect(wrapper.find("form").exists()).toBe(false)
    expect(wrapper.text()).toContain("本轮补全结果")
    await wrapper.findAll("button").find(button => button.text() === "撤销这次补全").trigger("click")
    await flushPromises()
    expect(api.imports.rollbackTargetedCompletion).toHaveBeenCalledWith("deep-import-1", "p1")
    expect(api.imports.targetedCompletion).not.toHaveBeenCalled()
  })

  it("明确授权后才提交目标，完成结果显示新增填空并支持安全撤销", async () => {
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", entityId: "e1", initialName: "沈岚" } })
    expect(api.imports.targetedCompletion).not.toHaveBeenCalled()
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(api.imports.targetedCompletion).toHaveBeenCalledWith({ novel_id: "p1", targets: [{ entity_id: "e1" }], start_chapter: 1, end_chapter: 0, authorization_confirmed: true })
    expect(wrapper.text()).toContain("新增 1 · 填空 2")
    await wrapper.findAll("button").find(button => button.text() === "撤销这次补全").trigger("click")
    await flushPromises()
    expect(api.imports.rollbackTargetedCompletion).toHaveBeenCalledWith("completion-1", "p1")
    expect(wrapper.text()).toContain("本次补全已安全撤销")
  })
  it("未入库名称可启动，取消撤销确认不会发送写请求", async () => {
    setBridgeOverrides({ confirm: () => false })
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", initialName: "长桥" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    expect(api.imports.targetedCompletion).toHaveBeenCalledWith(expect.objectContaining({ targets: [{ name: "长桥" }] }))
    await wrapper.findAll("button").find(button => button.text() === "撤销这次补全").trigger("click")
    expect(api.imports.rollbackTargetedCompletion).not.toHaveBeenCalled()
  })

  it("提交后立即卸载仍保留回执，恢复使用服务端部分撤销状态", async () => {
    let finish
    api.imports.targetedCompletion.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await wrapper.get("form").trigger("submit"); await flushPromises()
    wrapper.unmount()
    finish({ task_id: "late-completion" }); await flushPromises()
    expect(recoverActiveWorkflows("p1").some(item => item.taskId === "late-completion")).toBe(true)
    api.tasks.get.mockResolvedValue({ status: "done", result: { targeted_completion: { status: "partial", created: 1, filled: 1, rollback_status: "partial", rollback_conflicts: 1 } } })
    const restored = mount(TargetedCompletionPanel, { props: { projectId: "p1", initialName: "沈岚" } })
    await flushPromises()
    expect(restored.text()).toContain("后续修改或引用冲突已保留")
    expect(restored.text()).not.toContain("继续未完成的补全")
    expect(restored.findAll("button").some(button => button.text() === "撤销这次补全")).toBe(true)
  })
})
