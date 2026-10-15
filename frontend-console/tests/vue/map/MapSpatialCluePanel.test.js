import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapSpatialCluePanel from '../../../vue/views/map/MapSpatialCluePanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
const clue = (overrides = {}) => ({ id: 'clue-1', scene_id: 'scene-1', scene_index: 0, status: 'pending_review', fingerprint: 'fp-1', kind: 'bearing', modality: 'event_observed', quote: '旧桥位于南门以东。', subject: { surface: '旧桥' }, target: { surface: '南门' }, attributes: {}, ...overrides })
let api, confirmAction
beforeEach(() => {
  api = { world: { listSpatialClues: vi.fn().mockResolvedValue({ items: [clue()], total_count: 1 }), reviewSpatialClue: vi.fn().mockResolvedValue(clue({ status: 'adopted' })) } }
  confirmAction = vi.fn((message, confirm) => confirm())
  setBridgeOverrides({ api, confirmAction })
})
afterEach(resetBridgeOverrides)
async function open(props = {}) {
  const wrapper = mount(MapSpatialCluePanel, { props: { projectId: 'novel-1', ...props } })
  wrapper.get('details').element.open = true
  await wrapper.get('details').trigger('toggle'); await flushPromises()
  return wrapper
}
function button(wrapper, text) { return wrapper.findAll('button').find(item => item.text().includes(text)) }
async function selectFirst(wrapper) { await wrapper.get('.clue-choice').trigger('click'); await flushPromises() }

describe('空间线索复核', () => {
  it('折叠时不读取，展开查询有限分页及两个待处理状态', async () => {
    const wrapper = mount(MapSpatialCluePanel, { props: { projectId: 'novel-1' } })
    expect(api.world.listSpatialClues).not.toHaveBeenCalled()
    wrapper.get('details').element.open = true
    await wrapper.get('details').trigger('toggle'); await flushPromises()
    expect(api.world.listSpatialClues).toHaveBeenCalledWith('novel-1', { status: ['pending_review', 'pending_verification'], limit: 20, offset: 0 })
    expect(wrapper.text()).toContain('旧桥位于南门以东。')
  })
  it('作者确认后提交当前指纹，回执返回前不显示成功', async () => {
    const wrapper = await open(); await selectFirst(wrapper)
    let finish
    api.world.reviewSpatialClue.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    await wrapper.get('textarea').setValue('核对过原文')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(confirmAction).toHaveBeenCalledTimes(1)
    expect(api.world.reviewSpatialClue).toHaveBeenCalledWith('novel-1', 'clue-1', { action: 'adopt', expected_fingerprint: 'fp-1', confirmed: true, reason: '核对过原文' })
    expect(wrapper.text()).not.toContain('线索已确认。')
    finish(clue({ status: 'adopted' })); await flushPromises()
    expect(wrapper.text()).toContain('线索已确认。请继续核对地图草图。')
  })
  it('待核对不能确认，人物陈述明确说明不参加客观计算', async () => {
    api.world.listSpatialClues.mockResolvedValue({ items: [clue({ status: 'pending_verification', modality: 'character_statement' })], total_count: 1 })
    const wrapper = await open(); await selectFirst(wrapper)
    expect(button(wrapper, '确认这条线索').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.world.reviewSpatialClue).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('不作为客观空间事实参与计算')
  })
  it('合并携带两侧指纹，拒绝不会夹带选中的合并目标', async () => {
    api.world.listSpatialClues.mockResolvedValue({ items: [clue(), clue({ id: 'clue-2', fingerprint: 'fp-2', quote: '南门西侧是旧桥。' })], total_count: 2 })
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.get('.clue-review select').setValue('clue-2')
    await button(wrapper, '确认合并').trigger('click'); await flushPromises()
    expect(api.world.reviewSpatialClue).toHaveBeenCalledWith('novel-1', 'clue-1', expect.objectContaining({ action: 'merge', target_clue_id: 'clue-2', target_fingerprint: 'fp-2' }))
    await selectFirst(wrapper); await wrapper.get('.clue-review select').setValue('clue-2')
    await button(wrapper, '拒绝线索').trigger('click'); await flushPromises()
    expect(api.world.reviewSpatialClue.mock.lastCall[2]).not.toHaveProperty('target_clue_id')
  })
  it('取消确认不发请求，版本冲突保留说明且不自动刷新覆盖', async () => {
    const wrapper = await open(); await selectFirst(wrapper)
    confirmAction.mockImplementationOnce(() => {})
    await wrapper.get('form').trigger('submit'); await flushPromises()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
    expect(api.world.reviewSpatialClue).not.toHaveBeenCalled()
    api.world.reviewSpatialClue.mockRejectedValue({ status: 409 })
    await wrapper.get('textarea').setValue('保留这份说明')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('textarea').element.value).toBe('保留这份说明')
    expect(wrapper.text()).toContain('线索或来源已变化')
    expect(api.world.listSpatialClues).toHaveBeenCalledTimes(1)
  })
  it('确认期间锁住表单和选项，切换作品忽略旧回执', async () => {
    let approve
    confirmAction.mockImplementation((message, confirm) => { approve = confirm })
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.clue-choice').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ projectId: 'novel-2' }); approve(); await flushPromises()
    expect(api.world.reviewSpatialClue).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('旧桥位于南门以东。')
  })
  it('翻页受未提交说明保护，读取失败可以重试', async () => {
    api.world.listSpatialClues.mockResolvedValue({ items: [clue()], total_count: 21 })
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.get('textarea').setValue('未提交')
    expect(button(wrapper, '下一页').attributes('disabled')).toBeDefined()
    await button(wrapper, '收起复核').trigger('click'); await flushPromises()
    api.world.listSpatialClues.mockRejectedValueOnce(new Error('读取失败'))
    await button(wrapper, '下一页').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('读取失败')
    await button(wrapper, '重新读取').trigger('click'); await flushPromises()
    expect(api.world.listSpatialClues.mock.lastCall[1].offset).toBe(20)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
