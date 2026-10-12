import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import OpeningSkeletonReview from "../../../vue/views/today/components/OpeningSkeletonReview.vue"

enableAutoUnmount(afterEach)
afterEach(resetBridgeOverrides)
let api, suggestion
beforeEach(() => {
  localStorage.clear()
  suggestion = { updated_at: "2026-10-12T00:00:00Z", payload_json: { items: [{ item_key: "city", kind: "core_entity", disposition: "include", payload: { operation: "create", entity: { name: "潮城", summary: "旧简介" } } }] } }
  api = { world: {
    getAdoptionArtifact: vi.fn(async () => suggestion),
    previewAdoptionPackage: vi.fn(async () => ({ expected_preview_hash: "p".repeat(64), canon_diff: [] })),
    updateAdoptionPackageItems: vi.fn(async (_id, body) => ({ suggestion: { ...suggestion, updated_at: "2026-10-12T00:00:01Z", payload_json: { items: [{ ...suggestion.payload_json.items[0], disposition: body.items[0].included ? "include" : "open", payload: { operation: "create", entity: { name: body.items[0].name ?? "潮城", summary: body.items[0].summary ?? "旧简介" } } }] } }, item_conflicts: [] })),
    rollbackAdoptionPackage: vi.fn(async () => ({ results: [{ item_key: "city", status: "modified_after_adoption" }] })),
  } }
  setBridgeOverrides({ api, confirmAction: (_message, onConfirm) => onConfirm() })
})
async function review(adopted = false) {
  const wrapper = mount(OpeningSkeletonReview, { props: { projectId: "p1", packageId: "package1", adopted } })
  await flushPromises()
  return wrapper
}
describe("骨架逐条取舍", () => {
  it("编辑前后绑定服务端基线；保存后才可采用当前取舍", async () => {
    const wrapper = await review()
    await wrapper.get("textarea").setValue("作者改过的简介")
    expect(wrapper.get('[data-action="opening-adopt"]').attributes("disabled")).toBeDefined()
    await wrapper.findAll("button").find(button => button.text() === "保存取舍").trigger("click")
    await flushPromises()
    expect(api.world.updateAdoptionPackageItems).toHaveBeenCalledWith("package1", { novel_id: "p1", expected_updated_at: suggestion.updated_at, items: [{ item_key: "city", included: true, summary: "作者改过的简介" }] })
    expect(wrapper.text()).toContain("取舍已保存")
    await wrapper.get('[data-action="opening-adopt"]').trigger("click")
    expect(wrapper.emitted("adopt")[0]).toEqual(["p".repeat(64)])
  })
  it("并发冲突保留输入；排除全部条目不能空采用", async () => {
    const wrapper = await review()
    api.world.updateAdoptionPackageItems.mockRejectedValue({ status: 409 })
    await wrapper.get("textarea").setValue("待保留修改")
    await wrapper.findAll("button").find(button => button.text() === "保存取舍").trigger("click")
    await flushPromises()
    expect(wrapper.get("textarea").element.value).toBe("待保留修改")
    expect(wrapper.text()).toContain("当前修改仍保留")
    await wrapper.get("input[type=checkbox]").setValue(false)
    expect(wrapper.get('[data-action="opening-adopt"]').attributes("disabled")).toBeDefined()
  })
  it("冲突后重新读取可恢复改名、简介与排除", async () => {
    const wrapper = await review()
    api.world.updateAdoptionPackageItems.mockRejectedValue({ status: 409 })
    await wrapper.get("textarea").setValue("我的完整修改")
    await wrapper.get("input[type=checkbox]").setValue(false)
    await wrapper.findAll("button").find(button => button.text() === "保存取舍").trigger("click")
    await flushPromises()
    await wrapper.findAll("button").find(button => button.text() === "重新读取").trigger("click")
    await flushPromises()
    expect(wrapper.get("textarea").element.value).toBe("旧简介")
    await wrapper.findAll("button").find(button => button.text() === "恢复我的修改").trigger("click")
    expect(wrapper.get("textarea").element.value).toBe("我的完整修改")
    expect(wrapper.get("input[type=checkbox]").element.checked).toBe(false)
    expect(wrapper.get('[data-action="opening-adopt"]').attributes("disabled")).toBeDefined()
  })
  it("撤销经过领域确认并说明保留对象，不能重复点击", async () => {
    const wrapper = await review(true)
    await wrapper.findAll("button").find(button => button.text() === "撤销这次骨架采用").trigger("click")
    await flushPromises()
    expect(api.world.rollbackAdoptionPackage).toHaveBeenCalledWith("package1", "p1")
    expect(wrapper.text()).toContain("采用后已编辑，保留")
    expect(wrapper.emitted("rolled-back")).toHaveLength(1)
    expect(wrapper.findAll("button").find(button => button.text() === "撤销这次骨架采用").attributes("disabled")).toBeDefined()
  })
})

it("实际本地关系引用显示端点名称与规则正文、依赖原因", async () => {
  suggestion.payload_json.items.push({ item_key: "person", kind: "core_entity", disposition: "include", payload: { operation: "create", entity: { name: "守钟人", summary: "报时者" } } }, { item_key: "relation", kind: "entity_relation", disposition: "open", review_reasons: ["endpoint_excluded"], payload: { source_ref: "local:person", target_ref: "local:city", relation_type: "守护", description: "长夜值守" } }, { item_key: "rule", kind: "world_bible_page", disposition: "include", payload: { title: "月潮规则", sections_json: [{ title: "起落", body_markdown: "月潮退去时城市浮出水面。" }] } })
  const wrapper = await review()
  expect(wrapper.text()).toContain("守钟人 → 潮城：守护")
  expect(wrapper.text()).toContain("月潮退去时城市浮出水面")
  expect(wrapper.text()).toContain("关联对象已排除")
})
it("浏览器备份不可用时重读保留修改并阻止无保护离页", async () => {
  let guard
  setBridgeOverrides({ api, router: { registerLeaveGuard: callback => { guard = callback; return () => {} } } })
  const wrapper = await review()
  await wrapper.get("textarea").setValue("唯一未保存修改")
  const originalStorage = globalThis.localStorage
  vi.stubGlobal("localStorage", { getItem: key => originalStorage.getItem(key), setItem: () => { throw new Error("quota") } })
  await wrapper.findAll("button").find(button => button.text() === "重新读取").trigger("click")
  await flushPromises()
  expect(wrapper.get("textarea").element.value).toBe("唯一未保存修改")
  expect(wrapper.text()).toContain("本地备份不可用")
  expect(guard()).toBe(false)
  vi.unstubAllGlobals()
})
it("读取在途时禁用编辑；保存其他条目后仍显示已有对象关系与别名", async () => {
  suggestion.payload_json.items.push({ item_key: "known", kind: "core_entity", disposition: "include", payload: { operation: "fill_empty", entity_id: "known-id", fields: { summary: "补充资料" } } }, { item_key: "alias", kind: "entity_alias", disposition: "include", payload: { entity_ref: "existing:known-id", alias: "报时者" } }, { item_key: "edge", kind: "entity_relation", disposition: "include", payload: { source_ref: "existing:known-id", target_ref: "local:city", relation_type: "守护" } })
  api.world.getEntity = vi.fn(async () => ({ name: "林鸦" }))
  api.world.updateAdoptionPackageItems.mockImplementation(async (_id, body) => ({ suggestion: { ...suggestion, payload_json: { items: suggestion.payload_json.items.map(item => item.item_key === "city" ? { ...item, payload: { operation: "create", entity: { name: "潮城", summary: body.items[0].summary } } } : item) } }, item_conflicts: [] }))
  const wrapper = await review()
  expect(wrapper.text()).toContain("林鸦 → 潮城：守护")
  expect(wrapper.text()).toContain("林鸦的别名：报时者")
  await wrapper.get("textarea").setValue("更清楚的城市规则")
  await wrapper.findAll("button").find(button => button.text() === "保存取舍").trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("林鸦 → 潮城：守护")
  expect(wrapper.text()).toContain("林鸦的别名：报时者")
  let resolve
  api.world.getAdoptionArtifact.mockImplementation(() => new Promise(done => { resolve = done }))
  await wrapper.findAll("button").find(button => button.text() === "重新读取").trigger("click")
  expect(wrapper.get("textarea").attributes("disabled")).toBeDefined()
  expect(wrapper.get('[data-action="opening-adopt"]').attributes("disabled")).toBeDefined()
  resolve(suggestion)
  await flushPromises()
})
