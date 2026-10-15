import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapNodeMergePanel from '../../../vue/views/map/MapNodeMergePanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
enableAutoUnmount(afterEach)
const node = { id: 'source', title: '来源图', status: 'adopted', level: 'region' }
const target = { id: 'target', title: '目标图', status: 'adopted', level: 'region' }
const preview = () => ({ source_node_id: 'source', target_node_id: 'target', source_title: '来源图', target_title: '目标图', source_hierarchy: { level: 'region' }, target_hierarchy: { level: 'region' }, source_document: { features: [{}] }, target_document: { features: [] }, can_execute: true, blockers: [], fingerprint: 'frozen', affected_count: 3 })
const button = (wrapper, label) => wrapper.findAll('button').find(item => item.text() === label)
let api, confirmAction
beforeEach(() => {
  api = { world: { previewMapNodeMerge: vi.fn().mockResolvedValue(preview()), mergeMapNodes: vi.fn().mockResolvedValue({ target_node_id: 'target', label: '合并已完成' }), previewMapNodeMergeUndo: vi.fn().mockResolvedValue({ source_node_id: 'source', target_node_id: 'target', fingerprint: 'undo-frozen', affected_count: 3, can_undo: true, blockers: [] }), undoMapNodeMerge: vi.fn().mockResolvedValue({ target_node_id: 'target' }) } }
  confirmAction = vi.fn((_message, callback) => callback())
  setBridgeOverrides({ api, confirmAction })
})
afterEach(resetBridgeOverrides)
async function prepared() {
  const wrapper = mount(MapNodeMergePanel, { props: { projectId: 'novel', node, nodes: [node, target] } })
  await wrapper.get('select').setValue('target'); await button(wrapper, '预览地图合并').trigger('click'); await flushPromises()
  return wrapper
}
it('预览两个目标和源处置，勾选并二次确认后才写入', async () => {
  const wrapper = await prepared()
  expect(wrapper.text()).toContain('来源图'); expect(wrapper.text()).toContain('目标图'); expect(wrapper.text()).toContain('3 项变更')
  expect(button(wrapper, '确认合并地图').attributes('disabled')).toBeDefined()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await button(wrapper, '确认合并地图').trigger('click'); await flushPromises()
  expect(confirmAction).toHaveBeenCalledOnce()
  expect(api.world.mergeMapNodes).toHaveBeenCalledWith('novel', { source_node_id: 'source', target_node_id: 'target', preview_fingerprint: 'frozen', confirmed_source_disposition: true })
  expect(wrapper.emitted('changed')).toHaveLength(1)
})
it('409保留目标选择并清除过期确认，需要重新预览', async () => {
  api.world.mergeMapNodes.mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 409 }))
  const wrapper = await prepared(); await wrapper.get('input').setValue(true)
  await button(wrapper, '确认合并地图').trigger('click'); await flushPromises()
  expect(wrapper.get('select').element.value).toBe('target')
  expect(wrapper.get('[role="alert"]').text()).toContain('重新预览')
  expect(wrapper.find('input').exists()).toBe(false)
  await button(wrapper, '预览地图合并').trigger('click'); await flushPromises()
  expect(wrapper.get('input').element.checked).toBe(false)
})
it('含图片的实际blocker阻止写入', async () => {
  api.world.previewMapNodeMerge.mockResolvedValue({ ...preview(), can_execute: false, blockers: ['来源或目标已有图片页，当前合并不会移动图片'] })
  const wrapper = await prepared()
  expect(wrapper.text()).toContain('已有图片页')
  expect(button(wrapper, '确认合并地图')).toBeUndefined()
  expect(api.world.mergeMapNodes).not.toHaveBeenCalled()
})
it('目标历史提供独立撤回预览与确认', async () => {
  const wrapper = mount(MapNodeMergePanel, { props: { projectId: 'novel', node: { ...target, merged_sources: [{ id: 'source', title: '来源图' }] }, nodes: [target] } })
  await button(wrapper, '预览撤回合并').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('追加合并前内容的恢复版本')
  await button(wrapper, '确认撤回合并').trigger('click'); await flushPromises()
  expect(api.world.undoMapNodeMerge).toHaveBeenCalledWith('novel', { source_node_id: 'source', target_node_id: 'target', preview_fingerprint: 'undo-frozen', confirmed: true })
})
