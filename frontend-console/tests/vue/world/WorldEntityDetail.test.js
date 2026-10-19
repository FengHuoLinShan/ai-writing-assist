import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldEntityDetail from "../../../vue/views/world/library/WorldEntityDetail.vue"
import WorldEntityRevisionHistory from "../../../vue/views/world/library/WorldEntityRevisionHistory.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const character = { id: "character-1", entity_type: "character", name: "林澈", status: "canonical", content_json: {} }
const profile = { entity_id: "character-1", role: "主角", personality: "谨慎", meta: { auto_materialized: true }, status: "canonical" }
let api

beforeEach(() => {
  globalThis.localStorage?.clear?.()
  api = {
    world: {
      getCharacter: vi.fn(async () => profile),
      updateCharacter: vi.fn(async (_id, payload) => ({ ...profile, ...payload })),
      getEntityRevisions: vi.fn(async () => ({ items: [], total: 0 })),
      getEntityDossier: vi.fn(async () => ({ entries: [], total_count: 0, omitted_count: 0, unknown: true })),
      listEntityDossierFacets: vi.fn(async () => ({ items: [] })),
    },
    outline: { listScenesOrdered: vi.fn(async () => []) },
  }
  setBridgeOverrides({ api, toast: vi.fn(), currentAccount: { id: "account-test" } })
})

afterEach(() => {
  resetBridgeOverrides()
})

function mountDetail(entity = character) {
  return mount(WorldEntityDetail, { props: { entity, projectId: "p1", typeLabel: "人物" } })
}

it.each([false, true])("撤回基本资料清理中间备份且保留其他页面新副本：%s", async concurrentBackup => {
  const saved = { ...character, summary: "服务器概要", updated_at: "2026-10-18T00:00:00Z" }
  let wrapper = mountDetail(saved)
  await wrapper.get("[data-action=world-entity-basic-edit]").trigger("click")
  await wrapper.get("[data-basic-field=summary]").setValue("已放弃的中间输入")
  if (concurrentBackup) {
    const key = Object.keys(localStorage).find(key => key.endsWith(":character-1:basic"))
    const newer = JSON.parse(localStorage.getItem(key))
    newer.payload.summary = "其他页面的新副本"
    localStorage.setItem(key, JSON.stringify(newer))
  }
  await wrapper.get("[data-basic-field=summary]").setValue(saved.summary)
  expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([false])
  if (concurrentBackup) expect(wrapper.text()).toContain("本机草稿已在其他页面更新，因此没有清除")
  wrapper.unmount()
  wrapper = mountDetail(saved)
  await wrapper.get("[data-action=world-entity-basic-edit]").trigger("click")
  expect(wrapper.get("[data-basic-field=summary]").element.value).toBe(concurrentBackup ? "其他页面的新副本" : saved.summary)
  wrapper.unmount()
})

describe("WorldEntityDetail 人物档案", () => {
  it('按对象资料分区键盘切换，档案编辑实例和输入保留', async () => {
    const wrapper = mountDetail()
    const tab = label => wrapper.findAll('[role=tab]').find(button => button.text() === label)
    await tab('设定档案').trigger('click')
    const section = wrapper.get('details.world-entity-dossier')
    section.element.open = true
    await section.trigger('toggle')
    await flushPromises()
    const editor = wrapper.findComponent({ name: 'WorldObjectDossierEditor' })
    await tab('设定档案').trigger('keydown', { key: 'ArrowRight' })
    expect(tab('关系').attributes('aria-selected')).toBe('true')
    await tab('关系').trigger('keydown', { key: 'End' })
    expect(tab('经历与来源').attributes('aria-selected')).toBe('true')
    await tab('设定档案').trigger('click')
    expect(wrapper.findComponent({ name: 'WorldObjectDossierEditor' }).element).toBe(editor.element)
    wrapper.unmount()
  })
  it("对象详情中的对象档案默认收起，展开后从真实档案接口读取并纳入 dirty 状态", async () => {
    const wrapper = mountDetail()
    const section = wrapper.get("details.world-entity-dossier")
    expect(api.world.getEntityDossier).not.toHaveBeenCalled()
    section.element.open = true
    await section.trigger("toggle")
    await flushPromises()
    expect(api.world.getEntityDossier).toHaveBeenCalledWith("character-1", "p1", { cache: "no-store", asOfSceneId: null })
    expect(wrapper.text()).toContain("当前没有已确认的稳定档案条目")
    wrapper.findComponent({ name: "WorldObjectDossierEditor" }).vm.$emit("dirty", true)
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])
    const editor = wrapper.findComponent({ name: "WorldObjectDossierEditor" })
    section.element.open = false
    await section.trigger("toggle")
    expect(editor.exists()).toBe(true)
    expect(wrapper.findComponent({ name: "WorldObjectDossierEditor" }).element).toBe(editor.element)
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])
    section.element.open = true
    await section.trigger("toggle")
    expect(api.world.getEntityDossier).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("同对象刷新不卸载档案或清除编辑中的输入，切换对象才重置", async () => {
    const wrapper = mountDetail({ ...character, summary: "服务器概要" })
    const section = wrapper.get("details.world-entity-dossier")
    section.element.open = true
    await section.trigger("toggle")
    await flushPromises()
    const editor = wrapper.findComponent({ name: "WorldObjectDossierEditor" })
    await wrapper.get("[data-action=world-entity-basic-edit]").trigger("click")
    await wrapper.get("[data-basic-field=summary]").setValue("仍在编辑的输入")
    await wrapper.setProps({ entity: { ...character, summary: "后台刷新的概要" } })
    await flushPromises()
    expect(wrapper.findComponent({ name: "WorldObjectDossierEditor" }).element).toBe(editor.element)
    expect(wrapper.get("[data-basic-field=summary]").element.value).toBe("仍在编辑的输入")
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])
    await wrapper.setProps({ entity: { ...character, id: "character-2", name: "另一对象" } })
    expect(wrapper.findComponent({ name: "WorldObjectDossierEditor" }).exists()).toBe(false)
    expect(wrapper.find("[data-basic-field=summary]").exists()).toBe(false)
    wrapper.unmount()
  })

  it("公开演示中的对象档案不挂载写入操作", async () => {
    setBridgeOverrides({ publicDemoReadOnly: true })
    const wrapper = mountDetail()
    const section = wrapper.get("details.world-entity-dossier")
    section.element.open = true
    await section.trigger("toggle")
    await flushPromises()
    expect(wrapper.text()).toContain("只读演示")
    expect(wrapper.text()).not.toContain("新增档案条目")
    wrapper.unmount()
  })

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

  it("内联修订历史：默认收起不发请求，展开后按对象与作品读取，恢复完成转发 refresh", async () => {
    const wrapper = mountDetail()
    const panel = wrapper.get("details.world-entity-revision-history")
    expect(api.world.getEntityRevisions).not.toHaveBeenCalled()
    panel.element.open = true
    await panel.trigger("toggle")
    await flushPromises()
    expect(api.world.getEntityRevisions).toHaveBeenCalledWith("character-1", "p1", { skip: 0, limit: 20 })
    wrapper.findComponent(WorldEntityRevisionHistory).vm.$emit("restored")
    expect(wrapper.emitted("refresh").at(-1)).toEqual(["character-1"])
    wrapper.unmount()
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
    expect(localStorage.getItem("author-workspace-draft:v1:account-test:p1:character-1:basic")).toBeNull()
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

  it("同一服务器版本的对象草稿在离开后可恢复，但仍需手动保存", async () => {
    const entity = withTimestamp(character)
    const wrapper = mountDetail(entity)
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("本地未保存概要")
    await wrapper.vm.$nextTick()
    await flushPromises()

    const key = "author-workspace-draft:v1:account-test:p1:character-1:basic"
    const stored = JSON.parse(localStorage.getItem(key))
    expect(stored).toMatchObject({ base_version: entity.updated_at, payload: { summary: "本地未保存概要" } })
    wrapper.unmount()

    const resumed = mountDetail(entity)
    await resumed.get("[data-action='world-entity-basic-edit']").trigger("click")
    expect(resumed.get("[data-basic-field='summary']").element.value).toBe("本地未保存概要")
    expect(resumed.text()).toContain("已恢复与当前服务器版本匹配的本机草稿")
    expect(api.world.updateEntity).not.toHaveBeenCalled()
    resumed.unmount()
  })

  it("服务器版本变化时不覆盖资料，作者核对最新版本后才能保留本机草稿", async () => {
    const oldEntity = withTimestamp(character)
    const first = mountDetail(oldEntity)
    await first.get("[data-action='world-entity-basic-edit']").trigger("click")
    await first.get("[data-basic-field='summary']").setValue("需要保留的草稿")
    await first.vm.$nextTick()
    await flushPromises()
    first.unmount()

    const newEntity = { ...character, name: "服务器名称", summary: "服务器概要", updated_at: "2026-09-09T03:00:00Z" }
    api.world.getEntity.mockResolvedValue(newEntity)
    const resumed = mountDetail(newEntity)
    await resumed.get("[data-action='world-entity-basic-edit']").trigger("click")
    expect(resumed.get("[data-basic-field='summary']").element.value).toBe("服务器概要")
    expect(resumed.find("[data-conflict='basic-local-draft']").exists()).toBe(true)
    expect(resumed.get("[data-basic-field='summary']").attributes("disabled")).toBeDefined()

    await resumed.find("[data-conflict='basic-local-draft'] button").trigger("click")
    await flushPromises()
    expect(api.world.getEntity).toHaveBeenCalledWith("character-1", "p1", { cache: "no-store" })
    expect(resumed.get("[data-basic-field='summary']").element.value).toBe("需要保留的草稿")
    expect(resumed.get("[data-basic-field='name']").element.value).toBe("服务器名称")
    await resumed.vm.$nextTick()
    const rebased = JSON.parse(localStorage.getItem("author-workspace-draft:v1:account-test:p1:character-1:basic"))
    expect(rebased.base_version).toBe(newEntity.updated_at)
    resumed.unmount()
  })

  it("放弃旧版本本机草稿须明确确认且不修改服务器", async () => {
    const oldEntity = withTimestamp(character)
    const first = mountDetail(oldEntity)
    await first.get("[data-action='world-entity-basic-edit']").trigger("click")
    await first.get("[data-basic-field='summary']").setValue("待放弃")
    await first.vm.$nextTick()
    await flushPromises()
    first.unmount()

    const server = { ...character, updated_at: "2026-09-09T03:00:00Z" }
    const confirm = vi.fn(() => true)
    setBridgeOverrides({ confirm })
    const resumed = mountDetail(server)
    await resumed.get("[data-action='world-entity-basic-edit']").trigger("click")
    await resumed.findAll("[data-conflict='basic-local-draft'] button")[1].trigger("click")

    expect(confirm).toHaveBeenCalled()
    expect(localStorage.getItem("author-workspace-draft:v1:account-test:p1:character-1:basic")).toBeNull()
    expect(api.world.updateEntity).not.toHaveBeenCalled()
    expect(resumed.text()).toContain("已放弃本机草稿")
    resumed.unmount()
  })

  it("本机存储失败会明示并保留页面输入", async () => {
    setBridgeOverrides({ localDraftStorage: { getItem() { throw new Error("storage disabled") }, setItem() { throw new Error("storage disabled") }, removeItem() {} } })
    const wrapper = mountDetail(withTimestamp(character))
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("仍在页面里的内容")
    await wrapper.vm.$nextTick()

    expect(wrapper.get("[data-basic-field='summary']").element.value).toBe("仍在页面里的内容")
    expect(wrapper.get("[role='alert']").text()).toContain("本机草稿备份失败")
    expect(wrapper.emitted("profile-dirty").at(-1)).toEqual([true])
    wrapper.unmount()
  })
})

describe("WorldEntityDetail 精确助手定位", () => {
  it("从对象资料打开带保存版本的助手上下文", async () => {
    const assistantOpener = vi.fn(async () => undefined)
    setBridgeOverrides({ state: { currentProjectId: "p1" }, assistantOpener })
    const entity = { ...character, updated_at: "2026-10-18T08:00:00Z" }
    const wrapper = mountDetail(entity)
    const button = wrapper.findAll("button").find((item) => item.text().trim() === "问对象")
    expect(button?.exists()).toBe(true)
    await button.trigger("click")

    expect(assistantOpener).toHaveBeenCalledWith(expect.objectContaining({
      projectId: "p1",
      context: expect.objectContaining({
        page: "world",
        target: { target_type: "world_entity", target_id: "character-1" },
        focus_ref: { kind: "entity", entity_id: "character-1", updated_at: entity.updated_at },
        focus_label: "对象：林澈 · 人物",
      }),
    }))
    wrapper.unmount()
  })

  it("存在未保存的世界资料时不把旧版本误作当前讨论上下文", async () => {
    const assistantOpener = vi.fn(async () => undefined)
    const toast = vi.fn()
    const wrapper = mountDetail({ ...character, updated_at: "2026-10-18T08:00:00Z" })
    setBridgeOverrides({ state: { currentProjectId: "p1" }, assistantOpener, toast })
    await wrapper.get("[data-action='world-entity-basic-edit']").trigger("click")
    await wrapper.get("[data-basic-field='summary']").setValue("尚未保存的摘要")
    const askButton = wrapper.findAll("button").find((item) => item.text().trim() === "问对象")
    await askButton.trigger("click")

    expect(assistantOpener).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "先保存或取消未保存的资料，再按已保存版本打开助手讨论。",
      "warning",
    )
    wrapper.unmount()
  })

  it("从关系行打开带关系版本和当前对象的助手上下文", async () => {
    const relation = {
      id: "relation-1", source_name: "林澈", target_name: "青竹",
      updated_at: "2026-10-18T08:01:00Z", description: "相互信任",
    }
    api.world.getEntityRelations = vi.fn(async () => ({ items: [relation], total: 1 }))
    const assistantOpener = vi.fn(async () => undefined)
    setBridgeOverrides({ state: { currentProjectId: "p1" }, assistantOpener })
    const wrapper = mountDetail({ ...character, updated_at: "2026-10-18T08:00:00Z" })
    const details = wrapper.findAll("details").find((item) => item.find("summary").text().trim() === "关系")
    details.element.open = true
    await details.trigger("toggle")
    await flushPromises()
    const button = details.findAll("button").find((item) => item.text().trim() === "问这条关系")
    expect(button?.exists()).toBe(true)
    await button.trigger("click")

    expect(assistantOpener).toHaveBeenCalledWith(expect.objectContaining({
      context: expect.objectContaining({
        target: { target_type: "world_entity", target_id: "character-1" },
        focus_ref: {
          kind: "relation", entity_id: "character-1", relation_id: relation.id,
          updated_at: relation.updated_at,
        },
        focus_label: "关系：林澈 → 青竹",
      }),
    }))
    wrapper.unmount()
  })
})
