import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WorldEntityDetail from "../../../vue/views/world/library/WorldEntityDetail.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const character = { id: "character-1", entity_type: "character", name: "林澈", status: "canonical", content_json: {} }
const profile = { entity_id: "character-1", role: "主角", personality: "谨慎", meta: { auto_materialized: true }, status: "canonical" }
let api

beforeEach(() => {
  api = { world: { getCharacter: vi.fn(async () => profile), updateCharacter: vi.fn(async (_id, payload) => ({ ...profile, ...payload })) } }
  setBridgeOverrides({ api, toast: vi.fn() })
})

afterEach(() => resetBridgeOverrides())

function mountDetail(entity = character) {
  return mount(WorldEntityDetail, { props: { entity, projectId: "p1", typeLabel: "人物" } })
}

describe("WorldEntityDetail 人物档案", () => {
  it("非人物不显示人物档案", () => {
    const wrapper = mountDetail({ ...character, id: "location-1", entity_type: "location", name: "雾港" })
    expect(wrapper.find(".world-character-profile").exists()).toBe(false)
  })

  it("只提交作者可编辑的人物字段", async () => {
    const wrapper = mountDetail()
    await wrapper.get(".world-character-profile > header .btn").trigger("click")
    await vi.waitFor(() => expect(api.world.getCharacter).toHaveBeenCalledWith("character-1", "p1"))
    const fields = wrapper.findAll(".world-character-profile textarea")
    await fields[0].setValue("调查者")
    await fields[2].setValue("克制而多疑")
    await wrapper.get(".world-character-profile__actions .btn").trigger("click")

    const payload = api.world.updateCharacter.mock.calls[0][1]
    expect(payload).toMatchObject({ role: "调查者", personality: "克制而多疑" })
    expect(payload).not.toHaveProperty("name")
    expect(payload).not.toHaveProperty("aliases")
    expect(payload).not.toHaveProperty("meta")
    expect(payload).not.toHaveProperty("status")
  })

  it("保存失败保留输入并显示原位错误", async () => {
    api.world.updateCharacter.mockRejectedValueOnce(new Error("暂时不可用"))
    const wrapper = mountDetail()
    await wrapper.get(".world-character-profile > header .btn").trigger("click")
    await vi.waitFor(() => expect(wrapper.findAll("textarea").length).toBeGreaterThan(0))
    await wrapper.findAll("textarea")[0].setValue("守门人")
    await wrapper.get(".world-character-profile__actions .btn").trigger("click")

    await vi.waitFor(() => expect(wrapper.get(".field-error").text()).toContain("暂时不可用"))
    expect(wrapper.findAll("textarea")[0].element.value).toBe("守门人")
  })

  it("收起人物档案仍保留未保存状态，保存后解除", async () => {
    const wrapper = mountDetail()
    const toggle = wrapper.get(".world-character-profile > header .btn")
    await toggle.trigger("click")
    await vi.waitFor(() => expect(wrapper.findAll("textarea").length).toBeGreaterThan(0))
    await wrapper.findAll("textarea")[0].setValue("守门人")
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])

    await toggle.trigger("click")
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])

    await toggle.trigger("click")
    await wrapper.get(".world-character-profile__actions .btn").trigger("click")
    await vi.waitFor(() => expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([false]))
  })

  it("切换对象后忽略旧人物档案的晚到响应", async () => {
    let resolve
    api.world.getCharacter.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const wrapper = mountDetail()
    await wrapper.get(".world-character-profile > header .btn").trigger("click")
    await wrapper.setProps({ entity: { ...character, id: "character-2", name: "迟雨" } })
    resolve(profile)
    await Promise.resolve()
    expect(wrapper.find(".world-character-profile__form").exists()).toBe(false)
  })
})
