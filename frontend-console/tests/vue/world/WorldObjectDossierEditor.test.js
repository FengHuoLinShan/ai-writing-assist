import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldObjectDossierEditor from "../../../vue/views/world/library/WorldObjectDossierEditor.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

afterEach(() => {
  resetBridgeOverrides()
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
  setBridgeOverrides({ api, ...bridge })
  return mount(WorldObjectDossierEditor, { props: { entity, projectId: "project-a", ...props } })
}

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
