import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import CreativeTrialEditor from "../../../vue/components/CreativeTrialEditor.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const trial = { id: "trial-a", status: "open", stale: false, revision_id: "revision-a", editable_resources: [{ resource: { kind: "writing_draft", id: "draft-a" }, label: "开场", value: { title: "开场", content: "原稿。" } }] }
beforeEach(() => localStorage.clear())
afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it("手动试改的文字随页面恢复", async () => {
  setBridgeOverrides({ api: { collaboration: {} } })
  let wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial } })
  await wrapper.findAll("button").find(button => button.text() === "手动调整这一版").trigger("click")
  await wrapper.findAll("textarea")[1].setValue("保留谨慎的动机。")
  wrapper.unmount()
  wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial } })
  expect(wrapper.findAll("textarea")[1].element.value).toBe("保留谨慎的动机。")
  wrapper.unmount()
})

it("失去重建回执时复用原操作，冲突选择绑定当前版本", async () => {
  const rebase = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ status: "conflict", current_hash: "a".repeat(64), conflicts: [{ resource: { kind: "writing_draft", id: "current" }, label: "开场", fields: ["content"], base: { title: "开场", content: "原稿。" }, current: { title: "开场", content: "作者改动。" }, trial: { title: "开场", content: "试改。" } }] }).mockResolvedValueOnce({ status: "ready", workspace: { id: "rebased" } })
  setBridgeOverrides({ api: { collaboration: { rebase } } })
  const wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial } })
  await wrapper.findAll("button").find(button => button.text() === "按当前稿重建试改").trigger("click")
  await flushPromises()
  const operation = rebase.mock.calls[0][2].operation_id
  await wrapper.findAll("button").find(button => button.text() === "恢复原操作").trigger("click")
  await flushPromises()
  expect(rebase.mock.calls[1][2].operation_id).toBe(operation)
  await wrapper.get('input[value="trial"]').setValue(true)
  await wrapper.get("form").trigger("submit")
  await flushPromises()
  expect(rebase.mock.calls[2][2]).toEqual(expect.objectContaining({ operation_id: operation, expected_current_hash: "a".repeat(64), resolutions: [{ kind: "writing_draft", id: "current", operation: "replace", value: { title: "开场", content: "试改。" } }] }))
  expect(wrapper.emitted("updated")[0][0].id).toBe("rebased")
  wrapper.unmount()
})

it("新修订中的新输入不会覆盖上一修订保留的文字", async () => {
  setBridgeOverrides({ api: { collaboration: {} } })
  let wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial } })
  await wrapper.findAll("button").find(button => button.text() === "手动调整这一版").trigger("click")
  await wrapper.findAll("textarea")[1].setValue("旧修订中的未提交文字。")
  const changed = { ...trial, revision_id: "revision-b" }
  await wrapper.setProps({ trial: changed })
  expect(wrapper.text()).toContain("旧修订中的未提交文字。")
  await wrapper.findAll("button").find(button => button.text() === "手动调整这一版").trigger("click")
  await wrapper.findAll("textarea")[1].setValue("新修订中的另一段输入。")
  wrapper.unmount()
  wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial: changed } })
  expect(wrapper.findAll("textarea")[1].element.value).toBe("新修订中的另一段输入。")
  expect(wrapper.text()).toContain("旧修订中的未提交文字。")
  wrapper.unmount()
})

it("备份失败通过独立路由守卫保护试改文字", async () => {
  let guard
  const release = vi.fn()
  setBridgeOverrides({ api: { collaboration: {} }, router: { registerLeaveGuard: fn => { guard = fn; return release } } })
  const wrapper = mount(CreativeTrialEditor, { props: { projectId: "project-a", trial } })
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => { throw new Error("disk full") } })
  vi.stubGlobal("confirm", vi.fn(() => false))
  await wrapper.findAll("button").find(button => button.text() === "手动调整这一版").trigger("click")
  await wrapper.findAll("textarea")[1].setValue("不能丢失这段修改。")
  expect(guard()).toBe(false)
  expect(wrapper.text()).toContain("修改暂未备份")
  wrapper.unmount()
  expect(release).toHaveBeenCalled()
})
