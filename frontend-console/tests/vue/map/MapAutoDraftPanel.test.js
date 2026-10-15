import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapAutoDraftPanel from '../../../vue/views/map/MapAutoDraftPanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
const draft = () => ({ batch_id: 'batch', node_id: 'node', node_title: '港口', node: { id: 'node', level: 'city', current_revision_id: null }, revision_id: 'candidate', base_revision_id: 'previous-candidate', status: 'candidate', document: { schema_version: 2, spaces: [{ id: 'main', label: '主空间' }, { id: 'dream', label: '梦境' }], features: [], constraints: [], journeys: [] }, pending_tray: [{ item_id: 'tray', fingerprint: 'tray-fp', endpoint: { surface: '码头' }, reason: 'placement_failed', quote: '码头在港口以东。', source_mode: 'canonical' }], conflicts: [], warnings: [] })
const listing = () => ({ items: [draft()], total_count: 1, batches: [{ batch_id: 'batch', fingerprint: 'batch-fp', status: 'completed', completed_chunks: 1, total_chunks: 1 }], truncated: false, batches_truncated: false })
let api, confirmAction
beforeEach(() => {
  api = { world: {
    listMapAutoDrafts: vi.fn().mockResolvedValue(listing()),
    resumeMapAutoDrafts: vi.fn().mockResolvedValue({ status: 'running' }),
    redoMapAutoDrafts: vi.fn().mockResolvedValue({ status: 'running' }),
    previewAutoDraftTrayPlacement: vi.fn().mockResolvedValue({ preview_fingerprint: 'preview-fp', old_feature_count: 0, new_feature_count: 1, remaining_tray_count: 0, impacts: ['新增锁定点位'], warnings: [] }),
    placeAutoDraftTrayItem: vi.fn().mockResolvedValue({ status: 'candidate' }),
  } }
  confirmAction = vi.fn((_message, confirm) => confirm())
  setBridgeOverrides({ api, confirmAction })
})
afterEach(resetBridgeOverrides)
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text().includes(text))
async function open() {
  const wrapper = mount(MapAutoDraftPanel, { props: { projectId: 'novel' } })
  wrapper.get('details').element.open = true
  await wrapper.get('details').trigger('toggle'); await flushPromises()
  return wrapper
}
async function select(wrapper) { await button(wrapper, '在草图上选择位置').trigger('click'); await flushPromises() }

describe('阅读自动草图与待放置托盘', () => {
  it('折叠不读取，真实分片进度与分页独立显示', async () => {
    const value = listing(); value.total_count = 21; value.truncated = true; value.batches[0] = { ...value.batches[0], status: 'running', completed_chunks: 20, total_chunks: 25 }
    api.world.listMapAutoDrafts.mockResolvedValue(value)
    const wrapper = await open()
    expect(api.world.listMapAutoDrafts).toHaveBeenCalledWith('novel', { limit: 20, offset: 0 })
    expect(wrapper.text()).toContain('20 / 25 片')
    expect(wrapper.text()).not.toContain('本次批次摘要未全部')
    expect(button(wrapper, '在草图上选择位置').attributes('disabled')).toBeDefined()
    await button(wrapper, '下一页草图').trigger('click'); await flushPromises()
    expect(api.world.listMapAutoDrafts.mock.lastCall[1].offset).toBe(20)
    await button(wrapper, '继续整理分片').trigger('click'); await flushPromises()
    expect(api.world.resumeMapAutoDrafts).toHaveBeenCalledWith('novel', 'batch', { expected_fingerprint: 'batch-fp', confirmed: true })
    expect(wrapper.text()).toContain('20 / 25 片')
  })
  it('作者选点前不能预览，放置绑定正式head和预览指纹', async () => {
    const wrapper = await open(); await select(wrapper)
    expect(button(wrapper, '预览放置影响').attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('state').at(-1)[0].dirty).toBe(true)
    expect(button(wrapper, '打开地图逐项审核').attributes('disabled')).toBeDefined()
    await wrapper.get('svg').trigger('keydown', { key: 'Enter' })
    await button(wrapper, '预览放置影响').trigger('click'); await flushPromises()
    const payload = api.world.previewAutoDraftTrayPlacement.mock.lastCall.at(-1)
    expect(payload).toEqual({ expected_fingerprint: 'tray-fp', base_revision_id: null, space_id: 'main', point: { x: expect.any(Number), y: expect.any(Number) } })
    expect(api.world.placeAutoDraftTrayItem).not.toHaveBeenCalled()
    await button(wrapper, '确认放入草图候选').trigger('click'); await flushPromises()
    expect(confirmAction).toHaveBeenCalledTimes(1)
    expect(api.world.placeAutoDraftTrayItem).toHaveBeenCalledWith('novel', 'batch', 'node', 'candidate', 'tray', { ...payload, preview_fingerprint: 'preview-fp', confirmed: true })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })
  it('移动选点或切换空间会使旧预览失效，重新定位前不能确认', async () => {
    const wrapper = await open(); await select(wrapper)
    await wrapper.get('svg').trigger('keydown', { key: 'Enter' }); await button(wrapper, '预览放置影响').trigger('click'); await flushPromises()
    await wrapper.get('svg').trigger('keydown', { key: 'ArrowRight' })
    expect(button(wrapper, '确认放入草图候选')).toBeUndefined()
    await button(wrapper, '预览放置影响').trigger('click'); await flushPromises()
    await wrapper.get('select').setValue('dream')
    expect(button(wrapper, '确认放入草图候选')).toBeUndefined()
    expect(button(wrapper, '预览放置影响').attributes('disabled')).toBeDefined()
    expect(api.world.placeAutoDraftTrayItem).not.toHaveBeenCalled()
  })
  it('定位不会因重新读取被覆盖，取消后允许读取并解除离开保护', async () => {
    const wrapper = await open(); await select(wrapper)
    await button(wrapper, '重新读取草图').trigger('click'); await flushPromises()
    expect(api.world.listMapAutoDrafts).toHaveBeenCalledTimes(1)
    await button(wrapper, '取消定位').trigger('click')
    expect(wrapper.emitted('state').at(-1)[0].dirty).toBe(false)
    await button(wrapper, '重新读取草图').trigger('click'); await flushPromises()
    expect(api.world.listMapAutoDrafts).toHaveBeenCalledTimes(2)
  })
  it('确认期间锁住所有定位控件，切换作品不提交旧地点', async () => {
    let approve
    confirmAction.mockImplementation((_message, confirm) => { approve = confirm })
    const wrapper = await open(); await select(wrapper)
    await wrapper.get('svg').trigger('keydown', { key: 'Enter' }); await button(wrapper, '预览放置影响').trigger('click'); await flushPromises()
    await button(wrapper, '确认放入草图候选').trigger('click'); await flushPromises()
    expect(button(wrapper, '取消定位').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ projectId: 'other' }); approve(); await flushPromises()
    expect(api.world.placeAutoDraftTrayItem).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('码头')
  })
  it('过期来源阻止放置，409保留当前定位且要求重新核对', async () => {
    const wrapper = await open(); await select(wrapper)
    api.world.placeAutoDraftTrayItem.mockRejectedValue({ status: 409 })
    await wrapper.get('svg').trigger('keydown', { key: 'Enter' }); await button(wrapper, '预览放置影响').trigger('click'); await flushPromises()
    await button(wrapper, '确认放入草图候选').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('地图、来源或托盘已变化')
    expect(wrapper.get('[aria-label="待放置地点定位"]').exists()).toBe(true)
    expect(button(wrapper, '确认放入草图候选')).toBeUndefined()
    expect(wrapper.emitted('changed')).toBeUndefined()
  })
  it('来源已失效和被取代候选只能查看，展开不会虚构地图节点', async () => {
    const value = listing(); value.items[0].stale = true
    api.world.listMapAutoDrafts.mockResolvedValue(value)
    const wrapper = await open()
    expect(button(wrapper, '在草图上选择位置').attributes('disabled')).toBeDefined()
    await button(wrapper, '打开地图逐项审核').trigger('click')
    expect(wrapper.emitted('review')[0][0].node).toEqual(value.items[0].node)
    expect(api.world.placeAutoDraftTrayItem).not.toHaveBeenCalled()
  })
})
