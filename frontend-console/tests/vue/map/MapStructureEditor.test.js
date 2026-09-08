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
  let api, confirm, router
  beforeEach(() => {
    api = { world: {
      getNodeMap: vi.fn(async () => state(record())),
      saveMapRevision: vi.fn(async (_project, _node, payload) => record(copyMap(payload.document), nextId)),
      listMapRevisions: vi.fn(async () => []),
      layoutMap: vi.fn(),
      previewMapRevision: vi.fn(async () => ({ image_layers: [], problems: [] })),
      previewMapReview: vi.fn(async (_project, _node, candidate, payload) => ({ candidate_revision_id: candidate, base_revision_id: payload.base_revision_id, applied_change_keys: payload.change_keys, expanded_change_keys: [] })),
      generateMapStructure: vi.fn(async () => ({ task_id: "task-1", status: "pending" })),
      reviewMapRevision: vi.fn(),
      previewReaderMap: vi.fn(),
      fetchReaderMapImage: vi.fn(async () => new Blob(["safe"])),
      fetchMapAtlasImage: vi.fn(async () => new Blob(["image"])),
      listEntities: vi.fn(async () => ({ items: [] })),
      createMapNode: vi.fn(),
    } }
    confirm = vi.fn(() => true)
    router = { navigate: vi.fn() }
    setBridgeOverrides({ api, confirm, router })
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
    await wrapper.get('.map-locator input').setValue('黑石')
    expect(wrapper.get('.map-locator').text()).toContain('当前地图没有匹配内容')
    expect(wrapper.find('[data-feature-id="b"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="读者地点详情"]').exists()).toBe(true)
    await wrapper.get('.map-locator input').setValue('临江')
    await button(wrapper, '临江城').trigger('click')
    expect(wrapper.get('[aria-label="读者地点详情"]').text()).toBe('临江城')
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

  it("选择同名图片即显示缩略预览，已关联图片用地点说明用途", async () => {
    const data = document()
    data.images = [{ page_id: 'image-a', role: 'illustration', feature_id: 'a', anchors: [] }]
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render({ images: [{ id: 'image-a', title: '城市示意' }, { id: 'image-b', title: '城市示意' }] })
    await flushPromises()
    const select = wrapper.get('.map-image-controls select')
    expect(select.text()).toContain('临江城配图')
    await select.setValue('image-b'); await flushPromises()
    expect(api.world.fetchMapAtlasImage).toHaveBeenCalledWith(projectId, 'image-b')
    expect(wrapper.get('img[alt="待关联配图预览"]').attributes('src')).toBe('blob:map')
    expect(wrapper.vm.dirty).toBe(false)
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
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
    expect(wrapper.findAll(".map-world-locations input")).toHaveLength(1)
    await wrapper.get(".map-world-locations input").setValue(true)
    await button(wrapper, "用这些地点生成空间关系").trigger("click")
    await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ action: "world.map_atlas.structure", entity_ids: ["location-1"] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ base_revision_id: revisionId, context_confirmation_id: "confirmation", location_ids: ["location-1"] }))
  })

  it('已有手工图元带精确原文选择进入生成，无需先创建世界对象', async () => {
    const sourceRef = { draft_id: nextId, chapter_index: 30, version_number: 1, content_mode: 'canonical', start_offset: 0, end_offset: 45, source_hash: 'a'.repeat(64), range_hash: 'b'.repeat(64) }
    const data = document(); data.features[0].sources = [{ kind: 'source_range', id: nextId, source_hash: sourceRef.source_hash, source_ref: sourceRef, quote: '临江城位于河岸' }]
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render(); await flushPromises()
    const choices = wrapper.findAll('details').find(item => item.find('summary').text() === '整理地图中已有内容')
    await choices.get('input[type=checkbox]').setValue(true)
    await button(wrapper, '整理所选内容的空间关系').trigger('click'); await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ pinned_refs: [{ kind: 'source_range', source_ref: sourceRef }] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ location_ids: [], feature_ids: ['a'] }))
  })

  it('逐项采用只发送选择键，成功后保留剩余候选和明确反馈', async () => {
    const candidate = document(); candidate.features[0].note = '第一项'; candidate.features[1].note = '第二项'
    const proposed = { ...record(candidate, nextId), status: 'candidate', base_revision_id: revisionId }
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [proposed] })
    const wrapper = render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
    const selection = wrapper.findAll('.map-change-review input[type=checkbox]')
    await selection[1].setValue(false)
    const applied = document(); applied.features[0].note = '第一项'
    const saved = { ...record(applied, 'saved-part'), applied_change_keys: ['feature:a'], expanded_change_keys: [], remaining_candidate_id: 'remaining' }
    api.world.reviewMapRevision.mockResolvedValue(saved)
    api.world.getNodeMap.mockResolvedValue({ ...state(saved), candidates: [{ ...proposed, id: 'remaining', base_revision_id: saved.id }] })
    await button(wrapper, '核对所选 1 项修改').trigger('click'); await flushPromises()
    expect(api.world.reviewMapRevision).not.toHaveBeenCalled()
    await button(wrapper, '确认采用共 1 项修改').trigger('click'); await flushPromises()
    expect(api.world.reviewMapRevision).toHaveBeenCalledWith(projectId, nodeId, nextId, { base_revision_id: revisionId, action: 'adopt', change_keys: ['feature:a'] })
    expect(wrapper.text()).toContain('其余修改仍待确认')
    expect(wrapper.findAll('.map-candidates>div')).toHaveLength(1)
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it('返回或刷新恢复选中地点、缩放与专注状态，地图文档不改变', async () => {
    const wrapper = render({ initialFeatureId: 'b' }); await flushPromises()
    expect(wrapper.get('.map-feature.selected').attributes('data-feature-id')).toBe('b')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(150)
    wrapper.get('.map-scroll').element.scrollLeft = 120
    wrapper.get('.map-scroll').element.scrollTop = 80
    await wrapper.get('.map-scroll').trigger('scroll')
    wrapper.unmount()
    const restored = render(); await flushPromises()
    expect(restored.get('.map-feature.selected').attributes('data-feature-id')).toBe('b')
    expect(restored.get('[aria-label="空间地图缩放"]').element.value).toBe('150')
    expect(restored.get('.map-scroll').element.scrollLeft).toBe(120)
    expect(restored.get('.map-scroll').element.scrollTop).toBe(80)
    expect(button(restored, '展开编辑工具')).toBeTruthy()
    expect(restored.vm.dirty).toBe(false)
  })

  it('历史地图预览使用该版本的图片层，不改变当前编辑', async () => {
    const old = record(document(), 'historical')
    api.world.listMapRevisions.mockResolvedValue([old])
    api.world.previewMapRevision.mockResolvedValue({ image_layers: [{ page_id: 'old-image', state: 'ready', role: 'background', opacity: 0.8, transform: [200, 0, 0, 200, 10, 20] }], problems: [] })
    const wrapper = render(); await flushPromises()
    await wrapper.findAll('summary').find(item => item.text() === '地图历史').trigger('click'); await flushPromises()
    await button(wrapper, '查看并比较').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('正在查看历史地图')
    expect(wrapper.get('.map-canvas image').attributes('transform')).toBe('matrix(200 0 0 200 10 20)')
    expect(api.world.fetchMapAtlasImage).toHaveBeenCalledWith(projectId, 'old-image')
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it('采用前展示服务端展开的关联范围，正式采用仍仅发送作者选择', async () => {
    const candidate = document(); candidate.features[0].note = '原选择'; candidate.features[1].note = '依赖修改'
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [{ ...record(candidate, nextId), status: 'candidate', base_revision_id: revisionId }] })
    api.world.previewMapReview.mockResolvedValue({ candidate_revision_id: nextId, base_revision_id: revisionId, applied_change_keys: ['feature:a', 'feature:b'], expanded_change_keys: ['feature:b'] })
    const wrapper = render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
    await wrapper.findAll('.map-change-review input')[1].setValue(false)
    await button(wrapper, '核对所选 1 项修改').trigger('click'); await flushPromises()
    expect(wrapper.get('[aria-label="即将采用的修改"]').text()).toContain('黑石关（关联修改）')
    expect(api.world.reviewMapRevision).not.toHaveBeenCalled()
    api.world.reviewMapRevision.mockResolvedValue(record(candidate, 'adopted'))
    await button(wrapper, '确认采用共 2 项修改').trigger('click'); await flushPromises()
    expect(api.world.reviewMapRevision.mock.calls[0][3].change_keys).toEqual(['feature:a'])
  })

  it('修改选择后丢弃晚到范围预览，预览失败不能采用旧结果', async () => {
    const candidate = document(); candidate.features[0].note = 'A'; candidate.features[1].note = 'B'
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [{ ...record(candidate, nextId), status: 'candidate', base_revision_id: revisionId }] })
    let finish
    api.world.previewMapReview.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const wrapper = render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
    await button(wrapper, '核对所选 2 项修改').trigger('click')
    await wrapper.findAll('.map-change-review input')[1].setValue(false)
    finish({ candidate_revision_id: nextId, base_revision_id: revisionId, applied_change_keys: ['feature:a', 'feature:b'], expanded_change_keys: [] }); await flushPromises()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
    api.world.previewMapReview.mockRejectedValueOnce(Object.assign(new Error('需要确认移除图形'), { body: { context: { required_change_keys: ['feature:b'] } } }))
    await button(wrapper, '核对所选 1 项修改').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('请明确勾选关联修改后再采用：黑石关')
    expect(api.world.reviewMapRevision).not.toHaveBeenCalled()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
  })

  it('切换候选或服务器基准变化后不能继续用原范围确认', async () => {
    vi.useFakeTimers()
    const candidate = document(); candidate.features[0].note = 'A'
    const proposed = { ...record(candidate, nextId), status: 'candidate', base_revision_id: revisionId }
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [proposed], task_id: 'task', task_status: 'running' })
    const wrapper = render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
    await button(wrapper, '核对所选 1 项修改').trigger('click'); await flushPromises()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(true)
    api.world.getNodeMap.mockResolvedValue({ ...state(record(document(), 'server-new')), candidates: [proposed] })
    await vi.advanceTimersByTimeAsync(2500); await flushPromises()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
    wrapper.unmount(); vi.useRealTimers()
    const refreshed = render(); await flushPromises(); await button(refreshed, '查看').trigger('click'); await flushPromises()
    expect(refreshed.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
    expect(button(refreshed, '核对所选 1 项修改').attributes('disabled')).toBeDefined()
  })

  it('历史预览接收实时来源问题，并恢复当前版新鲜问题', async () => {
    const current = record(); current.problems = [{ code: 'current', message: '当前版来源变化', feature_ids: [] }]
    api.world.getNodeMap.mockResolvedValue(state(current))
    api.world.listMapRevisions.mockResolvedValue([record(document(), 'historical')])
    api.world.previewMapRevision.mockResolvedValue({ image_layers: [{ page_id: 'old-illustration', role: 'illustration', state: 'ready', feature_id: 'a' }], problems: [{ code: 'stale', message: '历史版正文来源已失效', feature_ids: ['a'] }] })
    const wrapper = render(); await flushPromises()
    await wrapper.findAll('summary').find(item => item.text() === '地图历史').trigger('click'); await flushPromises()
    await button(wrapper, '查看并比较').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('历史版正文来源已失效')
    expect(wrapper.get('[aria-label="地图地点详情"] img').attributes('src')).toBe('blob:map')
    await button(wrapper, '返回当前地图').trigger('click')
    expect(wrapper.text()).toContain('当前版来源变化')
    expect(wrapper.text()).not.toContain('历史版正文来源已失效')
  })

  it('图片固定对照生成版，改图保存及重新挂载后仍显示影响', async () => {
    const original = document(), data = document()
    data.features[0].points[0].x += 40
    data.images = [{ page_id: 'picture', role: 'background', anchors: [{ feature_id: 'a' }] }]
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    api.world.previewMapRevision.mockResolvedValue({ document: original, image_layers: [], problems: [] })
    const props = { images: [{ id: 'picture', title: '地图', source_map_revision_id: 'old-source' }] }
    let wrapper = render(props); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('picture'); await flushPromises()
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    await wrapper.get('button[aria-label="向右移动"]').trigger('click')
    await button(wrapper, '保存地图').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    wrapper.unmount(); wrapper = render(props); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('picture'); await flushPromises()
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    await button(wrapper, '对照图片生成时的地图').trigger('click'); await flushPromises()
    expect(api.world.previewMapRevision).toHaveBeenCalledWith(projectId, nodeId, 'old-source')
    expect(api.world.listMapRevisions).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('正在查看历史地图')
  })

  it('无生成版的上传图片明确说明基准未知，晚到基准不能套到另一图片', async () => {
    let finish
    api.world.previewMapRevision.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const wrapper = render({ images: [{ id: 'generated', title: '生成图片', source_map_revision_id: 'old-source' }, { id: 'uploaded', title: '上传图片' }] }); await flushPromises()
    const select = wrapper.get('.map-image-controls select')
    await select.setValue('generated'); await select.setValue('uploaded')
    finish({ document: document(), image_layers: [], problems: [] }); await flushPromises()
    expect(wrapper.text()).toContain('无法自动判断空间变化')
    expect(button(wrapper, '对照图片生成时的地图')).toBeUndefined()
    expect(wrapper.vm.dirty).toBe(false)
  })

  it('空白画布拖动和视口方向键只平移，触摸由原生滚动与缩放处理', async () => {
    const data = document(); data.features.push({ ...feature('area', '区域', 0, 0), kind: 'area', points: [{ x: 0, y: 0 }, { x: 400, y: 0 }, { x: 400, y: 400 }] })
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render(); await flushPromises()
    const viewport = wrapper.get('.map-scroll')
    viewport.element.scrollLeft = 100
    await wrapper.get('.map-paper').trigger('pointerdown', { button: 0, clientX: 90, clientY: 40, pointerId: 1, pointerType: 'mouse' })
    await viewport.trigger('pointermove', { clientX: 30, clientY: 10, pointerId: 1 })
    await viewport.trigger('pointerup', { pointerId: 1 })
    expect(viewport.element.scrollLeft).toBe(160)
    expect(viewport.element.scrollTop).toBe(30)
    await viewport.trigger('keydown', { key: 'ArrowRight' })
    expect(viewport.element.scrollLeft).toBe(240)
    await wrapper.get('.map-paper').trigger('pointerdown', { button: 0, clientX: 90, pointerId: 2, pointerType: 'touch' })
    await viewport.trigger('pointermove', { clientX: 10, pointerId: 2 })
    expect(viewport.element.scrollLeft).toBe(240)
    await wrapper.get('.map-kind-area polygon').trigger('pointerdown', { button: 0, clientX: 90, clientY: 30, pointerId: 3 })
    await viewport.trigger('pointermove', { clientX: 20, clientY: 30, pointerId: 3 })
    await viewport.trigger('pointerup', { pointerId: 3 })
    expect(wrapper.get('.map-feature.selected').attributes('data-feature-id')).toBe('a')
    await wrapper.get('.map-kind-area polygon').trigger('pointerdown', { button: 0, clientX: 90, clientY: 30, pointerId: 4 })
    await viewport.trigger('pointerup', { pointerId: 4 })
    expect(wrapper.get('.map-feature.selected').attributes('data-feature-id')).toBe('area')
    expect(wrapper.vm.dirty).toBe(false)
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it('线段中点可插入并移出指定控制点，保留撤销及最小几何限制', async () => {
    const data = document()
    data.features.push({ ...feature('road', '河边路', 0, 0), kind: 'road', points: [0, 100, 200, 300].map(x => ({ x, y: 0 })) })
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-feature-id="road"]').trigger('click')
    const select = label => wrapper.findAll('.map-inspector label').find(item => item.text().startsWith(label)).get('select')
    await select('控制点').setValue('1')
    await button(wrapper, '移出选中控制点').trigger('click')
    expect(wrapper.get('[data-feature-id="road"] polyline').attributes('points')).toBe('0,0 200,0 300,0')
    await select('插入位置').setValue('1')
    await button(wrapper, '在线段中点插入').trigger('click')
    expect(wrapper.get('[data-feature-id="road"] polyline').attributes('points')).toBe('0,0 200,0 250,0 300,0')
    await button(wrapper, '撤销').trigger('click')
    expect(wrapper.get('[data-feature-id="road"] polyline').attributes('points')).toBe('0,0 200,0 300,0')
    await select('控制点').setValue('0')
    await button(wrapper, '移出选中控制点').trigger('click')
    expect(button(wrapper, '移出选中控制点').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-feature-id="road"] polyline').attributes('points')).toBe('200,0 300,0')
  })

  it('密集标签优先显示选中内容，切账号不能读取或写入另一账号视角', async () => {
    const data = document(); data.features = ['a', 'b', 'c', 'd', 'e'].map(id => feature(id, '地点' + id, 100, 100))
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-feature-id="e"]').trigger('click')
    expect(wrapper.get('[data-feature-id="e"] text').text()).toBe('地点e')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(180)
    localStorage.setItem('novel_accountId', 'another-account')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(190)
    wrapper.unmount()
    const next = render(); await flushPromises()
    expect(next.get('[aria-label="空间地图缩放"]').element.value).toBe('100')
    expect(next.get('.map-feature.selected').attributes('data-feature-id')).toBe('a')
  })

  it("候选可查看关系和图片变化，并与保存版对照而不改写当前编辑", async () => {
    const candidate = document()
    candidate.features[0].label = "临江新城"
    candidate.constraints = [{ id: "c1", subject: "a", target: "b", relation: "east", via: [], sources: [] }]
    candidate.images = [{ page_id: "private-page-id", role: "illustration", anchors: [] }]
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [{ ...record(candidate, nextId), status: "candidate", base_revision_id: revisionId }] })
    const wrapper = render(); await flushPromises()
    await button(wrapper, "查看").trigger("click")
    expect(wrapper.get('[aria-label="候选地图差异"]').text()).toContain("临江新城 · 在东侧 · 黑石关")
    expect(wrapper.get('[aria-label="候选地图差异"]').text()).toContain("地点配图")
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
    expect(wrapper.find('.map-reader').exists()).toBe(false)
    expect(wrapper.find('.map-save-status').exists()).toBe(false)
    expect(button(wrapper, '撤销')).toBeUndefined()
    expect(wrapper.emitted('state').at(-1)[0]).toMatchObject({ focused: true })
    await wrapper.get('.map-locator input').setValue("黑石")
    await button(wrapper, "黑石关").trigger("click"); await flushPromises()
    expect(wrapper.get('[aria-label="地图地点详情"]').text()).toContain("黑石关")
    const target = wrapper.get('[data-feature-id="b"]')
    await target.trigger("keydown", { key: "ArrowRight" })
    await target.get("circle").trigger("pointerdown", { button: 0 })
    expect(wrapper.vm.dirty).toBe(false)
    await button(wrapper, "展开编辑工具").trigger("click")
    expect(wrapper.find(".map-edit-grid").exists()).toBe(true)
    expect(wrapper.emitted('state').at(-1)[0]).toMatchObject({ focused: false })
  })

  it("专注浏览保留未保存提示和保存操作，来源能打开同项目对应章节", async () => {
    const data = document()
    data.features[0].sources = [{ kind: 'source_range', quote: '前往临江城', source_ref: { chapter_index: 12 } }]
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = render(); await flushPromises()
    await wrapper.get('button[aria-label="向右移动"]').trigger('click')
    await button(wrapper, '专注看图').trigger('click')
    expect(wrapper.get('.map-save-status').text()).toContain('未保存')
    expect(button(wrapper, '保存地图').attributes('disabled')).toBeUndefined()
    await button(wrapper, '打开第 12 章').trigger('click')
    const args = router.navigate.mock.calls[0]
    expect(args.slice(0, 3)).toEqual(['writing', null, true])
    expect(Object.fromEntries(args[3])).toEqual({ novel_id: projectId, chapter_index: '12' })
    api.world.previewReaderMap.mockResolvedValue({ features: [{ id: 'a', kind: 'location', label: '临江城', points: [{ x: 100, y: 100 }] }], images: [], chapter: 1 })
    await button(wrapper, '保存地图').trigger('click'); await flushPromises()
    await button(wrapper, '展开编辑工具').trigger('click')
    await button(wrapper, '预览读者所见').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('前往临江城')
    expect(button(wrapper, '打开第 12 章')).toBeUndefined()
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
