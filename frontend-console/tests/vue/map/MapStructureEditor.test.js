import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import MapStructureEditor from "../../../vue/views/map/MapStructureEditor.vue"
import { copyMap, emptyMap, geometrySignature, mapChanges, removeMapFeature } from "../../../vue/views/map/mapStructureEditor.js"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))
enableAutoUnmount(afterEach)

const nodeId = "20000000-0000-0000-0000-000000000001"
const projectId = "10000000-0000-0000-0000-000000000001"
const revisionId = "30000000-0000-0000-0000-000000000001"
const nextId = "30000000-0000-0000-0000-000000000002"
const feature = (id, label, x, y) => ({ id, kind: "location", label, points: [{ x, y }], locked: false, entity_id: null, target_node_id: null, depends_on: [], sources: [], note: "", reader_from_chapter: null })
const document = () => ({ ...emptyMap(), features: [feature("a", "临江城", 100, 100), feature("b", "黑石关", 300, 100), feature("c", "北堡", 100, 300)] })
const record = (data = document(), id = revisionId) => ({ id, node_id: nodeId, base_revision_id: null, status: "saved", document: data, problems: [], geometry_hash: "a".repeat(64), created_at: "2026-09-08T00:00:00Z" })
const state = revision => ({ node_id: nodeId, revision, candidates: [], image_layers: [], task_id: null, task_status: null })
const button = (wrapper, label) => wrapper.findAll("button").find(item => item.text() === label)

describe("统一地图编辑器", () => {
  let api, confirm
  beforeEach(() => {
    api = { world: {
      getNodeMap: vi.fn(async () => state(record())),
      saveMapRevision: vi.fn(async (_project, _node, payload) => record(copyMap(payload.document), nextId)),
      listMapRevisions: vi.fn(async () => []),
      layoutMap: vi.fn(),
      generateMapStructure: vi.fn(async () => ({ task_id: "task-1", status: "pending" })),
      reviewMapRevision: vi.fn(),
      previewReaderMap: vi.fn(),
      fetchReaderMapImage: vi.fn(async () => new Blob(["safe"])),
      fetchMapAtlasImage: vi.fn(async () => new Blob(["image"])),
      listEntities: vi.fn(async () => ({ items: [] })),
      createMapNode: vi.fn(),
    } }
    confirm = vi.fn(() => true)
    setBridgeOverrides({ api, confirm, router: { navigate: vi.fn() } })
    confirmAiReference.mockReset()
    confirmAiReference.mockResolvedValue({ id: "confirmation" })
    localStorage.clear()
    localStorage.setItem("novel_accountId", "test-account")
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:map")
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {})
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    resetBridgeOverrides()
  })
  const render = (props = {}) => mount(MapStructureEditor, { props: { projectId, node: { id: nodeId, title: "区域", level: "region" }, ...props } })

  it("无需图片连接即可编辑保存，文字使用安全的 SVG 文本", async () => {
    const wrapper = render()
    await flushPromises()
    expect(wrapper.findAll(".map-feature")).toHaveLength(3)
    await wrapper.get(".map-inspector input").setValue("<img src=x onerror=alert(1)>")
    expect(wrapper.get(".map-feature text").text()).toBe("<img src=x onerror=alert(1)>")
    expect(wrapper.find(".map-canvas img").exists()).toBe(false)
    await button(wrapper, "保存地图").trigger("click")
    await flushPromises()
    expect(api.world.saveMapRevision).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ base_revision_id: revisionId }))
    expect(wrapper.text()).toContain("已保存到服务端")
    expect(api.world.fetchMapAtlasImage).not.toHaveBeenCalled()
  })

  it("键盘替代按钮可移动地点，并可撤销重做", async () => {
    const wrapper = render()
    await flushPromises()
    await wrapper.get('button[aria-label="向右移动"]').trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("110")
    await button(wrapper, "撤销").trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("100")
    await button(wrapper, "重做").trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("110")
  })

  it("服务端与本地备份同时失败时不放行导航，也不声称已备份", async () => {
    const wrapper = render()
    await flushPromises()
    vi.stubGlobal("localStorage", { getItem: () => "test-account", setItem: () => { throw new DOMException("full", "QuotaExceededError") }, removeItem: vi.fn() })
    api.world.saveMapRevision.mockRejectedValue(new Error("保存失败"))
    await wrapper.get(".map-inspector input").setValue("我的新名称")
    await button(wrapper, "保存地图").trigger("click")
    await flushPromises()
    expect(wrapper.vm.canLeave()).toBe(false)
    expect(wrapper.text()).toContain("本机备份不可用")
    expect(wrapper.get(".map-save-status").text()).not.toContain("已保存")
    expect(wrapper.get(".map-inspector input").element.value).toBe("我的新名称")
  })

  it("版本冲突保留当前编辑与旧基准，先提供服务器版比较", async () => {
    const wrapper = render()
    await flushPromises()
    await wrapper.get(".map-inspector input").setValue("本机修改")
    const server = document(); server.features[0].label = "另一窗口修改"
    api.world.getNodeMap.mockResolvedValue(state(record(server, nextId)))
    api.world.saveMapRevision.mockRejectedValue(Object.assign(new Error("地图已更新"), { status: 409 }))
    await button(wrapper, "保存地图").trigger("click")
    await flushPromises()
    expect(wrapper.get(".map-inspector input").element.value).toBe("本机修改")
    expect(wrapper.text()).toContain("服务器已有更新")
    expect(wrapper.vm.revision.id).toBe(revisionId)
    await button(wrapper, "查看服务器版").trigger("click")
    expect(wrapper.get(".map-feature text").text()).toBe("另一窗口修改")
    await button(wrapper, "回到我的编辑").trigger("click")
    expect(wrapper.get(".map-feature text").text()).toBe("本机修改")
  })

  it("晚到布局不能覆盖请求之后的新编辑", async () => {
    const wrapper = render()
    await flushPromises()
    let finish
    api.world.layoutMap.mockReturnValue(new Promise(resolve => { finish = resolve }))
    await button(wrapper, "布置尚未定位的地点").trigger("click")
    await wrapper.get(".map-inspector input").setValue("布局请求后的编辑")
    finish({ document: document(), problems: [], image_layers: [] })
    await flushPromises()
    expect(wrapper.get(".map-inspector input").element.value).toBe("布局请求后的编辑")
    expect(wrapper.text()).toContain("返回预览时已有新编辑")
  })

  it("阅读预览只绘制服务端白名单，隐藏作者问题与候选", async () => {
    const revision = record()
    revision.problems = [{ code: "hidden", message: "后续章节秘密", feature_ids: [] }]
    api.world.getNodeMap.mockResolvedValue({ ...state(revision), candidates: [record(document(), nextId)] })
    api.world.previewReaderMap.mockResolvedValue({ features: [feature("a", "临江城", 100, 100)], images: [], chapter: 1 })
    const wrapper = render()
    await flushPromises()
    await button(wrapper, "预览读者所见").trigger("click")
    await flushPromises()
    expect(wrapper.findAll(".map-feature")).toHaveLength(1)
    expect(wrapper.find(".map-candidates").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("后续章节秘密")
    expect(wrapper.find(".map-edit-grid").exists()).toBe(false)
    expect(api.world.fetchMapAtlasImage).not.toHaveBeenCalled()
  })

  it("图片校准预览按服务端变换叠加，移动地点后立即退出底图", async () => {
    const pageId = "40000000-0000-0000-0000-000000000001"
    const data = document()
    data.images = [{ page_id: pageId, role: "background", feature_id: null, opacity: 0.6, anchors: [], geometry_hash: "a".repeat(64), reader_from_chapter: null, reader_image_hash: null }]
    api.world.getNodeMap.mockResolvedValue({ ...state(record(data)), image_layers: [{ page_id: pageId, role: "background", state: "ready", transform: [200, 0, 0, 200, 100, 100], opacity: 0.6 }] })
    const wrapper = render({ images: [{ id: pageId, title: "区域底图", image_hash: "b".repeat(64) }] })
    await flushPromises()
    expect(wrapper.get(".map-canvas image").attributes("transform")).toBe("matrix(200 0 0 200 100 100)")
    await wrapper.get('button[aria-label="向右移动"]').trigger("click")
    expect(wrapper.find(".map-canvas image").exists()).toBe(false)
    expect(wrapper.text()).toContain("待复核，已退出叠加")
  })

  it("空间生成固定地点范围并通过一次 Context 确认", async () => {
    api.world.listEntities.mockResolvedValue({ items: [
      { id: "location-1", name: "临江城", status: "canonical" },
      { id: "location-2", name: "未采用对象", status: "candidate" },
    ] })
    const wrapper = render()
    await flushPromises()
    await button(wrapper, "查找").trigger("submit")
    await wrapper.get(".map-inline-form").trigger("submit")
    await flushPromises()
    expect(wrapper.findAll(".map-location-list input")).toHaveLength(1)
    await wrapper.get(".map-location-list input").setValue(true)
    await button(wrapper, "用这些地点生成空间关系").trigger("click")
    await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ action: "world.map_atlas.structure", entity_ids: ["location-1"] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ base_revision_id: revisionId, context_confirmation_id: "confirmation", location_ids: ["location-1"] }))
  })

  it("候选可查看关系和图片变化，并与保存版对照而不改写当前编辑", async () => {
    const candidate = document()
    candidate.features[0].label = "临江新城"
    candidate.constraints = [{ id: "c1", subject: "a", target: "b", relation: "east", via: [], sources: [] }]
    candidate.images = [{ page_id: "private-page-id", role: "illustration", anchors: [] }]
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [record(candidate, nextId)] })
    const wrapper = render(); await flushPromises()
    await button(wrapper, "查看").trigger("click")
    expect(wrapper.get('[aria-label="候选地图差异"]').text()).toContain("空间关系：临江新城 → 黑石关")
    expect(wrapper.get('[aria-label="候选地图差异"]').text()).toContain("地点配图设置")
    expect(wrapper.text()).not.toContain("private-page-id")
    expect(wrapper.get(".map-feature text").text()).toBe("临江新城")
    await button(wrapper, "对照已保存地图").trigger("click")
    expect(wrapper.get(".map-feature text").text()).toBe("临江城")
    await button(wrapper, "返回当前地图").trigger("click")
    expect(wrapper.vm.dirty).toBe(false)
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it("专注浏览能查找选择地点，方向键和拖动不会改图", async () => {
    const wrapper = render(); await flushPromises()
    await button(wrapper, "专注看图").trigger("click")
    expect(wrapper.find(".map-edit-grid").exists()).toBe(false)
    await wrapper.get('.map-locator input').setValue("黑石")
    await button(wrapper, "黑石关").trigger("click"); await flushPromises()
    expect(wrapper.get('[aria-label="地图地点详情"]').text()).toContain("黑石关")
    const target = wrapper.get('[data-feature-id="b"]')
    await target.trigger("keydown", { key: "ArrowRight" })
    await target.get("circle").trigger("pointerdown", { button: 0 })
    expect(wrapper.vm.dirty).toBe(false)
    await button(wrapper, "展开编辑工具").trigger("click")
    expect(wrapper.find(".map-edit-grid").exists()).toBe(true)
  })
})

it("仅关系、图片或标注变化也能被版本比较发现", () => {
  const before = document(), after = document()
  before.constraints = [{ id: 'r', subject: 'a', target: 'b', relation: 'east' }]
  after.constraints = [{ id: 'r', subject: 'a', target: 'b', relation: 'west' }]
  before.images = [{ page_id: 'image', role: 'background', opacity: 0.5 }]
  after.images = [{ page_id: 'image', role: 'background', opacity: 0.8 }]
  after.annotation_bindings = [{ annotation_id: 'private-annotation', feature_id: 'b' }]
  expect(mapChanges(before, after)).toEqual(['调整：空间关系：临江城 → 黑石关', '调整：图片底图设置', '新增：图片标注绑定'])
})

it("移出依赖地点会使相关轮廓待定位，展示配置不改变空间签名", () => {
  const source = document()
  source.features.push({ ...feature("area", "边界", 0, 0), kind: "area", points: [{ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 200 }], depends_on: ["a"] })
  const signature = geometrySignature(source)
  source.features[0].reader_from_chapter = 9
  source.images.push({ page_id: "page", role: "illustration", anchors: [], feature_id: null })
  expect(geometrySignature(source)).toBe(signature)
  removeMapFeature(source, "a")
  expect(source.features.find(feature => feature.id === "area").points).toEqual([])
})
