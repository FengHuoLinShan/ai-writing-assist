import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import MapStructureEditor from "../../../vue/views/map/MapStructureEditor.vue"
import { copyMap, emptyMap, geometrySignature, mapChanges, removeMapFeature } from "../../../vue/views/map/mapStructureEditor.js"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))
enableAutoUnmount(afterEach)

const nodeId = "20000000-0000-0000-0000-000000000001"
const confirmDecision = vi.hoisted(() => ({ current: () => true }))
vi.mock('../../../shared/confirmAsync.js', () => ({ confirmAsync: message => Promise.resolve(confirmDecision.current(message)) }))
const projectId = "10000000-0000-0000-0000-000000000001"
const revisionId = "30000000-0000-0000-0000-000000000001"
const nextId = "30000000-0000-0000-0000-000000000002"
const feature = (id, label, x, y) => ({ id, kind: "location", label, points: [{ x, y }], locked: false, entity_id: null, target_node_id: null, depends_on: [], sources: [], note: "", reader_from_chapter: null })
const document = () => ({ ...emptyMap(), features: [feature("a", "临江城", 100, 100), feature("b", "黑石关", 300, 100), feature("c", "北堡", 100, 300)] })
const record = (data = document(), id = revisionId) => ({ id, node_id: nodeId, base_revision_id: null, status: "saved", document: data, problems: [], geometry_hash: "a".repeat(64), created_at: "2026-09-08T00:00:00Z" })
const state = revision => ({ node_id: nodeId, revision, candidates: [], image_layers: [], task_id: null, task_status: null })
const generationSummary = changes => ({ outcome: 'partial', message: '部分资料尚未完成核对，原地图仍保留。', targets: 3, sources: 4, input_characters: 800, batches: 2, failed_batches: 1, truncated_batches: 0, received_relations: 3, accepted_relations: 1, discarded_relations: 2, discard_reasons: { quote_mismatch: 2 }, structured_attempts: null, format_retries: null, ...changes })
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
    api.tasks = { cancel: vi.fn(async id => ({ task_id: id, status: 'cancelled', cancelled: true })), retry: vi.fn() }
    confirm = vi.fn(() => true)
    confirmDecision.current = confirm
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
  const render = async ({ browseOnly = false, ...props } = {}) => {
    const wrapper = mount(MapStructureEditor, { global: { stubs: { teleport: true } }, props: { projectId, node: { id: nodeId, title: "区域", level: "region" }, ...props } })
    await flushPromises()
    if (!browseOnly) {
      const edit = wrapper.findAll('button').find(item => item.text() === '编辑所选内容')
      if (edit) await edit.trigger('click')
    }
    return wrapper
  }

  it('默认先展示画布，详情按需打开，阅读预览只有一份', async () => {
    const wrapper = await render({ browseOnly: true })
    expect(wrapper.findAll('.map-reader')).toHaveLength(1)
    expect(wrapper.find('.map-inspector input').exists()).toBe(false)
    await button(wrapper, '编辑所选内容').trigger('click')
    expect(wrapper.findAll('.map-inspector')).toHaveLength(1)
    expect(wrapper.get('.map-inspector input').element.value).toBe('临江城')
  })

  it('锁定地点时四个微调按钮均禁用并解释解锁入口', async () => {
    const data = document(); data.features[0].locked = true
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = await render()
    for (const label of ['向左移动','向右移动','向上移动','向下移动']) expect(wrapper.get(`button[aria-label="${label}"]`).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('解锁后才能移动')
  })

  it('保存失败时离开决定仍待定，继续编辑保留当前输入', async () => {
    const proto = HTMLDialogElement.prototype
    const oldShow = proto.showModal, oldClose = proto.close
    proto.showModal = function () { this.open = true }
    proto.close = function () { this.open = false }
    const wrapper = await render(); await flushPromises()
    try {
      await wrapper.get('.map-inspector input[maxlength="200"]').setValue('尚未保存的地点名')
      const leaving = wrapper.vm.canLeave()
      let settled = false; void leaving.then(() => { settled = true })
      api.world.saveMapRevision.mockRejectedValueOnce(new Error('保存失败'))
      await button(wrapper, '保存并离开').trigger('click'); await flushPromises()
      expect(settled).toBe(false)
      expect(wrapper.get('dialog').text()).toContain('保存失败')
      expect(wrapper.get('.map-inspector input[maxlength="200"]').element.value).toBe('尚未保存的地点名')
      await button(wrapper, '继续编辑').trigger('click')
      expect(await leaving).toBe(false)
    } finally { wrapper.unmount(); proto.showModal = oldShow; proto.close = oldClose }
  })

  it("成果链接打开指定历史版进行比较而不替换当前编辑", async () => {
    api.world.previewMapRevision.mockResolvedValue({ document: { ...emptyMap(), features: [feature("old", "旧港口", 10, 10)] }, image_layers: [], problems: [] })
    const wrapper = await render({ initialRevisionId: nextId })
    await flushPromises()
    expect(api.world.previewMapRevision).toHaveBeenCalledWith(projectId, nodeId, nextId)
    expect(wrapper.text()).toContain("正在查看历史地图")
    expect(wrapper.text()).toContain("旧港口")
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
    expect(wrapper.vm.revision.id).toBe(revisionId)
  })

  it("无需图片连接即可编辑保存，文字使用安全的 SVG 文本", async () => {
    const wrapper = await render()
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
    const wrapper = await render()
    await flushPromises()
    await wrapper.get('button[aria-label="向右移动"]').trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("110")
    await button(wrapper, "撤销").trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("100")
    await button(wrapper, "重做").trigger("click")
    expect(wrapper.get(".map-feature circle").attributes("cx")).toBe("110")
  })

  it.each(['卸载', '立即刷新'])('编辑已备份后撤销回服务端版，%s再重开不会复活已撤销内容', async exit => {
    vi.useFakeTimers()
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const wrapper = await render(); await flushPromises()
    await wrapper.get('.map-inspector input').setValue('不再保留的编辑')
    await vi.advanceTimersByTimeAsync(250)
    expect(JSON.parse(localStorage.getItem(key)).document.features[0].label).toBe('不再保留的编辑')
    await button(wrapper, '撤销').trigger('click')
    expect(wrapper.vm.dirty).toBe(false)
    expect(button(wrapper, '保存地图').attributes('disabled')).toBeDefined()
    if (exit === '立即刷新') {
      const event = new Event('beforeunload', { cancelable: true })
      globalThis.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
      expect(localStorage.getItem(key)).toBeNull()
    }
    wrapper.unmount()
    expect(localStorage.getItem(key)).toBeNull()
    const reopened = await render(); await flushPromises()
    expect(reopened.text()).not.toContain('发现未保存的本机编辑')
    expect(reopened.get('.map-inspector input').element.value).toBe('临江城')
  })

  it('首次加载尚未读取、恢复提示待决定和无法解析的旧备份均不会因干净状态被清理', async () => {
    vi.useFakeTimers()
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '需要作者决定的备份'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: backup })
    localStorage.setItem(key, raw)
    let finish
    api.world.getNodeMap.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = await render()
    pending.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
    finish(state(record())); await flushPromises()
    const deciding = await render(); await flushPromises()
    expect(deciding.text()).toContain('发现未保存的本机编辑')
    await vi.advanceTimersByTimeAsync(250)
    deciding.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
    localStorage.setItem(key, '{unfinished')
    const unreadable = await render(); await flushPromises()
    unreadable.unmount()
    expect(localStorage.getItem(key)).toBe('{unfinished')
  })

  it('账户已经切换时，撤销清理不删除任何账户的备份', async () => {
    vi.useFakeTimers()
    const oldKey = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const otherKey = `novel_map_draft:other-account:${projectId}:${nodeId}`
    const wrapper = await render(); await flushPromises()
    await wrapper.get('.map-inspector input').setValue('旧账户的本机编辑')
    await vi.advanceTimersByTimeAsync(250)
    const oldBackup = localStorage.getItem(oldKey)
    localStorage.setItem(otherKey, 'other-account-backup')
    localStorage.setItem('novel_accountId', 'other-account')
    await button(wrapper, '撤销').trigger('click')
    await vi.advanceTimersByTimeAsync(250)
    wrapper.unmount()
    expect(localStorage.getItem(oldKey)).toBe(oldBackup)
    expect(localStorage.getItem(otherKey)).toBe('other-account-backup')
  })

  it.each([false, true])('干净标签页不删除同账户另一标签页后来写入的备份（本页曾编辑：%s）', async edited => {
    vi.useFakeTimers()
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const wrapper = await render(); await flushPromises()
    if (edited) {
      await wrapper.get('.map-inspector input').setValue('本标签页已备份的编辑')
      await vi.advanceTimersByTimeAsync(250)
    }
    const other = document(); other.features[0].label = '另一标签页的新编辑'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: other })
    localStorage.setItem(key, raw)
    if (edited) await button(wrapper, '撤销').trigger('click')
    await vi.advanceTimersByTimeAsync(250)
    globalThis.dispatchEvent(new Event('beforeunload', { cancelable: true }))
    wrapper.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
    const reopened = await render(); await flushPromises()
    expect(reopened.text()).toContain('发现未保存的本机编辑')
  })

  it('待恢复编辑尚未决定时仅能浏览，键盘、保存和版本采用不能覆盖备份', async () => {
    vi.useFakeTimers()
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '尚未决定的编辑'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: backup })
    localStorage.setItem(key, raw)
    const candidate = { ...record(backup, nextId), status: 'candidate', base_revision_id: revisionId }
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [candidate] })
    api.world.listMapRevisions.mockResolvedValue([record(backup, 'historical')])
    const wrapper = await render({ images: [{ id: 'image' }] }); await flushPromises()
    expect(wrapper.text()).toContain('可以继续浏览')
    expect(wrapper.find('.map-edit-grid').exists()).toBe(false)
    expect(wrapper.find('.map-image-controls').exists()).toBe(false)
    expect(wrapper.get('.map-inspector').text()).toContain('临江城')
    const point = wrapper.get('[data-feature-id="a"] circle').attributes('cx')
    await wrapper.get('[data-feature-id="a"]').trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.get('[data-feature-id="a"] circle').attributes('cx')).toBe(point)
    await wrapper.vm.save()
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
    await button(wrapper, '查看').trigger('click'); await flushPromises()
    expect(button(wrapper, '核对所选 1 项修改').attributes('disabled')).toBeDefined()
    await button(wrapper, '返回当前地图').trigger('click')
    await wrapper.findAll('summary').find(item => item.text() === '地图历史').trigger('click'); await flushPromises()
    expect(button(wrapper, '恢复为新版本').attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(250)
    wrapper.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(api.world.reviewMapRevision).not.toHaveBeenCalled()
    const reopened = await render(); await flushPromises()
    await button(reopened, '恢复到编辑区').trigger('click'); await flushPromises()
    expect(reopened.get('.map-inspector input').element.value).toBe('尚未决定的编辑')
    expect(reopened.vm.dirty).toBe(true)
  })

  it('放弃备份使用页内二次确认，取消保留备份，确认后恢复编辑和焦点', async () => {
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '可选择恢复的编辑'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: backup })
    localStorage.setItem(key, raw)
    const wrapper = mount(MapStructureEditor, { global: { stubs: { teleport: true } }, props: { projectId, node: { id: nodeId, title: '区域', level: 'region' } }, attachTo: globalThis.document.body })
    await flushPromises()
    await button(wrapper, '放弃本机编辑').trigger('click'); await flushPromises()
    expect(wrapper.find('[aria-label="确认放弃本机编辑"]').exists()).toBe(true)
    expect(localStorage.getItem(key)).toBe(raw)
    expect(globalThis.document.activeElement).toBe(button(wrapper, '确认放弃这份备份').element)
    await button(wrapper, '保留备份').trigger('click'); await flushPromises()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(globalThis.document.activeElement).toBe(button(wrapper, '放弃本机编辑').element)
    await button(wrapper, '放弃本机编辑').trigger('click')
    await button(wrapper, '确认放弃这份备份').trigger('click'); await flushPromises()
    expect(localStorage.getItem(key)).toBeNull()
    expect(wrapper.find('[aria-label="待处理的本机地图编辑"]').exists()).toBe(false)
    expect(wrapper.get('.map-inspector input').element.value).toBe('临江城')
    expect(globalThis.document.activeElement).toBe(wrapper.get('.map-scroll').element)
    expect(confirm).not.toHaveBeenCalled()
  })

  it.each(['恢复到编辑区', '确认放弃这份备份'])('另一处备份变化后%s只刷新提示，必须重新作出选择', async action => {
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '第一份备份'
    localStorage.setItem(key, JSON.stringify({ base_revision_id: revisionId, document: backup }))
    const wrapper = await render(); await flushPromises()
    if (action.startsWith('确认')) await button(wrapper, '放弃本机编辑').trigger('click')
    const changed = document(); changed.features[0].label = '另一处的新备份'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: changed })
    localStorage.setItem(key, raw)
    await button(wrapper, action).trigger('click'); await flushPromises()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(wrapper.text()).toContain('本机备份已在另一处变化')
    expect(wrapper.find('.map-edit-grid').exists()).toBe(false)
    expect(wrapper.find('[aria-label="确认放弃本机编辑"]').exists()).toBe(false)
    await button(wrapper, '恢复到编辑区').trigger('click'); await flushPromises()
    expect(wrapper.get('.map-inspector input').element.value).toBe('另一处的新备份')
  })

  it('保存请求等待时另一处写入的新备份不被完成清理删除', async () => {
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const wrapper = await render(); await flushPromises()
    await wrapper.get('.map-inspector input').setValue('本页保存内容')
    let finish
    api.world.saveMapRevision.mockReturnValue(new Promise(resolve => { finish = resolve }))
    await button(wrapper, '保存地图').trigger('click')
    const other = document(); other.features[0].label = '另一处仍未保存'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: other })
    localStorage.setItem(key, raw)
    const saved = record(api.world.saveMapRevision.mock.calls[0][2].document, nextId)
    api.world.getNodeMap.mockResolvedValue(state(saved))
    finish(saved); await flushPromises()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(wrapper.get('.map-save-status').text()).toBe('已保存到服务端')
    wrapper.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
  })

  it('另一处写入损坏备份后明确标记不可恢复，重新二次确认可仅放弃这份损坏内容', async () => {
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '原本待决定的编辑'
    localStorage.setItem(key, JSON.stringify({ base_revision_id: revisionId, document: backup }))
    const wrapper = await render(); await flushPromises()
    await button(wrapper, '放弃本机编辑').trigger('click')
    localStorage.setItem(key, '{damaged-in-another-tab')
    await button(wrapper, '确认放弃这份备份').trigger('click'); await flushPromises()
    expect(localStorage.getItem(key)).toBe('{damaged-in-another-tab')
    expect(wrapper.text()).toContain('本机备份内容已损坏')
    expect(button(wrapper, '恢复到编辑区').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[aria-label="确认放弃本机编辑"]').exists()).toBe(false)
    expect(wrapper.find('.map-edit-grid').exists()).toBe(false)
    await button(wrapper, '放弃本机编辑').trigger('click')
    await button(wrapper, '确认放弃这份备份').trigger('click'); await flushPromises()
    expect(localStorage.getItem(key)).toBeNull()
    expect(wrapper.find('.map-edit-grid').exists()).toBe(true)
  })

  it('核对备份时读取异常仍保留原内容，不解除待决定保护', async () => {
    const key = `novel_map_draft:test-account:${projectId}:${nodeId}`
    const backup = document(); backup.features[0].label = '不能丢的原备份'
    const raw = JSON.stringify({ base_revision_id: revisionId, document: backup })
    localStorage.setItem(key, raw)
    const wrapper = await render(); await flushPromises()
    const original = localStorage.getItem.bind(localStorage)
    const storage = vi.spyOn(localStorage, 'getItem').mockImplementation(value => { if (value === key) throw new Error('storage unavailable'); return original(value) })
    await button(wrapper, '恢复到编辑区').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('本机备份暂时无法核对')
    expect(wrapper.find('.map-edit-grid').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('本机备份内容已损坏')
    storage.mockRestore()
    wrapper.unmount()
    expect(localStorage.getItem(key)).toBe(raw)
  })

  it("服务端与本地备份同时失败时不放行导航，也不声称已备份", async () => {
    const wrapper = await render()
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
    const wrapper = await render()
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
    const wrapper = await render()
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
    const wrapper = await render()
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
    const wrapper = await render({ images: [{ id: pageId, title: "区域底图", image_hash: "b".repeat(64) }] })
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
    const wrapper = await render({ images: [{ id: 'image-a', title: '城市示意' }, { id: 'image-b', title: '城市示意' }] })
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
    const wrapper = await render()
    await flushPromises()
    await button(wrapper, "查找").trigger("submit")
    await wrapper.get(".map-location-search").trigger("submit")
    await flushPromises()
    expect(wrapper.findAll(".map-world-locations input")).toHaveLength(1)
    await wrapper.get(".map-world-locations input").setValue(true)
    await button(wrapper, "用这些地点生成空间关系").trigger("click")
    await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ action: "world.map_atlas.structure", entity_ids: ["location-1"] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ base_revision_id: revisionId, context_confirmation_id: "confirmation", location_ids: ["location-1"] }))
  })

  it.each([null, 0, 2])('整理结果显示安全摘要，尝试计数%s如实展示且不进入读者预览', async attempts => {
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), task_status: 'done', generation_summary: generationSummary({ message: '<img src=x>引文未通过来源检查，已排除。', structured_attempts: attempts }) })
    const wrapper = await render(); await flushPromises()
    const feedback = wrapper.get('[aria-label="空间整理结果"]')
    expect(feedback.get('p[role=status]').text()).toBe('<img src=x>引文未通过来源检查，已排除。')
    expect(feedback.find('img').exists()).toBe(false)
    expect(feedback.text()).toContain('引文与来源不符：2 条')
    expect(feedback.text()).not.toContain('quote_mismatch')
    const count = feedback.findAll('dt').find(item => item.text() === '生成尝试次数')
    expect(count.element.nextElementSibling.textContent).toBe(attempts == null ? '未记录' : String(attempts))
    api.world.previewReaderMap.mockResolvedValue({ features: [], images: [], chapter: 1 })
    await button(wrapper, '预览读者所见').trigger('click'); await flushPromises()
    expect(wrapper.find('[aria-label="空间整理结果"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('引文未通过来源检查')
  })

  it('停止整理复用当前项目任务接口，只有服务器成功后才说明已停止', async () => {
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), task_id: 'task-1', task_status: 'running' })
    const wrapper = await render({ hasReference: true }); await flushPromises()
    api.tasks.cancel.mockRejectedValueOnce(new Error('暂时无法停止'))
    await button(wrapper, '停止本次整理').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('本次整理已停止')
    expect(button(wrapper, '停止本次整理').attributes('disabled')).toBeUndefined()
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), task_id: 'task-1', task_status: 'cancelled' })
    await button(wrapper, '停止本次整理').trigger('click'); await flushPromises()
    expect(api.tasks.cancel).toHaveBeenLastCalledWith('task-1', projectId)
    expect(wrapper.text()).toContain('本次整理已停止')
    await button(wrapper, '专注看图').trigger('click')
    await button(wrapper, '查看图片参考').trigger('click')
    await button(wrapper, '选择内容重新整理').trigger('click'); await flushPromises()
    expect(wrapper.find('.map-edit-grid').exists()).toBe(true)
    expect(wrapper.emitted('reference-visible').at(-1)).toEqual([false])
    expect(api.tasks.retry).not.toHaveBeenCalled()
    expect(api.world.generateMapStructure).not.toHaveBeenCalled()
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it('新任务不沿用旧整理计数，首次读取失败后继续轮询并恢复反馈', async () => {
    vi.useFakeTimers()
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), task_id: 'old-task', task_status: 'done', generation_summary: generationSummary({ message: '旧任务摘要' }) })
    api.world.listEntities.mockResolvedValue({ items: [{ id: 'world-location', name: '临江城', status: 'canonical' }] })
    const wrapper = await render(); await flushPromises()
    await wrapper.get('.map-location-search').trigger('submit'); await flushPromises()
    await wrapper.get('.map-world-locations input').setValue(true)
    api.world.getNodeMap.mockRejectedValueOnce(new Error('本次地图读取失败'))
    await button(wrapper, '用这些地点生成空间关系').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('旧任务摘要')
    expect(wrapper.get('[aria-label="空间整理结果"] p').text()).toContain('正在核对空间资料')
    expect(wrapper.find('[aria-label="空间整理结果"] details').exists()).toBe(false)
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), task_id: 'task-1', task_status: 'done', generation_summary: generationSummary({ message: '新任务已核对完成', structured_attempts: 1 }) })
    await vi.advanceTimersByTimeAsync(2500); await flushPromises()
    expect(wrapper.text()).toContain('新任务已核对完成')
    expect(wrapper.text()).not.toContain('本次地图读取失败')
    expect(wrapper.find('[aria-label="空间整理结果"] details').exists()).toBe(true)
  })

  it('已有手工图元带精确原文选择进入生成，无需先创建世界对象', async () => {
    const sourceRef = { draft_id: nextId, chapter_index: 30, version_number: 1, content_mode: 'canonical', start_offset: 0, end_offset: 45, source_hash: 'a'.repeat(64), range_hash: 'b'.repeat(64) }
    const data = document(); data.features[0].sources = [{ kind: 'source_range', id: nextId, source_hash: sourceRef.source_hash, source_ref: sourceRef, quote: '临江城位于河岸' }]
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = await render(); await flushPromises()
    const choices = wrapper.findAll('details').find(item => item.find('summary').text() === '整理地图中已有内容')
    await choices.get('input[type=checkbox]').setValue(true)
    await button(wrapper, '整理所选内容的空间关系').trigger('click'); await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ pinned_refs: [{ kind: 'source_range', source_ref: sourceRef }] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ location_ids: [], feature_ids: ['a'] }))
  })

  it('普通作者可手工加标记、查找正文、关联保存，再确认资料生成空间关系', async () => {
    const sourceRef = { draft_id: nextId, chapter_index: 30, version_number: 1, content_mode: 'canonical', start_offset: 0, end_offset: 45, source_hash: 'a'.repeat(64), range_hash: 'b'.repeat(64) }
    api.context = {
      searchEvidence: vi.fn(async () => ({ hits: [{ kind: 'manuscript', title: '城中', snippet: '旅馆……桥旁', source_ref: sourceRef }], total: 1 })),
      readEvidence: vi.fn(async () => ({ source_ref: sourceRef, text: '旅馆在桥旁，入口面向广场。', title: '城中', highlight_start: 0, highlight_end: '旅馆在桥旁，入口面向广场。'.length })),
    }
    api.world.saveMapRevision.mockImplementation(async (_project, _node, payload) => {
      const saved = record(copyMap(payload.document), nextId)
      api.world.getNodeMap.mockResolvedValue(state(saved))
      return saved
    })
    setBridgeOverrides({ state: { currentProjectId: projectId } })
    const wrapper = await render(); await flushPromises()
    const form = wrapper.findAll('form').find(item => item.text().includes('标记名称'))
    await form.get('input').setValue('旅馆')
    await form.trigger('submit')
    await button(wrapper, '结束绘制').trigger('click')
    expect(wrapper.get('.map-feature-sources').text()).toContain('尚未关联依据')
    await button(wrapper, '添加正文依据').trigger('click')
    await wrapper.get('.map-source-search').trigger('submit'); await flushPromises()
    await button(wrapper, '查看原文').trigger('click'); await flushPromises()
    await button(wrapper, '关联到“旅馆”').trigger('click')
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
    await button(wrapper, '返回地图').trigger('click')
    expect(wrapper.get('.map-feature-sources').text()).toContain('旅馆在桥旁，入口面向广场。')
    await button(wrapper, '撤销').trigger('click')
    expect(wrapper.get('.map-feature-sources').text()).toContain('尚未关联依据')
    await button(wrapper, '重做').trigger('click')
    await button(wrapper, '保存地图').trigger('click'); await flushPromises()
    const saved = api.world.saveMapRevision.mock.calls[0][2].document.features.find(item => item.label === '旅馆')
    expect(saved.entity_id).toBeNull()
    expect(saved.sources).toEqual([{ kind: 'source_range', id: nextId, source_hash: sourceRef.source_hash, source_ref: sourceRef, quote: '旅馆在桥旁，入口面向广场。' }])
    const choices = wrapper.findAll('details').find(item => item.find('summary').text() === '整理地图中已有内容')
    await choices.get(`input[value="${saved.id}"]`).setValue(true)
    await button(wrapper, '整理所选内容的空间关系').trigger('click'); await flushPromises()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ entity_ids: [], pinned_refs: [{ kind: 'source_range', source_ref: sourceRef }] }))
    expect(api.world.generateMapStructure).toHaveBeenCalledWith(projectId, nodeId, expect.objectContaining({ base_revision_id: nextId, feature_ids: [saved.id] }))
  })

  it('逐项采用只发送选择键，成功后保留剩余候选和明确反馈', async () => {
    const candidate = document(); candidate.features[0].note = '第一项'; candidate.features[1].note = '第二项'
    const proposed = { ...record(candidate, nextId), status: 'candidate', base_revision_id: revisionId }
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [proposed] })
    const wrapper = await render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
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
    const wrapper = await render({ initialFeatureId: 'b' }); await flushPromises()
    expect(wrapper.get('.map-feature.selected').attributes('data-feature-id')).toBe('b')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(150)
    wrapper.get('.map-scroll').element.scrollLeft = 120
    wrapper.get('.map-scroll').element.scrollTop = 80
    await wrapper.get('.map-scroll').trigger('scroll')
    wrapper.unmount()
    const restored = await render(); await flushPromises()
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
    const wrapper = await render(); await flushPromises()
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
    const wrapper = await render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
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
    const wrapper = await render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
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
    const wrapper = await render(); await flushPromises(); await button(wrapper, '查看').trigger('click'); await flushPromises()
    await button(wrapper, '核对所选 1 项修改').trigger('click'); await flushPromises()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(true)
    api.world.getNodeMap.mockResolvedValue({ ...state(record(document(), 'server-new')), candidates: [proposed] })
    await vi.advanceTimersByTimeAsync(2500); await flushPromises()
    expect(wrapper.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
    wrapper.unmount(); vi.useRealTimers()
    const refreshed = await render(); await flushPromises(); await button(refreshed, '查看').trigger('click'); await flushPromises()
    expect(refreshed.find('[aria-label="即将采用的修改"]').exists()).toBe(false)
    expect(button(refreshed, '核对所选 1 项修改').attributes('disabled')).toBeDefined()
  })

  it('历史预览接收实时来源问题，并恢复当前版新鲜问题', async () => {
    const current = record(); current.problems = [{ code: 'current', message: '当前版来源变化', feature_ids: [] }]
    api.world.getNodeMap.mockResolvedValue(state(current))
    api.world.listMapRevisions.mockResolvedValue([record(document(), 'historical')])
    api.world.previewMapRevision.mockResolvedValue({ image_layers: [{ page_id: 'old-illustration', role: 'illustration', state: 'ready', feature_id: 'a' }], problems: [{ code: 'stale', message: '历史版正文来源已失效', feature_ids: ['a'] }] })
    const wrapper = await render(); await flushPromises()
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
    let wrapper = await render(props); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('picture'); await flushPromises()
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    await wrapper.get('button[aria-label="向右移动"]').trigger('click')
    await button(wrapper, '保存地图').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    wrapper.unmount(); wrapper = await render(props); await flushPromises()
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
    const wrapper = await render({ images: [{ id: 'generated', title: '生成图片', source_map_revision_id: 'old-source' }, { id: 'uploaded', title: '上传图片' }] }); await flushPromises()
    const select = wrapper.get('.map-image-controls select')
    await select.setValue('generated'); await select.setValue('uploaded')
    finish({ document: document(), image_layers: [], problems: [] }); await flushPromises()
    expect(wrapper.text()).toContain('无法自动判断空间变化')
    expect(button(wrapper, '对照图片生成时的地图')).toBeUndefined()
    expect(wrapper.vm.dirty).toBe(false)
  })

  it('上传底图用服务端证明的校准版本对照，并明确区别图片生成来源', async () => {
    const original = document(), current = document()
    current.features[0].points[0].x = 140
    current.images = [{ page_id: 'uploaded', role: 'background', anchors: [{ feature_id: 'a' }] }]
    const layer = { page_id: 'uploaded', role: 'background', state: 'stale', calibration_revision_id: 'calibrated-old', calibration_lookup_status: 'found' }
    api.world.getNodeMap.mockResolvedValue({ ...state(record(current)), image_layers: [layer] })
    api.world.previewMapRevision.mockResolvedValue({ document: original, image_layers: [], problems: [] })
    const wrapper = await render({ images: [{ id: 'uploaded', title: '上传底图', source_map_revision_id: null }] }); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('uploaded'); await flushPromises()
    expect(api.world.previewMapRevision).toHaveBeenCalledWith(projectId, nodeId, 'calibrated-old')
    expect(wrapper.text()).toContain('校准点发生变化：临江城')
    expect(wrapper.get('.map-image-baseline-status').text()).toContain('不表示图片由该版本生成')
    expect(button(wrapper, '对照图片生成时的地图')).toBeUndefined()
    await button(wrapper, '对照上次校准时的地图').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('正在查看历史地图')
    expect(api.world.listMapRevisions).not.toHaveBeenCalled()
    expect(api.world.saveMapRevision).not.toHaveBeenCalled()
  })

  it.each(['not_found', 'truncated', null])('没有可信校准版本时(%s)不使用臆测的历史基准', async lookup => {
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), image_layers: [{ page_id: 'uploaded', role: lookup ? 'background' : 'illustration', state: 'unavailable', calibration_revision_id: null, calibration_lookup_status: lookup }] })
    const wrapper = await render({ images: [{ id: 'uploaded', title: '上传图片' }] }); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('uploaded'); await flushPromises()
    expect(wrapper.get('.map-image-baseline-status').text()).toContain(lookup === 'truncated' ? '校准历史较多' : lookup === 'not_found' ? '未找到与此底图校准配置匹配' : '没有绑定生成时的地图版本')
    expect(wrapper.get('.map-image-baseline-status').text()).toContain('无法自动判断空间变化')
    expect(button(wrapper, '对照上次校准时的地图')).toBeUndefined()
    expect(api.world.previewMapRevision).not.toHaveBeenCalled()
  })

  it('同一图片同时保留生成与校准来源，分别打开对应的冻结地图', async () => {
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), image_layers: [{ page_id: 'picture', role: 'background', state: 'stale', calibration_revision_id: 'calibration', calibration_lookup_status: 'found' }] })
    api.world.previewMapRevision.mockResolvedValue({ document: document(), image_layers: [], problems: [] })
    const wrapper = await render({ images: [{ id: 'picture', title: '地图图片', source_map_revision_id: 'generated' }] }); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('picture'); await flushPromises()
    expect(wrapper.get('.map-image-baseline-status').text()).toContain('图片生成时绑定的地图版本')
    expect(button(wrapper, '对照图片生成时的地图')).toBeDefined()
    expect(button(wrapper, '对照上次校准时的地图')).toBeDefined()
    await button(wrapper, '对照上次校准时的地图').trigger('click'); await flushPromises()
    expect(api.world.previewMapRevision).toHaveBeenLastCalledWith(projectId, nodeId, 'calibration')
  })

  it('两类来源对照只接受最后一次点击，晚到的生成版不能覆盖校准版', async () => {
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), image_layers: [{ page_id: 'picture', role: 'background', state: 'stale', calibration_revision_id: 'calibration', calibration_lookup_status: 'found' }] })
    api.world.previewMapRevision.mockResolvedValue({ document: document(), image_layers: [], problems: [] })
    const wrapper = await render({ images: [{ id: 'picture', title: '地图图片', source_map_revision_id: 'generated' }] }); await flushPromises()
    await wrapper.get('.map-image-controls select').setValue('picture'); await flushPromises()
    let finish
    const calibrated = document(); calibrated.features[0].label = '校准版地点'
    api.world.previewMapRevision.mockImplementation(async (_project, _node, id) => id === 'generated' ? new Promise(resolve => { finish = resolve }) : { document: calibrated, image_layers: [], problems: [] })
    await button(wrapper, '对照图片生成时的地图').trigger('click')
    await button(wrapper, '对照上次校准时的地图').trigger('click'); await flushPromises()
    expect(wrapper.get('.map-feature text').text()).toBe('校准版地点')
    const generated = document(); generated.features[0].label = '生成版地点'
    finish({ document: generated, image_layers: [], problems: [] }); await flushPromises()
    expect(wrapper.get('.map-feature text').text()).toBe('校准版地点')
  })

  it('空白画布拖动和视口方向键只平移，触摸由原生滚动与缩放处理', async () => {
    const data = document(); data.features.push({ ...feature('area', '区域', 0, 0), kind: 'area', points: [{ x: 0, y: 0 }, { x: 400, y: 0 }, { x: 400, y: 400 }] })
    api.world.getNodeMap.mockResolvedValue(state(record(data)))
    const wrapper = await render(); await flushPromises()
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
    const wrapper = await render(); await flushPromises(); await wrapper.get('[data-feature-id="road"]').trigger('click')
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
    const wrapper = await render(); await flushPromises(); await wrapper.get('[data-feature-id="e"]').trigger('click')
    expect(wrapper.get('[data-feature-id="e"] text').text()).toBe('地点e')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(180)
    localStorage.setItem('novel_accountId', 'another-account')
    await wrapper.get('[aria-label="空间地图缩放"]').setValue(190)
    wrapper.unmount()
    const next = await render(); await flushPromises()
    expect(next.get('[aria-label="空间地图缩放"]').element.value).toBe('100')
    expect(next.get('.map-feature.selected').attributes('data-feature-id')).toBe('a')
  })

  it("候选可查看关系和图片变化，并与保存版对照而不改写当前编辑", async () => {
    const candidate = document()
    candidate.features[0].label = "临江新城"
    candidate.constraints = [{ id: "c1", subject: "a", target: "b", relation: "east", via: [], sources: [] }]
    candidate.images = [{ page_id: "private-page-id", role: "illustration", anchors: [] }]
    api.world.getNodeMap.mockResolvedValue({ ...state(record()), candidates: [{ ...record(candidate, nextId), status: "candidate", base_revision_id: revisionId }] })
    const wrapper = await render(); await flushPromises()
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

  it("查证输入与完成结果在专注切换后保留，不重复查询", async () => {
    api.context = {
      startFocusedSearch: vi.fn(async () => ({ task_id: "lookup-1", status: "pending" })),
      getFocusedSearch: vi.fn(async () => ({ status: "completed", result: {
        targets: [{ key: "root", name: "查证结果地点", depth: 0 }], evidence: [],
        coverage: { complete: true, total_chapters: 1, scanned_chapters: 1 }, warnings: [],
      } })),
    }
    const wrapper = await render(); await flushPromises()
    const panel = wrapper.get(".focused-evidence")
    panel.element.open = true; await panel.trigger("toggle")
    await panel.get("input").setValue("待核对地点")
    await panel.get("textarea").setValue("保留这个查证问题")
    await panel.get("form").trigger("submit"); await flushPromises()
    expect(panel.text()).toContain("查证结果地点")
    await button(wrapper, "专注看图").trigger("click")
    await button(wrapper, "展开编辑工具").trigger("click")
    const restored = wrapper.get(".focused-evidence")
    expect(restored.get("input").element.value).toBe("待核对地点")
    expect(restored.get("textarea").element.value).toBe("保留这个查证问题")
    expect(restored.text()).toContain("查证结果地点")
    expect(api.context.startFocusedSearch).toHaveBeenCalledOnce()
  })

  it("专注浏览能查找选择地点，方向键和拖动不会改图", async () => {
    const wrapper = await render(); await flushPromises()
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
    const wrapper = await render(); await flushPromises()
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
