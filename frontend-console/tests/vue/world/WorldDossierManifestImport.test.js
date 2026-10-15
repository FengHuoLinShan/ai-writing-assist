import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldDossierManifestImport from "../../../vue/views/world/library/WorldDossierManifestImport.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })

const entity = { id: "entity-a", entity_type: "character", name: "沈砚" }
const manifest = {
  format: "novelcraft.world.dossier-manifest", format_version: 1,
  source_project_id: "project-a", source_entity_name: "来源人物", template: null,
  entries: [{ source_revision_id: "revision-a", facing: { kind: "core", key: "appearance" }, facing_label: "外貌", content: "左眼有一道旧伤。", visibility: "secret", validity: null }],
}
function choose(wrapper, value = manifest) {
  const input = wrapper.get('input[type="file"]')
  const file = { name: "dossier.json", size: 400, text: vi.fn(async () => JSON.stringify(value)) }
  Object.defineProperty(input.element, "files", { configurable: true, value: [file] })
  input.element.dispatchEvent(new Event("change", { bubbles: true }))
  return flushPromises()
}

it("选择 JSON 后经预览和确认采用；409 保留文件并防止双点重写", async () => {
  let finishApply
  const stale = Object.assign(new Error("预览已过期"), { status: 409 })
  const api = {
    world: {
      getEntityDossierTemplate: vi.fn(async () => ({ version_number: 2, state_fields: [] })),
      previewEntityDossierManifest: vi.fn(async () => ({ preview_hash: "hash", create_count: 1, update_count: 0, already_imported_count: 0, skipped_count: 0, conflicts: [], warnings: [], can_apply: true })),
      applyEntityDossierManifest: vi.fn().mockRejectedValueOnce(stale).mockImplementationOnce(() => new Promise((resolve) => { finishApply = resolve })),
    },
    writing: { listChapters: vi.fn(async () => []) },
  }
  setBridgeOverrides({ api })
  const wrapper = mount(WorldDossierManifestImport, { props: { projectId: "project-a", entity, facets: [], scenes: [] } })
  await choose(wrapper)
  await flushPromises()
  expect(wrapper.vm.manifest).toEqual(manifest)
  await vi.waitFor(() => expect(wrapper.text()).toContain("左眼有一道旧伤"))
  await wrapper.get(".manifest-import__actions button").trigger("click")
  await flushPromises()
  expect(api.world.previewEntityDossierManifest).toHaveBeenCalledWith(entity.id, "project-a", expect.objectContaining({ manifest }))
  await wrapper.get(".manifest-import__review input[type='checkbox']").setValue(true)
  await wrapper.get(".manifest-import__review button").trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("预览已过期")
  expect(wrapper.text()).toContain("左眼有一道旧伤")
  await wrapper.get(".manifest-import__actions button").trigger("click")
  await flushPromises()
  await wrapper.get(".manifest-import__review input[type='checkbox']").setValue(true)
  await wrapper.get(".manifest-import__review button").trigger("click")
  await wrapper.get(".manifest-import__review button").trigger("click")
  expect(api.world.applyEntityDossierManifest).toHaveBeenCalledTimes(2)
  finishApply({ applied_count: 1, updated_count: 0 })
  await flushPromises()
  expect(wrapper.text()).toContain("已采用 1 条档案")
  await wrapper.setProps({ projectId: "project-b" })
  expect(wrapper.text()).not.toContain("左眼有一道旧伤")
  wrapper.unmount()
})

it("跨项目面向和 Scene 不猜来源 ID，必须由作者选择目标", async () => {
  const api = {
    world: { getEntityDossierTemplate: vi.fn(async () => ({ version_number: 1, state_fields: [] })), previewEntityDossierManifest: vi.fn() },
    writing: { listChapters: vi.fn(async () => []) },
  }
  setBridgeOverrides({ api })
  const wrapper = mount(WorldDossierManifestImport, { props: {
    projectId: "project-b", entity,
    facets: [{ facing: { kind: "project", term_id: "target-term" }, label: "修行境界" }],
    scenes: [{ id: "target-scene", label: "目标场景" }],
  } })
  await choose(wrapper, {
    ...manifest,
    entries: [{ ...manifest.entries[0], facing: { kind: "project", term_id: "source-term" }, validity: { start: { kind: "scene", id: "source-scene" }, end: null } }],
  })
  await flushPromises()
  await vi.waitFor(() => expect(wrapper.find(".manifest-import__actions button").exists()).toBe(true))
  expect(wrapper.get(".manifest-import__actions button").attributes("disabled")).toBeDefined()
  const selectors = wrapper.findAll("fieldset select")
  await selectors[0].setValue("project:target-term")
  await selectors[1].setValue("target-scene")
  await wrapper.get(".manifest-import__actions button").trigger("click")
  expect(api.world.previewEntityDossierManifest).toHaveBeenCalledWith(entity.id, "project-b", expect.objectContaining({
    facing_mappings: [{ source: { kind: "project", term_id: "source-term" }, target: { kind: "project", term_id: "target-term" } }],
    anchor_mappings: [{ source: { kind: "scene", id: "source-scene" }, target: { kind: "scene", id: "target-scene" } }],
  }))
  wrapper.unmount()
})
