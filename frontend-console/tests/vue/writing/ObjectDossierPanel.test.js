import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ObjectDossierPanel from "../../../vue/views/writing/components/ObjectDossierPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })

const id = (index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`
const scene = (sceneId = "scene-a", ids = [id(1)]) => ({
  id: sceneId,
  pov_character_id: null,
  structure_meta: { related_entity_ids: ids },
})
const mountPanel = (props = {}) => mount(ObjectDossierPanel, {
  props: { projectId: "project-a", scene: scene(), ...props },
})
const briefResponse = (entityIds, overrides = {}) => ({
  novel_id: "project-a",
  scene_id: "scene-a",
  world_items: [{
    kind: "world_dossier",
    entity_id: entityIds[0],
    entity_type: "character",
    entry_id: "entry-a",
    revision_id: "revision-a",
    facing_label: "身份与社会位置",
    content: "旧港账房的学徒。",
    tags: ["作者确认"],
    visibility: "public",
    validity: null,
    source_refs: [{ scene_id: "scene-a", quote: "他递上账本。" }],
  }],
  continuity_items: [{
    entity_id: entityIds[0],
    subject_label: "沈砚",
    dimension: "custody",
    field: "holder",
    value: "沈砚",
    layer: "fact",
    possibly_false: false,
    confidence: "confirmed",
    checkpoint_id: "checkpoint-a",
    source_refs: [],
  }],
  pattern_items: [],
  checkpoint_refs: [],
  omitted_count: 1,
  omissions: ["另有一项资料未纳入本次简报"],
  layers: ["world", "continuity"],
  unknown_layers: ["evolution"],
  coverage: "partial",
  fingerprint: "f".repeat(64),
  ...overrides,
})

it("只读取 Scene 明确的 UUID 关联，按每批 16 个调用作者管理 Evidence 简报", async () => {
  const entityIds = Array.from({ length: 17 }, (_, index) => id(index + 1))
  const getEntity = vi.fn(async (entityId) => ({ id: entityId, name: `对象 ${entityId.slice(-2)}`, entity_type: "character" }))
  const objectDossierBrief = vi.fn(async (payload) => briefResponse(payload.entity_ids))
  setBridgeOverrides({ api: { world: { getEntity }, context: { objectDossierBrief } } })
  const wrapper = mountPanel({ scene: {
    ...scene("scene-a", entityIds.slice(0, 2)),
    // Unrelated metadata and prose must never become object IDs.
    structure_meta: { related_entity_ids: entityIds.slice(0, 2), note: id(3), private: { target_id: id(4) } },
    must_happen: `提到 ${id(5)}`,
  } })
  await flushPromises()

  expect(getEntity).toHaveBeenCalledTimes(2)
  expect(getEntity.mock.calls.map(([entityId]) => entityId)).toEqual(entityIds.slice(0, 2))
  expect(wrapper.text()).toContain("对象 01")
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()

  expect(objectDossierBrief).toHaveBeenCalledTimes(1)
  expect(objectDossierBrief).toHaveBeenCalledWith(expect.objectContaining({
    novel_id: "project-a",
    scene_id: "scene-a",
    entity_ids: entityIds.slice(0, 2),
    reveal_mode: "author_full",
    content_mode: "canonical",
    include_patterns: false,
    only_adopted_patterns: false,
  }), { signal: expect.any(AbortSignal) })
  expect(wrapper.text()).toContain("稳定设定")
  expect(wrapper.text()).toContain("本场时点状态")
  expect(wrapper.text()).toContain("沈砚 · 保管人")
  expect(wrapper.text()).not.toContain("沈砚 · holder")
  expect(wrapper.text()).toContain("另有一项资料未纳入")
  expect(wrapper.text()).toContain("演化倾向未知")
  wrapper.unmount()
})

it("对象与有效期没有可读名称时使用友好说明，并显示可用的边界名称", async () => {
  const entityId = id(91)
  const objectDossierBrief = vi.fn(async (payload) => briefResponse(payload.entity_ids, {
    world_items: [{
      kind: "world_dossier", entity_id: entityId, entity_type: "character",
      entry_id: "entry-a", revision_id: "revision-a", content: "一份档案",
      visibility: "public",
      validity: {
        start: { kind: "scene", id: "scene-private-id", title: "旧港重逢" },
        end: { kind: "chapter", id: "chapter-private-id" },
      },
      source_refs: [],
    }],
  }))
  setBridgeOverrides({
    api: {
      world: {
        getEntity: vi.fn(async () => ({ id: entityId, entity_type: "character" })),
        getEntityDossierTemplate: vi.fn(async () => ({ profile_type: "character", version_number: 1, state_fields: [] })),
      },
      context: { objectDossierBrief },
    },
  })
  const wrapper = mountPanel({ scene: scene("scene-a", [entityId]) })
  await flushPromises()
  expect(wrapper.text()).toContain("未命名对象")
  await wrapper.get(".object-dossier__selection input").setValue(true)
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()

  expect(wrapper.text()).toContain("生效：旧港重逢 — 章节名称暂不可用")
  expect(wrapper.text()).not.toContain(entityId)
  expect(wrapper.text()).not.toContain("scene-private-id")
  expect(wrapper.text()).not.toContain("chapter-private-id")
  wrapper.unmount()
})

it("Scene 关联超过单批上限时继续分批；单批失败显示 unknown 占位", async () => {
  const entityIds = Array.from({ length: 17 }, (_, index) => id(index + 20))
  const objectDossierBrief = vi.fn()
    .mockRejectedValueOnce(new Error("第一批暂不可读"))
    .mockResolvedValueOnce(briefResponse([entityIds[16]]))
  setBridgeOverrides({ api: {
    world: { getEntity: vi.fn(async (entityId) => ({ id: entityId, name: `对象 ${entityId.slice(-2)}`, entity_type: "item" })) },
    context: { objectDossierBrief },
  } })
  const wrapper = mountPanel({ scene: scene("scene-a", entityIds) })
  await flushPromises()
  expect(wrapper.text()).toContain("每次请求最多 16 个对象")
  expect(wrapper.text()).toContain("读取所选对象（17）")
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()

  expect(objectDossierBrief).toHaveBeenCalledTimes(2)
  expect(objectDossierBrief.mock.calls[0][0].entity_ids).toHaveLength(16)
  expect(objectDossierBrief.mock.calls[1][0].entity_ids).toEqual([entityIds[16]])
  expect(wrapper.text()).toContain("第一批暂不可读")
  expect(wrapper.text()).toContain("这不表示对象没有档案")
  expect(wrapper.text()).toContain("另有一项资料未纳入")
  wrapper.unmount()
})

it("Scene 切换后丢弃旧简报响应", async () => {
  let resolveBrief
  const objectDossierBrief = vi.fn(() => new Promise((resolve) => { resolveBrief = resolve }))
  setBridgeOverrides({ api: {
    world: { getEntity: vi.fn(async (entityId) => ({ id: entityId, name: `对象 ${entityId.slice(-2)}`, entity_type: "character" })) },
    context: { objectDossierBrief },
  } })
  const wrapper = mountPanel({ scene: scene("scene-a", [id(1)]) })
  await flushPromises()
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()
  await wrapper.setProps({ scene: scene("scene-b", [id(2)]) })
  await flushPromises()
  resolveBrief(briefResponse([id(1)], { scene_id: "scene-a", world_items: [] }))
  await flushPromises()

  expect(wrapper.text()).toContain("对象 02")
  expect(wrapper.text()).not.toContain("旧港账房的学徒")
  wrapper.unmount()
})

it("台账倾向默认为关闭，作者勾选后可独立选择是否只看已采用项", async () => {
  const objectDossierBrief = vi.fn(async (payload) => briefResponse(payload.entity_ids, {
    pattern_items: [{
      entry_id: "pattern-a", revision_id: "pattern-rev", revision: 1, entity_ids: [id(1)],
      category: "表达", statement: "遇到压力时先确认账目", conditions: [], modality: "tends_to",
      confidence: 0.8, competing_explanations: [], review_verdict: "supported",
      author_decision: "adopted", evidence_refs: [{ kind: "chapter", id: "chapter-1" }], interpretation_only: true,
    }],
  }))
  setBridgeOverrides({ api: {
    world: { getEntity: vi.fn(async (entityId) => ({ id: entityId, name: "沈砚", entity_type: "character" })) },
    context: { objectDossierBrief },
  } })
  const wrapper = mountPanel()
  await flushPromises()
  expect(wrapper.findAll(".object-dossier__option input")).toHaveLength(1)
  await wrapper.find(".object-dossier__option input").setValue(true)
  await wrapper.find(".object-dossier__option--nested input").setValue(true)
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()
  expect(objectDossierBrief).toHaveBeenCalledWith(expect.objectContaining({
    include_patterns: true,
    only_adopted_patterns: true,
  }), { signal: expect.any(AbortSignal) })
  expect(wrapper.text()).toContain("遇到压力时先确认账目")
  wrapper.unmount()
})

it("只对自定义类型声明字段展示 Story 作者确认编辑器并在重读后清除已保存草稿", async () => {
  const entityId = id(8)
  const customEntity = { id: entityId, name: "灰隼号", entity_type: "airship" }
  const response = briefResponse([entityId], {
    continuity_items: [],
    validity_notices: [{
      entity_id: entityId,
      entry_id: "entry-validity-1",
      story_field_key: "hull_condition",
      status: "gap",
      gap: "story_source_unverified",
      world_evidence: [],
      story_observation: null,
    }],
  })
  const updated = briefResponse([entityId], {
    continuity_items: [{
      entity_id: entityId,
      subject_id: entityId,
      subject_label: "灰隼号",
      dimension: "entities",
      field: "hull_condition",
      value: "船腹有一道新裂口",
      layer: "fact",
      confidence: "confirmed",
      checkpoint_id: "checkpoint-custom",
      source_refs: [],
    }],
  })
  const objectDossierBrief = vi.fn()
    .mockResolvedValueOnce(response)
    .mockResolvedValueOnce(updated)
  const confirmCustomTextState = vi.fn(async () => ({ created: true }))
  const ensureSceneCheckpoints = vi.fn(async () => ({}))
  setBridgeOverrides({ api: {
    world: {
      getEntity: vi.fn(async () => customEntity),
      getEntityDossierTemplate: vi.fn(async () => ({
        profile_type: "airship",
        version_number: 3,
        state_fields: [{ key: "hull_condition", label: "船体状况", value_kind: "text" }],
      })),
    },
    context: { objectDossierBrief },
    story: { confirmCustomTextState, ensureSceneCheckpoints },
  } })
  const wrapper = mountPanel({ scene: scene("scene-a", [entityId]) })
  await flushPromises()

  await wrapper.get(".object-dossier__selection input").setValue(true)
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("自定义文字状态")
  expect(wrapper.find("textarea").exists()).toBe(true)
  expect(wrapper.text()).toContain("作者有效期核对")
  expect(wrapper.text()).toContain("Story 观察的来源暂不可核实")
  await wrapper.get("textarea").setValue("船腹有一道新裂口")
  await wrapper.get(".object-dossier__custom-state-actions button").trigger("click")
  await flushPromises()

  expect(confirmCustomTextState).toHaveBeenCalledWith("project-a", expect.objectContaining({
    confirmed: true,
    scene_id: "scene-a",
    entity_id: entityId,
    field_key: "hull_condition",
    value: "船腹有一道新裂口",
    expected_template_version_number: 3,
    idempotency_key: expect.any(String),
  }))
  expect(ensureSceneCheckpoints).toHaveBeenCalledWith("project-a", "scene-a")
  expect(wrapper.text()).toContain("本场已有作者确认记录：船腹有一道新裂口")
  wrapper.unmount()
})

it("Story 写入失败时保留自定义文字状态草稿", async () => {
  const entityId = id(9)
  const stale = Object.assign(new Error("模板已更新，请重读后重试"), { status: 409 })
  const confirmCustomTextState = vi.fn().mockRejectedValue(stale)
  setBridgeOverrides({ api: {
    world: {
      getEntity: vi.fn(async () => ({ id: entityId, name: "灰隼号", entity_type: "airship" })),
      getEntityDossierTemplate: vi.fn(async () => ({
        profile_type: "airship",
        version_number: 3,
        state_fields: [{ key: "hull_condition", label: "船体状况", value_kind: "text" }],
      })),
    },
    context: { objectDossierBrief: vi.fn(async (payload) => briefResponse(payload.entity_ids, { continuity_items: [] })) },
    story: { confirmCustomTextState, ensureSceneCheckpoints: vi.fn(async () => ({})) },
  } })
  const wrapper = mountPanel({ scene: scene("scene-a", [entityId]) })
  await flushPromises()
  await wrapper.get(".object-dossier__selection input").setValue(true)
  await wrapper.get(".object-dossier__header button").trigger("click")
  await flushPromises()
  await wrapper.get("textarea").setValue("船腹仍然完好")
  await wrapper.get(".object-dossier__custom-state-actions button").trigger("click")
  await flushPromises()

  expect(wrapper.get("textarea").element.value).toBe("船腹仍然完好")
  expect(wrapper.get('[role="alert"]').text()).toContain("模板已更新")
  wrapper.unmount()
})
