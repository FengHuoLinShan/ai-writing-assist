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
  it("人物档案保存期间的新输入保持未保存，并使用服务器新基线重试", async () => {
    let resolve
    api.world.updateCharacter.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const wrapper = mountDetail()
    await wrapper.get(".world-character-profile > header .btn").trigger("click")
    await vi.waitFor(() => expect(wrapper.findAll(".world-character-profile textarea").length).toBeGreaterThan(0))
    await wrapper.findAll(".world-character-profile textarea")[0].setValue("先保存")
    await wrapper.get(".world-character-profile__actions .btn").trigger("click")
    await wrapper.findAll(".world-character-profile textarea")[0].setValue("继续输入")
    resolve({ ...profile, role: "先保存", updated_at: "2026-09-09T03:00:00Z" })
    await vi.waitFor(() => expect(wrapper.get(".world-character-profile__actions .btn").attributes("disabled")).toBeUndefined())
    expect(wrapper.findAll(".world-character-profile textarea")[0].element.value).toBe("继续输入")
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])
    await wrapper.get(".world-character-profile__actions .btn").trigger("click")
    expect(api.world.updateCharacter.mock.calls[1][1]).toMatchObject({ role: "继续输入", expected_updated_at: "2026-09-09T03:00:00Z" })
    wrapper.unmount()
  })

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

  it("读取失败时不允许覆盖未知档案，重试成功后才可编辑", async () => {
    api.world.getCharacter
      .mockRejectedValueOnce(new Error("暂时无法读取"))
      .mockResolvedValueOnce(profile)
    const wrapper = mountDetail()

    await wrapper.get(".world-character-profile > header .btn").trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".error-card").text()).toContain("暂时无法读取"))
    expect(wrapper.find(".world-character-profile textarea").exists()).toBe(false)
    expect(api.world.updateCharacter).not.toHaveBeenCalled()

    await wrapper.get(".error-card .btn").trigger("click")
    await vi.waitFor(() => expect(wrapper.findAll(".world-character-profile textarea").length).toBeGreaterThan(0))
    expect(api.world.getCharacter).toHaveBeenCalledTimes(2)
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

describe("WorldEntityDetail 基本资料就地编辑", () => {
  const withTimestamp = (entity) => ({ ...entity, updated_at: "2026-09-09T02:00:00Z" })

  beforeEach(() => {
    api.world.getEntity = vi.fn(async () => withTimestamp(character))
    api.world.updateEntity = vi.fn(async (_id, payload) => withTimestamp({ ...character, ...payload, expected_updated_at: undefined }))
  })

  it("切换对象后旧基本资料保存响应不能关闭新对象的编辑器", async () => {
    let resolve
    api.world.updateEntity.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const wrapper = mountDetail(withTimestamp(character))
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("旧对象")
    await wrapper.get("[data-action='world-entity-basic-save']").trigger("click")
    await wrapper.setProps({ entity: withTimestamp({ ...character, id: "new", name: "新对象" }) })
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("新对象未保存输入")
    resolve({ ...character, summary: "旧对象" })
    await Promise.resolve()
    await wrapper.vm.$nextTick()
    expect(wrapper.get("[data-basic-field='summary']").element.value).toBe("新对象未保存输入")
    expect(wrapper.emitted("refresh")).toBeUndefined()
    wrapper.unmount()
  })

  it("就地编辑名称/概要/公开信息/作者秘密，保存携带基线且不弹独立表单", async () => {
    const wrapper = mountDetail(withTimestamp(character))
    expect(wrapper.find(".world-entity-basic__facts").text()).toContain("林澈")

    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='name']").setValue("林澈（成年）")
    await wrapper.get("[data-basic-field='summary']").setValue("雾港的调查者")
    await wrapper.get("[data-basic-field='public_info']").setValue("港务登记在册")
    await wrapper.get("[data-basic-field='hidden_truth']").setValue("暗桩")

    await wrapper.get("[data-action='world-entity-basic-save']").trigger("click")
    expect(api.world.updateEntity).toHaveBeenCalledTimes(1)
    const [entityId, payload, projectId] = api.world.updateEntity.mock.calls[0]
    expect(entityId).toBe("character-1")
    expect(projectId).toBe("p1")
    expect(payload).toMatchObject({
      name: "林澈（成年）",
      summary: "雾港的调查者",
      public_info: "港务登记在册",
      hidden_truth: "暗桩",
      expected_updated_at: "2026-09-09T02:00:00Z",
    })
    // 保存成功后回到展示态并刷新
    expect(wrapper.find(".world-entity-basic__form").exists()).toBe(false)
  })

  it("取消不触发保存；有修改时取消需确认", async () => {
    const confirmSpy = vi.fn(() => false)
    setBridgeOverrides({ api, toast: vi.fn(), confirm: confirmSpy })
    const wrapper = mountDetail(withTimestamp(character))
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("临时修改")
    await wrapper.get("[data-action='world-entity-basic-cancel']").trigger("click")
    expect(confirmSpy).toHaveBeenCalled()
    expect(wrapper.find(".world-entity-basic__form").exists()).toBe(true)
    expect(api.world.updateEntity).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it("基线 409 展示服务器版本供作者选择，采用后载入新基线", async () => {
    const conflict = Object.assign(new Error("请求冲突：已在别处更新"), {
      status: 409,
      body: { error: "edit_baseline_stale" },
    })
    api.world.updateEntity.mockRejectedValueOnce(conflict)
    const server = { ...character, name: "林澈（服务器）", summary: "服务器概要", updated_at: "2026-09-09T03:00:00Z" }
    api.world.getEntity.mockResolvedValue(server)
    const wrapper = mountDetail(withTimestamp(character))

    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("我的修改")
    await wrapper.get("[data-action='world-entity-basic-save']").trigger("click")
    await vi.waitFor(() => expect(wrapper.find("[data-conflict='basic']").exists()).toBe(true))
    expect(wrapper.find("[data-conflict='basic']").text()).toContain("林澈（服务器）")

    await wrapper.get("[data-action='world-entity-basic-adopt-server']").trigger("click")
    await wrapper.vm.$nextTick()
    expect(wrapper.get("[data-basic-field='name']").element.value).toBe("林澈（服务器）")
    expect(wrapper.get("[data-basic-field='summary']").element.value).toBe("服务器概要")

    // 在服务器版本之上再次保存携带新基线
    api.world.updateEntity.mockClear()
    await wrapper.get("[data-basic-field='summary']").setValue("服务器概要＋补充")
    await wrapper.get("[data-action='world-entity-basic-save']").trigger("click")
    await vi.waitFor(() => expect(api.world.updateEntity).toHaveBeenCalledTimes(1))
    expect(api.world.updateEntity.mock.calls[0][1].expected_updated_at).toBe("2026-09-09T03:00:00Z")
  })
})
