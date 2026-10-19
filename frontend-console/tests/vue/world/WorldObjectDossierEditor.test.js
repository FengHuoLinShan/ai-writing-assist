import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldObjectDossierEditor from "../../../vue/views/world/library/WorldObjectDossierEditor.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

beforeEach(() => {
  globalThis.localStorage?.clear?.()
})

afterEach(() => {
  resetBridgeOverrides()
  globalThis.localStorage?.clear?.()
  delete globalThis.publicDemoMode
  delete globalThis.publicDemoRpMode
  vi.restoreAllMocks()
})

const entity = { id: "entity-a", entity_type: "character", name: "沈砚" }
const currentEntry = (overrides = {}) => ({
  id: "revision-1",
  entry_group_id: "group-1",
  revision_number: 1,
  entity_id: entity.id,
  facing: { kind: "core", key: "identity" },
  facing_label: "身份",
  content: "旧港账房的学徒。",
  tags: ["作者确认"],
  visibility: "public",
  status: "active",
  validity: null,
  ...overrides,
})
const dossier = (entries = [currentEntry()], overrides = {}) => ({
  entity_id: entity.id,
  entity_type: "character",
  entries,
  total_count: entries.length,
  omitted_count: 0,
  dossier_fingerprint: "fingerprint-a",
  layers: ["world"],
  unavailable_layers: ["continuity", "evolution"],
  unknown: entries.length === 0,
  ...overrides,
})
const facets = {
  entity_type: "character",
  items: [
    { facing: { kind: "core", key: "identity" }, label: "身份", description: "身份与社会位置", source: "core" },
    { facing: { kind: "core", key: "secret" }, label: "秘密", description: "作者秘密", source: "core" },
  ],
}
const sceneId = "00000000-0000-4000-8000-000000000001"
const baseApi = (overrides = {}) => ({
  world: {
    getEntityDossier: vi.fn(async () => dossier()),
    listEntityDossierFacets: vi.fn(async () => facets),
    listEntityDossierHistory: vi.fn(async () => ({ entries: [], total_count: 0, omitted_count: 0 })),
    createEntityDossierEntry: vi.fn(async () => currentEntry()),
    updateEntityDossierEntry: vi.fn(async () => currentEntry()),
    restoreEntityDossierEntry: vi.fn(async () => currentEntry()),
    getEntityDossierTemplate: vi.fn(async () => ({
      profile_type: "character", version_number: 1, fields: [], display_schema: {},
    })),
    listEntityDossierTemplateHistory: vi.fn(async () => ({ items: [] })),
    saveEntityDossierTemplate: vi.fn(async (_type, _project, payload) => ({
      profile_type: "character", version_number: 1, fields: payload.fields, display_schema: payload.display_schema,
    })),
    ...overrides.world,
  },
  outline: { listScenesOrdered: vi.fn(async () => [{ id: sceneId, scene_index: 1, title: "雾港来信" }]), ...overrides.outline },
})
const mountEditor = (api, props = {}, bridge = {}) => {
  setBridgeOverrides({ api, currentAccount: { id: "account-test" }, ...bridge })
  return mount(WorldObjectDossierEditor, { props: { entity, projectId: "project-a", ...props } })
}
const newEntryDraftKey = "author-workspace-draft:v1:account-test:project-a:entity-a:dossier-entry-create"
async function fillNewEntry(wrapper, { content = "雾港的新档案草稿。", tags = "雾港, 账房", visibility = "secret", startScene = sceneId } = {}) {
  await wrapper.get(".object-dossier-editor__new select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__new textarea").setValue(content)
  await wrapper.get(".object-dossier-editor__new input").setValue(tags)
  await wrapper.findAll(".object-dossier-editor__new form > label select").at(1).setValue(visibility)
  await wrapper.get(".object-dossier-editor__validity select").setValue(startScene)
}

it("新增保存的迟到回执恢复另一页面较新的草稿，再次编辑基于可见输入", async () => {
  let finish
  const api = baseApi({ world: { createEntityDossierEntry: vi.fn(() => new Promise(resolve => { finish = resolve })) } })
  const first = mountEditor(api)
  await flushPromises()
  await fillNewEntry(first, { content: "提交中的第一条" })
  await first.get(".object-dossier-editor__new form").trigger("submit")
  await flushPromises()
  const second = mountEditor(api)
  await flushPromises()
  await second.get(".object-dossier-editor__new textarea").setValue("另一页面的新草稿")
  second.unmount()
  finish(currentEntry())
  await flushPromises()
  expect(first.get(".object-dossier-editor__new textarea").element.value).toBe("另一页面的新草稿")
  expect(first.text()).toContain("另一页面更新的新增条目草稿已恢复")
  expect(JSON.parse(localStorage.getItem(newEntryDraftKey)).payload.content).toBe("另一页面的新草稿")
  await first.get(".object-dossier-editor__new textarea").setValue("核对可见草稿后的主动修改")
  expect(JSON.parse(localStorage.getItem(newEntryDraftKey)).payload.content).toBe("核对可见草稿后的主动修改")
  expect(api.world.createEntityDossierEntry).toHaveBeenCalledTimes(1)
  first.unmount()
})

it.each([false, true])("档案撤回清理中间草稿且保留其他页面新副本：%s", async concurrentBackup => {
  const api = baseApi()
  let wrapper = mountEditor(api)
  const edit = async () => {
    await wrapper.findAll(".object-dossier-editor__entry .object-dossier-editor__actions button").find(button => button.text() === "编辑").trigger("click")
    await flushPromises()
  }
  await flushPromises()
  await edit()
  await wrapper.get("[data-dossier-field=content]").setValue("档案中间输入")
  if (concurrentBackup) {
    const key = Object.keys(localStorage).find(key => key.endsWith(":dossier-group-1"))
    const newer = JSON.parse(localStorage.getItem(key))
    newer.payload.content = "其他页面的新副本"
    localStorage.setItem(key, JSON.stringify(newer))
  }
  await wrapper.get("[data-dossier-field=content]").setValue(currentEntry().content)
  if (concurrentBackup) expect(wrapper.text()).toContain("本机档案草稿已在其他页面更新，没有清除")
  wrapper.unmount()
  wrapper = mountEditor(api)
  await flushPromises()
  await edit()
  expect(wrapper.get("[data-dossier-field=content]").element.value).toBe(concurrentBackup ? "其他页面的新副本" : currentEntry().content)
  wrapper.unmount()
})

it("从档案条目以当前保存修订打开精确助手上下文", async () => {
  const assistantOpener = vi.fn(async () => undefined)
  const wrapper = mountEditor(baseApi(), {}, {
    state: { currentProjectId: "project-a" },
    assistantOpener,
  })
  await flushPromises()

  const askButton = wrapper.findAll(".object-dossier-editor__entry .object-dossier-editor__actions button")
    .find((button) => button.text().trim() === "问这条档案")
  await askButton.trigger("click")

  expect(assistantOpener).toHaveBeenCalledWith({
    projectId: "project-a",
    context: {
      page: "world",
      scope: "current",
      target: { target_type: "world_entity", target_id: entity.id },
      focus_ref: {
        kind: "dossier_entry",
        entity_id: entity.id,
        entry_group_id: "group-1",
        revision_id: "revision-1",
      },
      focus_label: "档案条目：身份 · 修订 1",
    },
  })
  wrapper.unmount()
})

it("父页面仍有未保存世界资料时不打开档案助手", async () => {
  const assistantOpener = vi.fn(async () => undefined)
  const toast = vi.fn()
  const wrapper = mountEditor(baseApi(), { assistantContextReady: false }, {
    state: { currentProjectId: "project-a" },
    assistantOpener,
    toast,
  })
  await flushPromises()
  const askButton = wrapper.findAll(".object-dossier-editor__entry .object-dossier-editor__actions button")
    .find((button) => button.text().trim() === "问这条档案")
  await askButton.trigger("click")

  expect(assistantOpener).not.toHaveBeenCalled()
  expect(toast).toHaveBeenCalledWith(
    "先保存或取消未保存的资料，再按已保存版本打开助手讨论。",
    "warning",
  )
  wrapper.unmount()
})

it("新增条目携带明确面向、作者可见性和 Scene 有效范围，成功后才显示已保存", async () => {
  let finishCreate
  const api = baseApi({ world: {
    getEntityDossier: vi.fn().mockResolvedValueOnce(dossier()).mockResolvedValueOnce(dossier([currentEntry(), currentEntry({ id: "revision-2", facing_label: "状态", content: "抵达雾港。" })])),
    createEntityDossierEntry: vi.fn(() => new Promise((resolve) => { finishCreate = resolve })),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__new select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__new textarea").setValue("雾港旧账房的学徒。")
  await wrapper.get(".object-dossier-editor__new input").setValue("旧港, 账房")
  await wrapper.findAll(".object-dossier-editor__new form > label select").at(1).setValue("secret")
  await wrapper.get(".object-dossier-editor__validity select").setValue(sceneId)
  await wrapper.get(".object-dossier-editor__new form").trigger("submit")
  await flushPromises()

  expect(JSON.parse(localStorage.getItem(newEntryDraftKey))).toMatchObject({
    scope: { accountId: "account-test", projectId: "project-a", objectId: "entity-a", section: "dossier-entry-create" },
    base_version: null,
    payload: { facingKey: "core:identity", content: "雾港旧账房的学徒。", visibility: "secret", startSceneId: sceneId },
  })
  expect(api.world.createEntityDossierEntry).toHaveBeenCalledWith(entity.id, "project-a", {
    facing: { kind: "core", key: "identity" },
    content: "雾港旧账房的学徒。",
    tags: ["旧港", "账房"],
    visibility: "secret",
    story_field_key: null,
    validity: { start: { kind: "scene", id: sceneId }, end: null },
  })
  expect(wrapper.text()).not.toContain("档案条目已保存")
  finishCreate(currentEntry())
  await flushPromises()
  expect(wrapper.text()).toContain("档案条目已保存")
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("")
  expect(localStorage.getItem(newEntryDraftKey)).toBeNull()
  wrapper.unmount()
})

it("新建条目草稿按账户、作品和对象恢复且不自动提交", async () => {
  const first = mountEditor(baseApi())
  await flushPromises()
  await fillNewEntry(first)
  await flushPromises()

  expect(JSON.parse(localStorage.getItem(newEntryDraftKey))).toMatchObject({
    scope: { accountId: "account-test", projectId: "project-a", objectId: "entity-a" },
    payload: { content: "雾港的新档案草稿。", tagsText: "雾港, 账房", visibility: "secret", startSceneId: sceneId },
  })
  first.unmount()

  const api = baseApi()
  const resumed = mountEditor(api)
  await flushPromises()
  expect(resumed.get(".object-dossier-editor__new textarea").element.value).toBe("雾港的新档案草稿。")
  expect(resumed.get(".object-dossier-editor__new input").element.value).toBe("雾港, 账房")
  expect(resumed.text()).toContain("已恢复本机新增条目草稿")
  expect(api.world.createEntityDossierEntry).not.toHaveBeenCalled()

  await resumed.setProps({ projectId: "project-b", entity: { ...entity, id: "entity-b" } })
  await flushPromises()
  expect(resumed.get(".object-dossier-editor__new textarea").element.value).toBe("")
  expect(localStorage.getItem(newEntryDraftKey)).not.toBeNull()
  resumed.unmount()
})

it("切换对象后迟到的创建成功仍为原草稿写入已保存标记", async () => {
  let finishCreate
  const api = baseApi({ world: {
    createEntityDossierEntry: vi.fn(() => new Promise((resolve) => { finishCreate = resolve })),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await fillNewEntry(wrapper, { content: "切换后迟到保存的条目。", startScene: "" })
  await wrapper.get(".object-dossier-editor__new form").trigger("submit")
  await flushPromises()
  expect(api.world.createEntityDossierEntry).toHaveBeenCalledOnce()

  await wrapper.setProps({ projectId: "project-b", entity: { ...entity, id: "entity-b" } })
  await flushPromises()
  finishCreate(currentEntry())
  await flushPromises()
  expect(JSON.parse(localStorage.getItem(newEntryDraftKey)).payload.saved_after_create).toBe(true)
  wrapper.unmount()

  const resumedApi = baseApi()
  const resumed = mountEditor(resumedApi)
  await flushPromises()
  expect(resumed.text()).toContain("服务器已保存此条目")
  expect(resumed.find(".object-dossier-editor__new form").exists()).toBe(false)
  expect(resumedApi.world.createEntityDossierEntry).not.toHaveBeenCalled()
  resumed.unmount()
})

it("本机备份失败和服务端新增失败时保留页面输入", async () => {
  const storage = { getItem: () => null, setItem: () => { throw new Error("quota") }, removeItem: () => {} }
  const api = baseApi({ world: { createEntityDossierEntry: vi.fn().mockRejectedValue(new Error("网络失败")) } })
  const wrapper = mountEditor(api, {}, { localDraftStorage: storage })
  await flushPromises()
  await fillNewEntry(wrapper, { content: "没有丢失的新档案。", startScene: "" })
  await flushPromises()

  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("没有丢失的新档案。")
  expect(wrapper.text()).toContain("新增档案草稿无法备份")
  await wrapper.get(".object-dossier-editor__new form").trigger("submit")
  await flushPromises()
  expect(wrapper.text()).toContain("网络失败")
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("没有丢失的新档案。")
  expect(api.world.createEntityDossierEntry).toHaveBeenCalledOnce()
  wrapper.unmount()
})

it("服务器已保存但本机清理失败时标记副本并阻止重复新增", async () => {
  const stored = new Map()
  const storage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: () => { throw new Error("storage locked") },
  }
  const api = baseApi()
  const wrapper = mountEditor(api, {}, { localDraftStorage: storage })
  await flushPromises()
  await fillNewEntry(wrapper, { content: "只创建一次的条目。", startScene: "" })
  await wrapper.get(".object-dossier-editor__new form").trigger("submit")
  await flushPromises()

  expect(api.world.createEntityDossierEntry).toHaveBeenCalledOnce()
  expect(wrapper.find(".object-dossier-editor__new form").exists()).toBe(false)
  expect(wrapper.text()).toContain("服务器已保存，但本机副本未能清理")
  expect(JSON.parse(stored.get(newEntryDraftKey)).payload.saved_after_create).toBe(true)
  wrapper.unmount()

  storage.removeItem = (key) => stored.delete(key)
  const resumedApi = baseApi()
  const resumed = mountEditor(resumedApi, {}, { localDraftStorage: storage })
  await flushPromises()
  expect(resumed.text()).toContain("服务器已保存此条目")
  expect(resumed.find(".object-dossier-editor__new form").exists()).toBe(false)
  expect(resumedApi.world.createEntityDossierEntry).not.toHaveBeenCalled()
  await resumed.findAll(".object-dossier-editor__new button").find((button) => button.text().includes("清除已保存条目的本机副本")).trigger("click")
  expect(stored.has(newEntryDraftKey)).toBe(false)
  expect(resumed.find(".object-dossier-editor__new form").exists()).toBe(true)
  resumed.unmount()
})

it("放弃新增条目草稿需要确认并清理本机副本", async () => {
  const confirm = vi.fn(() => false)
  const wrapper = mountEditor(baseApi(), {}, { confirm })
  await flushPromises()
  await fillNewEntry(wrapper, { content: "需要确认放弃的草稿。", startScene: "" })
  await flushPromises()
  expect(localStorage.getItem(newEntryDraftKey)).not.toBeNull()

  const discard = wrapper.findAll(".object-dossier-editor__new button").find((button) => button.text().trim() === "放弃新增草稿")
  await discard.trigger("click")
  expect(confirm).toHaveBeenCalledOnce()
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("需要确认放弃的草稿。")
  expect(localStorage.getItem(newEntryDraftKey)).not.toBeNull()

  confirm.mockReturnValue(true)
  await discard.trigger("click")
  await flushPromises()
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("")
  expect(localStorage.getItem(newEntryDraftKey)).toBeNull()
  expect(wrapper.text()).toContain("新增档案草稿已放弃")
  wrapper.unmount()
})

it("恢复到已删除 Story 场景的新增草稿时要求重新选择范围", async () => {
  localStorage.setItem(newEntryDraftKey, JSON.stringify({
    schema_version: 1,
    scope: { accountId: "account-test", projectId: "project-a", objectId: "entity-a", section: "dossier-entry-create" },
    base_version: null,
    saved_at: new Date().toISOString(),
    payload: { facingKey: "core:identity", content: "范围需要重核的草稿。", tagsText: "", visibility: "public", startSceneId: "missing-scene", endSceneId: "", storyFieldKey: "" },
  }))
  const api = baseApi()
  const wrapper = mountEditor(api)
  await flushPromises()
  expect(wrapper.text()).toContain("草稿中的 Story 场景已变化")
  await wrapper.get(".object-dossier-editor__new form").trigger("submit")
  expect(wrapper.text()).toContain("草稿中的 Story 场景已变化")
  expect(api.world.createEntityDossierEntry).not.toHaveBeenCalled()
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("范围需要重核的草稿。")
  wrapper.unmount()
})

it("409 后保留编辑草稿，作者选择按服务器修订重新提交", async () => {
  const serverRevision = currentEntry({ id: "revision-2", revision_number: 2, content: "服务器内容。" })
  const stale = Object.assign(new Error("档案已在别处更新"), { status: 409 })
  const api = baseApi({ world: {
    getEntityDossier: vi.fn().mockResolvedValueOnce(dossier()).mockResolvedValueOnce(dossier([serverRevision])).mockResolvedValueOnce(dossier([currentEntry({ id: "revision-3", revision_number: 3, content: "我的草稿。" })])),
    updateEntityDossierEntry: vi.fn().mockRejectedValueOnce(stale).mockResolvedValueOnce(currentEntry({ id: "revision-3", revision_number: 3 })),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await wrapper.get(".object-dossier-editor__entry form textarea").setValue("我的草稿。")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()

  expect(wrapper.get(".object-dossier-editor__entry form textarea").element.value).toBe("我的草稿。")
  expect(wrapper.text()).toContain("服务器已有修订 2")
  await wrapper.get(".object-dossier-editor__conflict-actions button:last-child").trigger("click")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()

  expect(api.world.updateEntityDossierEntry).toHaveBeenNthCalledWith(1, entity.id, "revision-1", "project-a", expect.objectContaining({ expected_revision_id: "revision-1", content: "我的草稿。" }))
  expect(api.world.updateEntityDossierEntry).toHaveBeenNthCalledWith(2, entity.id, "revision-2", "project-a", expect.objectContaining({ expected_revision_id: "revision-2", content: "我的草稿。" }))
  expect(wrapper.text()).toContain("档案新修订已保存")
  expect(localStorage.getItem("author-workspace-draft:v1:account-test:project-a:entity-a:dossier-group-1")).toBeNull()
  wrapper.unmount()
})

it("编辑已保存条目可清除旧章节有效期并以当前修订保存", async () => {
  const limited = currentEntry({ validity: { start: { kind: "chapter", id: sceneId }, end: null } })
  const api = baseApi({ world: {
    getEntityDossier: vi.fn(async () => dossier([limited])),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  const start = wrapper.get(".object-dossier-editor__entry form .object-dossier-editor__validity select")
  expect(start.element.value).toBe(`chapter:${sceneId}`)
  await start.setValue("")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()
  expect(api.world.updateEntityDossierEntry).toHaveBeenCalledWith(entity.id, "revision-1", "project-a", expect.objectContaining({
    expected_revision_id: "revision-1",
    validity: null,
  }))
  wrapper.unmount()
})

it("编辑结构化旧档案时提交原类型值，由服务端派生存储文本", async () => {
  const entry = currentEntry({
    legacy_field_key: "species_profiles.abilities_json",
    legacy_value: [{ name: "夜视", description: "可在黑暗中看清" }],
    content: "夜视：可在黑暗中看清",
  })
  const api = baseApi({ world: {
    getEntityDossier: vi.fn(async () => dossier([entry])),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await wrapper.get(".object-dossier-editor__legacy-value input").setValue("强化夜视")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()

  expect(api.world.updateEntityDossierEntry).toHaveBeenCalledWith(entity.id, entry.id, "project-a", expect.objectContaining({
    legacy_value: [{ name: "强化夜视", description: "可在黑暗中看清" }],
  }))
  expect(api.world.updateEntityDossierEntry.mock.calls[0][3]).not.toHaveProperty("content")
  wrapper.unmount()
})

it.each([{ legacyValue: ["leader-a"] }, { legacyValue: [] }])("字符串数组 $legacyValue 新增、清空后再新增仍提交字符串", async ({ legacyValue }) => {
  const entry = currentEntry({
    legacy_field_key: "faction_profiles.leader_entity_ids_json",
    legacy_value: legacyValue,
    content: legacyValue.join("；"),
  })
  const api = baseApi({ world: { getEntityDossier: vi.fn(async () => dossier([entry])) } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  const add = () => wrapper.findAll(".object-dossier-editor__legacy-value button").find(button => button.text() === "添加一项").trigger("click")
  await add()
  expect(wrapper.findAll(".object-dossier-editor__legacy-value input").map(input => input.element.value)).toEqual([...legacyValue, ""])
  while (wrapper.findAll(".object-dossier-editor__legacy-value input").length) {
    await wrapper.findAll(".object-dossier-editor__legacy-value button").find(button => button.text() === "移除此项").trigger("click")
  }
  expect(wrapper.findAll(".object-dossier-editor__legacy-value input")).toHaveLength(0)
  await add()
  await wrapper.get(".object-dossier-editor__legacy-value input").setValue("leader-b")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()
  expect(api.world.updateEntityDossierEntry.mock.calls[0][3].legacy_value).toEqual(["leader-b"])
  wrapper.unmount()
})

it("无名称键的对象数组使用可读标签展示，保存只提交原类型值", async () => {
  const entry = currentEntry({
    legacy_field_key: "faction_profiles.resources_json",
    legacy_value: [{ resource: "盐铁", amount: 3 }],
    content: "resource：盐铁；amount：3",
  })
  const api = baseApi({ world: { getEntityDossier: vi.fn(async () => dossier([entry])) } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  expect(wrapper.get(".object-dossier-editor__legacy-value").text()).not.toMatch(/resource|amount/)
  await wrapper.get(".object-dossier-editor__legacy-value input").setValue("盐矿")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()
  const payload = api.world.updateEntityDossierEntry.mock.calls[0][3]
  expect(payload.legacy_value).toEqual([{ resource: "盐矿", amount: 3 }])
  expect(payload).not.toHaveProperty("content")
  expect(wrapper.text()).toContain("档案新修订已保存")
  wrapper.unmount()
})

it("按 Scene 重读作者有效期结果，并保存精确绑定的 Story 字段键", async () => {
  const validity = { start: { kind: "scene", id: sceneId }, end: null }
  const aligned = currentEntry({
    story_field_key: "hull_condition",
    validity,
    validity_conflict: true,
    validity_gap: "story_source_unverified",
  })
  const customEntity = { ...entity, entity_type: "airship" }
  const api = baseApi({ world: {
    getEntityDossier: vi.fn(async (_entityId, _projectId, options = {}) => dossier([aligned], {
      as_of_scene_id: options.asOfSceneId || null,
      allow_story_override: true,
    })),
    getEntityDossierTemplate: vi.fn(async () => ({
      profile_type: "airship",
      version_number: 4,
      fields: [],
      state_fields: [
        { key: "hull_condition", label: "船体状况", value_kind: "text" },
        { key: "drive_condition", label: "引擎状况", value_kind: "text" },
      ],
      display_schema: {},
    })),
    updateEntityDossierEntry: vi.fn(async () => aligned),
  } })
  const wrapper = mountEditor(api, { entity: customEntity })
  await flushPromises()

  expect(wrapper.text()).toContain("来源或截止点暂不可核实")
  await wrapper.get(".object-dossier-editor__read-controls select").setValue(sceneId)
  await wrapper.get('[data-action="dossier-reload"]').trigger("click")
  await flushPromises()
  expect(api.world.getEntityDossier).toHaveBeenLastCalledWith(entity.id, "project-a", expect.objectContaining({ asOfSceneId: sceneId }))
  expect(wrapper.text()).toContain("剧情覆盖设置已开启")

  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  const fieldSelect = wrapper.findAll(".object-dossier-editor__entry form select").at(1)
  expect(fieldSelect.text()).toContain("船体状况")
  await fieldSelect.setValue("drive_condition")
  await wrapper.get(".object-dossier-editor__entry form").trigger("submit")
  await flushPromises()

  expect(api.world.updateEntityDossierEntry).toHaveBeenCalledWith(entity.id, aligned.id, "project-a", expect.objectContaining({
    story_field_key: "drive_condition",
    validity,
  }))
  wrapper.unmount()
})

it("历史恢复需要第二次明确确认，并携带当前修订 CAS", async () => {
  const old = currentEntry({ id: "revision-old", revision_number: 1, content: "更早的设定。", status: "superseded" })
  const active = currentEntry({ id: "revision-current", revision_number: 2, content: "当前设定。" })
  const api = baseApi({ world: {
    getEntityDossier: vi.fn().mockResolvedValueOnce(dossier([active])).mockResolvedValueOnce(dossier([currentEntry({ id: "revision-restored", revision_number: 3, content: "更早的设定。" })])),
    listEntityDossierHistory: vi.fn(async () => ({ entries: [active, old], total_count: 2, omitted_count: 0 })),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  const history = wrapper.get(".object-dossier-editor__history")
  history.element.open = true
  await history.trigger("toggle")
  await flushPromises()
  await wrapper.get(".object-dossier-editor__history-item button").trigger("click")
  expect(api.world.restoreEntityDossierEntry).not.toHaveBeenCalled()
  await wrapper.get(".object-dossier-editor__restore button.btn-primary").trigger("click")
  await flushPromises()
  expect(api.world.restoreEntityDossierEntry).toHaveBeenCalledWith(entity.id, "group-1", "project-a", {
    revision_id: "revision-old",
    expected_current_revision_id: "revision-current",
  })
  expect(wrapper.text()).toContain("已恢复“身份”的历史版本")
  wrapper.unmount()
})

it("读写模板时仅在成功后标记版本，409 保留本地字段", async () => {
  const missing = Object.assign(new Error("Not found"), { status: 404 })
  const api = baseApi({ world: {
    getEntityDossierTemplate: vi.fn().mockRejectedValueOnce(missing),
    saveEntityDossierTemplate: vi.fn(async (_type, _project, payload) => ({ profile_type: "character", version_number: 1, fields: payload.fields, display_schema: payload.display_schema })),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  await wrapper.get(".object-dossier-editor__template-fields > label select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__template-fields > button").trigger("click")
  await wrapper.get("[aria-label='模板字段显示名称']").setValue("人物身份")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__actions button").trigger("click")
  await flushPromises()

  expect(api.world.saveEntityDossierTemplate).toHaveBeenCalledWith("character", "project-a", {
    expected_version_number: null,
    borrowed_facings: [],
    fields: [{ facing: { kind: "core", key: "identity" }, label: "人物身份", description: "身份与社会位置", required: false, value_kind: "text" }],
    state_fields: [],
    display_schema: {},
  })
  expect(wrapper.text()).toContain("模板已保存为第 1 版")
  wrapper.unmount()
})

it("自定义对象模板可显式选择来源类型并借用内核面向", async () => {
  const customEntity = { id: "entity-spirit", entity_type: "spirit_beast", name: "照夜" }
  const api = baseApi({ world: {
    getEntityDossier: vi.fn(async () => dossier([], { entity_type: "spirit_beast" })),
    getEntityDossierTemplate: vi.fn(async () => ({
      profile_type: "spirit_beast", version_number: 1, borrowed_facings: [], fields: [], state_fields: [], display_schema: {},
    })),
    listDossierFacetsForType: vi.fn(async () => ({
      items: [{ facing: { kind: "core", key: "appearance" }, label: "外貌", source: "core" }],
    })),
    saveEntityDossierTemplate: vi.fn(async (_type, _project, payload) => ({
      profile_type: "spirit_beast", version_number: 2, borrowed_facings: payload.borrowed_facings, fields: payload.fields, state_fields: [], display_schema: {},
    })),
  } })
  const wrapper = mountEditor(api, { entity: customEntity })
  await flushPromises()
  const borrowed = wrapper.get(".object-dossier-editor__borrowed-facings")
  borrowed.element.open = true
  await borrowed.trigger("toggle")
  const selects = borrowed.findAll("select")
  await selects[0].setValue("character")
  await flushPromises()
  await borrowed.findAll("select")[1].setValue("appearance")
  await borrowed.find("button.btn:not(.btn-ghost)").trigger("click")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__actions button").trigger("click")
  await flushPromises()

  expect(api.world.listDossierFacetsForType).toHaveBeenCalledWith("character", "project-a", { cache: "no-store" })
  expect(api.world.saveEntityDossierTemplate).toHaveBeenCalledWith("spirit_beast", "project-a", expect.objectContaining({
    expected_version_number: 1,
    borrowed_facings: [{ kind: "core", key: "borrowed:character:appearance" }],
  }))
  expect(wrapper.text()).toContain("模板已保存为第 2 版")
  wrapper.unmount()
})

it("只读演示不显示档案、历史恢复或模板写入操作", async () => {
  const wrapper = mountEditor(baseApi(), { readOnly: true })
  await flushPromises()
  expect(wrapper.text()).toContain("只读演示")
  expect(wrapper.text()).not.toContain("新增档案条目")
  expect(wrapper.find(".object-dossier-editor__entry > .object-dossier-editor__actions").exists()).toBe(false)
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  expect(wrapper.find(".object-dossier-editor__templates .object-dossier-editor__actions").exists()).toBe(false)
  expect(wrapper.find(".object-dossier-editor__template-fields > button").exists()).toBe(false)
  wrapper.unmount()
})

it("对象切换后不让较晚返回的旧档案覆盖新对象", async () => {
  let finishOldRead
  const api = baseApi({ world: {
    getEntityDossier: vi.fn((entityId) => entityId === entity.id
      ? new Promise((resolve) => { finishOldRead = resolve })
      : Promise.resolve(dossier([currentEntry({ entity_id: "entity-b", content: "新对象的稳定档案。" })]))),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.setProps({ entity: { ...entity, id: "entity-b", name: "新对象" } })
  await flushPromises()
  expect(wrapper.text()).toContain("新对象的稳定档案")
  finishOldRead(dossier([currentEntry({ content: "旧对象迟到的档案。" })]))
  await flushPromises()
  expect(wrapper.text()).toContain("新对象的稳定档案")
  expect(wrapper.text()).not.toContain("旧对象迟到的档案")
  wrapper.unmount()
})

it("模板 409 后保留本地字段草稿，并允许作者明确以服务器版本为 CAS 基线", async () => {
  const missing = Object.assign(new Error("Not found"), { status: 404 })
  const stale = Object.assign(new Error("模板已在别处更新"), { status: 409 })
  const serverTemplate = { profile_type: "character", version_number: 2, fields: [], display_schema: {} }
  const api = baseApi({ world: {
    getEntityDossierTemplate: vi.fn().mockRejectedValueOnce(missing).mockResolvedValueOnce(serverTemplate).mockResolvedValueOnce(serverTemplate),
    saveEntityDossierTemplate: vi.fn().mockRejectedValueOnce(stale).mockResolvedValueOnce({ ...serverTemplate, version_number: 3 }),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  await wrapper.get(".object-dossier-editor__template-fields > label select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__template-fields > button").trigger("click")
  await wrapper.get("[aria-label='模板字段显示名称']").setValue("我的字段")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__actions button").trigger("click")
  await flushPromises()

  expect(wrapper.text()).toContain("保留我的模板草稿")
  expect(wrapper.get("[aria-label='模板字段显示名称']").element.value).toBe("我的字段")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__conflict-actions button:last-child").trigger("click")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__actions button").trigger("click")
  await flushPromises()

  expect(api.world.saveEntityDossierTemplate).toHaveBeenNthCalledWith(2, "character", "project-a", expect.objectContaining({ expected_version_number: 2 }))
  expect(wrapper.text()).toContain("模板已保存为第 3 版")
  wrapper.unmount()
})

it("手动重读先确认并仅在本机副本可安全清除后才放弃新增草稿", async () => {
  const stored = new Map()
  let allowRemove = false
  const storage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: (key) => { if (!allowRemove) throw new Error("storage locked"); stored.delete(key) },
  }
  const confirm = vi.fn(() => true)
  const api = baseApi()
  const wrapper = mountEditor(api, {}, { localDraftStorage: storage, confirm })
  await flushPromises()
  await fillNewEntry(wrapper, { content: "重读前必须保留的草稿。", startScene: "" })
  await flushPromises()
  await wrapper.get('[data-action="dossier-reload"]').trigger("click")
  await flushPromises()

  expect(confirm).toHaveBeenCalledOnce()
  expect(api.world.getEntityDossier).toHaveBeenCalledTimes(1)
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("重读前必须保留的草稿。")
  expect(wrapper.text()).toContain("未能清除本机新增条目草稿")

  allowRemove = true
  await wrapper.get('[data-action="dossier-reload"]').trigger("click")
  await flushPromises()
  expect(api.world.getEntityDossier).toHaveBeenCalledTimes(2)
  expect(wrapper.get(".object-dossier-editor__new textarea").element.value).toBe("")
  expect(stored.has(newEntryDraftKey)).toBe(false)
  wrapper.unmount()
})

it("手动重读不能静默覆盖未保存的档案与模板草稿", async () => {
  const confirm = vi.fn(() => false)
  const api = baseApi()
  const wrapper = mountEditor(api, {}, { confirm })
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await wrapper.get(".object-dossier-editor__entry form textarea").setValue("尚未保存的对象内容")
  await wrapper.get('[data-action="dossier-reload"]').trigger("click")
  await flushPromises()
  expect(confirm).toHaveBeenCalled()
  expect(api.world.getEntityDossier).toHaveBeenCalledTimes(1)
  expect(wrapper.get(".object-dossier-editor__entry form textarea").element.value).toBe("尚未保存的对象内容")

  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  await wrapper.get(".object-dossier-editor__template-fields > label select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__template-fields > button").trigger("click")
  await wrapper.get("[aria-label='模板字段显示名称']").setValue("尚未保存的模板字段")
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  expect(api.world.getEntityDossierTemplate).toHaveBeenCalledTimes(2)
  expect(wrapper.get("[aria-label='模板字段显示名称']").element.value).toBe("尚未保存的模板字段")
  wrapper.unmount()
})

it("模板 409 后二次读取的旧项目响应不能污染新对象", async () => {
  let finishOldTemplate
  const stale = Object.assign(new Error("模板已在别处更新"), { status: 409 })
  const api = baseApi({ world: {
    getEntityDossierTemplate: vi.fn((_type, projectId) => projectId === "project-a"
      ? new Promise((resolve) => { finishOldTemplate = resolve })
      : Promise.resolve({ profile_type: "character", version_number: 5, fields: [], display_schema: {} })),
    saveEntityDossierTemplate: vi.fn().mockRejectedValue(stale),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  // The first template read is explicit; resolve it before editing.
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  finishOldTemplate({ profile_type: "character", version_number: 1, fields: [], display_schema: {} })
  await flushPromises()
  await wrapper.get(".object-dossier-editor__template-fields > label select").setValue("core:identity")
  await wrapper.get(".object-dossier-editor__template-fields > button").trigger("click")
  await wrapper.get(".object-dossier-editor__templates .object-dossier-editor__actions button").trigger("click")
  await flushPromises()
  await wrapper.setProps({ projectId: "project-b", entity: { ...entity, id: "entity-b" } })
  await flushPromises()
  await wrapper.get(".object-dossier-editor__templates > header button").trigger("click")
  await flushPromises()
  finishOldTemplate({ profile_type: "character", version_number: 2, fields: [], display_schema: {} })
  await flushPromises()
  expect(wrapper.text()).toContain("当前模板第 5 版")
  expect(wrapper.text()).not.toContain("模板已在别处更新")
  wrapper.unmount()
})

it("历史恢复 409 后迟到的旧对象重读不能写入新对象错误状态", async () => {
  let finishOldDossier
  const old = currentEntry({ id: "revision-old", status: "superseded", content: "历史内容。" })
  const active = currentEntry({ id: "revision-current", revision_number: 2 })
  const stale = Object.assign(new Error("旧对象修订冲突"), { status: 409 })
  const api = baseApi({ world: {
    getEntityDossier: vi.fn((id, projectId) => projectId === "project-b"
      ? Promise.resolve(dossier([currentEntry({ entity_id: id, content: "新对象内容。" })]))
      : api.world.getEntityDossier.mock.calls.length === 1
        ? Promise.resolve(dossier([active]))
        : new Promise((resolve) => { finishOldDossier = resolve })),
    listEntityDossierHistory: vi.fn(async () => ({ entries: [active, old], total_count: 2, omitted_count: 0 })),
    restoreEntityDossierEntry: vi.fn().mockRejectedValue(stale),
  } })
  const wrapper = mountEditor(api)
  await flushPromises()
  const history = wrapper.get(".object-dossier-editor__history")
  history.element.open = true
  await history.trigger("toggle")
  await flushPromises()
  await wrapper.get(".object-dossier-editor__history-item button").trigger("click")
  await wrapper.get(".object-dossier-editor__restore button.btn-primary").trigger("click")
  await flushPromises()
  await wrapper.setProps({ projectId: "project-b", entity: { ...entity, id: "entity-b" } })
  await flushPromises()
  finishOldDossier(dossier([active]))
  await flushPromises()
  expect(wrapper.vm.restoreError).toBe("")
  expect(wrapper.text()).toContain("新对象内容。")
  wrapper.unmount()
})

it("同一档案修订的本机编辑草稿可在重新进入后恢复", async () => {
  const entry = currentEntry()
  const api = baseApi({ world: { getEntityDossier: vi.fn(async () => dossier([entry])) } })
  const first = mountEditor(api)
  await flushPromises()
  await first.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await first.get("[data-dossier-field='content']").setValue("未保存的档案补充。")
  await flushPromises()

  const key = "author-workspace-draft:v1:account-test:project-a:entity-a:dossier-group-1"
  expect(JSON.parse(localStorage.getItem(key))).toMatchObject({ base_version: "revision-1", payload: { content: "未保存的档案补充。" } })
  first.unmount()

  const resumed = mountEditor(api)
  await flushPromises()
  await resumed.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  expect(resumed.get("[data-dossier-field='content']").element.value).toBe("未保存的档案补充。")
  expect(resumed.text()).toContain("已恢复与当前修订匹配的本机草稿")
  expect(api.world.updateEntityDossierEntry).not.toHaveBeenCalled()
  resumed.unmount()
})

it("旧修订草稿先停止编辑，核对最新修订后只重放作者改动字段", async () => {
  const original = currentEntry()
  const api = baseApi({ world: { getEntityDossier: vi.fn(async () => dossier([original])) } })
  const first = mountEditor(api)
  await flushPromises()
  await first.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await first.get("[data-dossier-field='content']").setValue("我的离线补充。")
  await flushPromises()
  first.unmount()

  const server = currentEntry({ id: "revision-2", revision_number: 2, content: "服务器正文。", tags: ["服务器新标签"] })
  api.world.getEntityDossier.mockResolvedValue(dossier([server]))
  const resumed = mountEditor(api)
  await flushPromises()
  await resumed.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  expect(resumed.find("[data-conflict='local-dossier-draft']").exists()).toBe(true)
  expect(resumed.get("[data-dossier-field='content']").element.value).toBe("服务器正文。")
  expect(resumed.get("[data-dossier-field='content']").attributes("disabled")).toBeDefined()

  await resumed.find("[data-conflict='local-dossier-draft'] button").trigger("click")
  await flushPromises()
  expect(resumed.get("[data-dossier-field='content']").element.value).toBe("我的离线补充。")
  expect(resumed.find(".object-dossier-editor__entry form input").element.value).toBe("服务器新标签")
  const rebased = JSON.parse(localStorage.getItem("author-workspace-draft:v1:account-test:project-a:entity-a:dossier-group-1"))
  expect(rebased.base_version).toBe("revision-2")
  resumed.unmount()
})

it("放弃旧档案草稿需要明确确认且不会写入服务器", async () => {
  const original = currentEntry()
  const api = baseApi({ world: { getEntityDossier: vi.fn(async () => dossier([original])) } })
  const first = mountEditor(api)
  await flushPromises()
  await first.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await first.get("[data-dossier-field='content']").setValue("待明确放弃")
  await flushPromises()
  first.unmount()

  api.world.getEntityDossier.mockResolvedValue(dossier([currentEntry({ id: "revision-2", revision_number: 2 })]))
  const confirm = vi.fn(() => true)
  const resumed = mountEditor(api, {}, { confirm })
  await flushPromises()
  await resumed.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await resumed.findAll("[data-conflict='local-dossier-draft'] button")[1].trigger("click")

  expect(confirm).toHaveBeenCalled()
  expect(localStorage.getItem("author-workspace-draft:v1:account-test:project-a:entity-a:dossier-group-1")).toBeNull()
  expect(api.world.updateEntityDossierEntry).not.toHaveBeenCalled()
  expect(resumed.text()).toContain("已放弃本机草稿")
  resumed.unmount()
})

it("档案草稿存储失败会告警并保留编辑器输入", async () => {
  const api = baseApi()
  const storage = { getItem: () => null, setItem: () => { throw new Error("quota") }, removeItem: () => {} }
  const wrapper = mountEditor(api, {}, { localDraftStorage: storage })
  await flushPromises()
  await wrapper.get(".object-dossier-editor__entry > .object-dossier-editor__actions button").trigger("click")
  await wrapper.get("[data-dossier-field='content']").setValue("仍在页面里的档案草稿")
  await flushPromises()

  expect(wrapper.get("[data-dossier-field='content']").element.value).toBe("仍在页面里的档案草稿")
  expect(wrapper.get("[role='alert']").text()).toContain("本机草稿备份失败")
  expect(wrapper.emitted("dirty").at(-1)).toEqual([true])
  wrapper.unmount()
})
